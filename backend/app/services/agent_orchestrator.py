"""
Agent Orchestrator 服务（智能体编排器）

基于 LangChain Agent 的核心协调模块，负责管理会话状态、
调用 LangChain Agent 处理查询、处理 SQL 确认/拒绝流程。

主要功能：
- process_query(): 异步生成器，调用 LangChain Agent 并逐步 yield StreamEvent
- handle_confirmation(): 处理用户对 SQL 的确认/拒绝
- cancel_query(): 取消正在执行的查询
- 会话状态管理（pending_sql、conversation_id）
- Dashboard Builder 模式：当 mode="dashboard_builder" 时，注册 dashboard tools
"""

import logging
import uuid
from typing import AsyncGenerator, Optional

from app.core.config import settings
from app.models.schemas import (
    MessageInput,
    QueryRequest,
    StreamEvent,
    StreamEventType,
)
from app.services.conversation_manager import conversation_manager
from app.services.dashboard_tools import load_dashboard_tools, reset_panel_state
from app.services.langchain_agent import data_query_agent

logger = logging.getLogger(__name__)


# ============================================================
# 会话状态定义
# ============================================================


class SessionState:
    """会话状态

    跟踪单个会话的当前处理阶段和中间数据。

    Attributes:
        session_id: 会话标识
        conversation_id: 对话ID
        pending_sql: 待确认的 SQL 语句
        pending_explanation: 待确认 SQL 的解释
        last_query: 最近一次用户查询
        mode: Agent 工作模式（None 或 'dashboard_builder'）
    """

    def __init__(self, session_id: str) -> None:
        """初始化会话状态

        Args:
            session_id: 会话标识
        """
        self.session_id: str = session_id
        self.conversation_id: Optional[str] = None
        self.pending_sql: Optional[str] = None
        self.pending_explanation: Optional[str] = None
        self.last_query: Optional[str] = None
        self.mode: Optional[str] = None

    def clear_pending(self) -> None:
        """清除待确认状态"""
        self.pending_sql = None
        self.pending_explanation = None


# ============================================================
# AgentOrchestrator 服务类
# ============================================================


class AgentOrchestrator:
    """智能体编排器

    管理会话状态，调用 LangChain Agent 处理查询。
    通过异步生成器逐步 yield StreamEvent，实现 SSE 流式输出。

    Attributes:
        _sessions: 会话状态字典，key 为 session_id
    """

    def __init__(self) -> None:
        """初始化智能体编排器"""
        self._sessions: dict[str, SessionState] = {}
        logger.info("AgentOrchestrator initialized (LangChain mode)")

    def _get_or_create_session(self, session_id: str) -> SessionState:
        """获取或创建会话状态

        Args:
            session_id: 会话标识

        Returns:
            会话状态对象
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(session_id)
            logger.info("Session created, session_id=%s", session_id)
        return self._sessions[session_id]

    # ============================================================
    # 核心方法：process_query
    # ============================================================

    async def process_query(
        self, request: QueryRequest
    ) -> AsyncGenerator[StreamEvent, None]:
        """处理用户查询，返回 SSE 流式事件

        调用 LangChain Agent 处理查询，Agent 自主决定使用指标工具
        还是生成 SQL，并编排完整的查询流程。
        当 mode="dashboard_builder" 时，注册 dashboard tools 并使用大屏构建模式。

        Args:
            request: 查询请求

        Yields:
            StreamEvent 对象，按流程逐步推送
        """
        session_id = request.session_id
        message = request.message
        conversation_id = request.conversation_id
        auto_execute = request.auto_execute
        mode = request.mode

        logger.info(
            "Processing query, session_id=%s, message=%s, auto_execute=%s, mode=%s",
            session_id, message[:100], auto_execute, mode,
        )

        # 1.获取或创建会话状态
        session = self._get_or_create_session(session_id)
        session.last_query = message

        # 2.检测 dashboard builder 模式切换
        if mode == "dashboard_builder" and session.mode != "dashboard_builder":
            # 首次进入大屏构建模式，重置面板状态
            reset_panel_state()
            logger.info("Dashboard builder mode activated, panel state reset, session_id=%s", session_id)
        session.mode = mode

        # 3.处理对话ID
        if conversation_id:
            session.conversation_id = conversation_id
        elif not session.conversation_id:
            conv = await conversation_manager.create_conversation(
                title=message[:30]
            )
            session.conversation_id = conv.id
            logger.info("New conversation created, conversation_id=%s", session.conversation_id)

        # 4.保存用户消息到对话历史
        await conversation_manager.add_message(
            session.conversation_id,
            MessageInput(role="user", content=message),
        )

        # 5.获取对话上下文
        conversation_history = []
        if session.conversation_id:
            context = await conversation_manager.get_context(session.conversation_id)
            messages = context.get("messages", [])
            for msg in messages[:-1]:  # 排除刚添加的当前消息
                msg_dict = {"role": msg.role, "content": msg.content}
                if msg.sql:
                    msg_dict["sql"] = msg.sql
                conversation_history.append(msg_dict)

        # 6.调用 LangChain Agent
        pending_sql = None
        pending_explanation = None

        async for event in data_query_agent.run(
            message=message,
            conversation_history=conversation_history,
            auto_execute=auto_execute,
            mode=mode,
            thread_id=session_id,
        ):
            # 拦截 sql_preview 事件，保存待确认 SQL
            if event.type == StreamEventType.sql_preview:
                pending_sql = event.data.get("sql")
                pending_explanation = event.data.get("explanation", "")

            # 拦截 result 事件，保存到对话历史
            if event.type == StreamEventType.result:
                await conversation_manager.add_message(
                    session.conversation_id,
                    MessageInput(
                        role="agent",
                        content=pending_explanation or "查询执行完成",
                        sql=pending_sql,
                        query_result={
                            "row_count": event.data.get("row_count", 0),
                            "execution_time": event.data.get("execution_time", 0),
                        },
                    ),
                )

            yield event

        # 7.更新会话状态
        if pending_sql and not auto_execute:
            session.pending_sql = pending_sql
            session.pending_explanation = pending_explanation
        else:
            session.clear_pending()

    # ============================================================
    # SQL 确认处理
    # ============================================================

    async def handle_confirmation(
        self,
        session_id: str,
        confirmed: bool,
        feedback: Optional[str] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """处理用户对 SQL 的确认或拒绝

        确认时：执行 SQL → 返回结果 → 推荐图表
        拒绝时：将反馈传给 Agent 重新生成 SQL

        Args:
            session_id: 会话标识
            confirmed: 是否确认执行
            feedback: 拒绝时的修改意见

        Yields:
            StreamEvent 对象
        """
        logger.info(
            "Handling confirmation, session_id=%s, confirmed=%s, feedback=%s",
            session_id, confirmed, feedback,
        )

        session = self._sessions.get(session_id)
        if not session:
            yield StreamEvent(
                type=StreamEventType.error,
                data={"message": "会话不存在或已过期，请重新发起查询。", "error_type": "session_not_found"},
            )
            return

        if not session.pending_sql:
            yield StreamEvent(
                type=StreamEventType.error,
                data={"message": "当前没有待确认的 SQL 语句。", "error_type": "no_pending_sql"},
            )
            return

        if confirmed:
            # 用户确认：执行 SQL 并推荐图表
            sql = session.pending_sql
            explanation = session.pending_explanation

            async for event in data_query_agent.execute_confirmed_sql(sql):
                # 拦截 result 事件保存到对话历史
                if event.type == StreamEventType.result:
                    await conversation_manager.add_message(
                        session.conversation_id,
                        MessageInput(
                            role="agent",
                            content=explanation or "查询执行完成",
                            sql=sql,
                            query_result={
                                "row_count": event.data.get("row_count", 0),
                                "execution_time": event.data.get("execution_time", 0),
                            },
                        ),
                    )
                yield event

            session.clear_pending()
        else:
            # 用户拒绝：将反馈传给 Agent 重新生成
            effective_feedback = feedback or "请重新生成 SQL"
            refined_message = f"用户对之前生成的 SQL 不满意，反馈：{effective_feedback}。原 SQL：{session.pending_sql}"

            session.clear_pending()

            # 获取对话上下文
            conversation_history = []
            if session.conversation_id:
                context = await conversation_manager.get_context(session.conversation_id)
                messages = context.get("messages", [])
                for msg in messages:
                    msg_dict = {"role": msg.role, "content": msg.content}
                    if msg.sql:
                        msg_dict["sql"] = msg.sql
                    conversation_history.append(msg_dict)

            # 重新调用 Agent（确认模式，只生成 SQL 不执行）
            async for event in data_query_agent.run(
                message=refined_message,
                conversation_history=conversation_history,
                auto_execute=False,
                thread_id=session_id,
            ):
                if event.type == StreamEventType.sql_preview:
                    session.pending_sql = event.data.get("sql")
                    session.pending_explanation = event.data.get("explanation", "")
                yield event

    # ============================================================
    # 查询取消
    # ============================================================

    async def cancel_query(self, session_id: str) -> StreamEvent:
        """取消正在执行的查询

        Args:
            session_id: 会话标识

        Returns:
            取消结果的 StreamEvent
        """
        logger.info("Cancelling query, session_id=%s", session_id)

        session = self._sessions.get(session_id)
        if not session:
            return StreamEvent(
                type=StreamEventType.error,
                data={"message": "会话不存在或已过期。", "error_type": "session_not_found"},
            )

        session.clear_pending()
        return StreamEvent(
            type=StreamEventType.result,
            data={"message": "查询已取消。", "cancelled": True},
        )

    # ============================================================
    # 工具刷新
    # ============================================================

    async def refresh_tools(self) -> None:
        """刷新 Agent 的工具列表（指标变更后调用）"""
        await data_query_agent.refresh_metric_tools()
        logger.info("Agent tools refreshed")

    # ============================================================
    # 会话状态查询
    # ============================================================

    def get_session_state(self, session_id: str) -> Optional[dict]:
        """获取会话状态信息

        Args:
            session_id: 会话标识

        Returns:
            会话状态字典，不存在时返回 None
        """
        session = self._sessions.get(session_id)
        if not session:
            return None
        return {
            "session_id": session.session_id,
            "conversation_id": session.conversation_id,
            "has_pending_sql": session.pending_sql is not None,
            "last_query": session.last_query,
            "mode": session.mode,
        }


# ============================================================
# 全局单例
# ============================================================

agent_orchestrator = AgentOrchestrator()
