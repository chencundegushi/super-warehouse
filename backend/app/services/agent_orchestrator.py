"""
Agent Orchestrator 服务（智能体编排器）

核心协调模块，负责理解用户意图、路由请求到各子系统、管理执行流程。
实现完整的查询处理流程：指标匹配→SQL生成→确认→执行→可视化推荐。

主要功能：
- process_query(): 异步生成器，协调完整查询流程并逐步 yield StreamEvent
- handle_confirmation(): 处理用户对 SQL 的确认/拒绝
- cancel_query(): 取消正在执行的查询
- 会话状态管理（pending_sql、active_query_id、conversation_id）
- 指标优先策略：先匹配指标，未命中时回退到 SQL Generator
- 多轮对话上下文注入：追问时结合历史 SQL 和结果
- 质疑处理：展示 SQL 并解释逻辑，提供验证方式
"""

import logging
import re
import uuid
from typing import AsyncGenerator, Optional

from app.core.config import settings
from app.models.schemas import (
    ChartRecommendation,
    DDLInfo,
    MessageInput,
    QueryRequest,
    QueryResult,
    SQLGenParams,
    SQLGenResult,
    StreamEvent,
    StreamEventType,
)
from app.services.conversation_manager import conversation_manager
from app.services.ddl_manager import DDLManager
from app.services.metric_engine import metric_engine
from app.services.query_executor import QueryExecutor
from app.services.sql_generator import SQLGenerator
from app.services.visualization_engine import visualization_engine

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
        pending_referenced_tables: 待确认 SQL 引用的表名
        active_query_id: 正在执行的查询ID
        ddl_context: 当前 DDL 上下文
        last_query: 最近一次用户查询
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
        self.pending_referenced_tables: list[str] = []
        self.active_query_id: Optional[str] = None
        self.ddl_context: list[DDLInfo] = []
        self.last_query: Optional[str] = None

    def clear_pending(self) -> None:
        """清除待确认状态"""
        self.pending_sql = None
        self.pending_explanation = None
        self.pending_referenced_tables = []

    def clear_active_query(self) -> None:
        """清除活跃查询状态"""
        self.active_query_id = None


# ============================================================
# 辅助函数
# ============================================================


def _is_challenge_query(message: str) -> bool:
    """判断用户消息是否为质疑类查询

    识别用户对查询结果的质疑，如"为什么"、"不对"、"怎么回事"等。

    Args:
        message: 用户消息文本

    Returns:
        是质疑类查询返回 True
    """
    challenge_patterns = [
        r'为什么',
        r'不对',
        r'不正确',
        r'有问题',
        r'怎么回事',
        r'结果不对',
        r'数据不对',
        r'质疑',
        r'怀疑',
        r'验证',
        r'确认一下',
        r'解释.*sql',
        r'sql.*解释',
        r'逻辑.*对不对',
    ]
    for pattern in challenge_patterns:
        if re.search(pattern, message, re.IGNORECASE):
            return True
    return False


def _build_challenge_response(sql: str, explanation: str) -> dict:
    """构建质疑响应数据

    展示 SQL 并解释逻辑，提供验证方式。

    Args:
        sql: 当前查询的 SQL 语句
        explanation: SQL 的解释说明

    Returns:
        质疑响应数据字典
    """
    # 1.提供验证方式建议
    verification_suggestions = []
    # 建议拆分子查询验证
    if "JOIN" in sql.upper():
        verification_suggestions.append(
            "可以将 JOIN 拆分为独立子查询分别执行，验证各部分数据是否正确"
        )
    if "WHERE" in sql.upper():
        verification_suggestions.append(
            "可以去除 WHERE 条件查看全量数据，确认筛选逻辑是否符合预期"
        )
    if "GROUP BY" in sql.upper():
        verification_suggestions.append(
            "可以添加明细数据抽样查询，验证聚合结果是否正确"
        )
    # 默认建议
    if not verification_suggestions:
        verification_suggestions.append(
            "可以添加 LIMIT 10 查看明细数据样本进行验证"
        )

    return {
        "sql": sql,
        "explanation": explanation,
        "verification_suggestions": verification_suggestions,
    }


# ============================================================
# AgentOrchestrator 服务类
# ============================================================


class AgentOrchestrator:
    """智能体编排器

    核心协调模块，管理查询处理的完整生命周期。
    通过异步生成器逐步 yield StreamEvent，实现 SSE 流式输出。

    Attributes:
        _sessions: 会话状态字典，key 为 session_id
        _sql_generator: SQL 生成器实例
        _query_executor: 查询执行器实例
        _ddl_manager: DDL 管理器实例
    """

    def __init__(self) -> None:
        """初始化智能体编排器"""
        self._sessions: dict[str, SessionState] = {}
        self._sql_generator = SQLGenerator()
        self._query_executor = QueryExecutor()
        self._ddl_manager = DDLManager()
        logger.info("AgentOrchestrator initialized")

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

    def _remove_session(self, session_id: str) -> None:
        """移除会话状态

        Args:
            session_id: 会话标识
        """
        self._sessions.pop(session_id, None)
        logger.info("Session removed, session_id=%s", session_id)

    # ============================================================
    # 核心方法：process_query
    # ============================================================

    async def process_query(
        self, request: QueryRequest
    ) -> AsyncGenerator[StreamEvent, None]:
        """处理用户查询，返回 SSE 流式事件

        完整流程：
        1. 接收用户查询 → yield thinking 事件
        2. 尝试指标匹配 → 命中则提取参数填充 SQL 模板
        3. 未命中指标 → 使用 SQL Generator 基于 DDL 生成 SQL
        4. 意图不明确 → yield clarification 事件并停止
        5. yield sql_preview 事件（等待用户确认）

        Args:
            request: 查询请求

        Yields:
            StreamEvent 对象，按流程逐步推送
        """
        session_id = request.session_id
        message = request.message
        conversation_id = request.conversation_id

        logger.info(
            "Processing query, session_id=%s, message=%s, conversation_id=%s",
            session_id, message[:100], conversation_id,
        )

        # 1.获取或创建会话状态
        session = self._get_or_create_session(session_id)
        session.last_query = message

        # 2.处理对话ID：如果未提供则创建新对话
        if conversation_id:
            session.conversation_id = conversation_id
        elif not session.conversation_id:
            conv = await conversation_manager.create_conversation(
                title=message[:30]
            )
            session.conversation_id = conv.id
            logger.info(
                "New conversation created, conversation_id=%s",
                session.conversation_id,
            )

        # 3.保存用户消息到对话历史
        await conversation_manager.add_message(
            session.conversation_id,
            MessageInput(role="user", content=message),
        )

        # 4.yield thinking 事件
        yield StreamEvent(
            type=StreamEventType.thinking,
            data={"message": "正在分析您的查询意图..."},
        )

        # 5.检查是否为质疑类查询
        if _is_challenge_query(message):
            async for event in self._handle_challenge(session):
                yield event
            return

        # 6.加载 DDL 上下文
        session.ddl_context = self._ddl_manager.list_loaded_ddl()

        # 7.指标优先策略：先尝试匹配指标
        try:
            match_result = await metric_engine.match_metric(message)
        except Exception as e:
            logger.warning("Metric matching failed, error=%s", str(e))
            match_result = None

        if match_result:
            # 8.指标命中：提取参数并填充 SQL 模板
            async for event in self._handle_metric_match(
                session, message, match_result
            ):
                yield event
        else:
            # 9.未命中指标：回退到 SQL Generator
            async for event in self._handle_sql_generation(session, message):
                yield event

        # 10.自动执行模式：如果有待确认的SQL且请求要求自动执行
        if request.auto_execute and session.pending_sql:
            logger.info(
                "Auto-executing SQL, session_id=%s", session_id
            )
            async for event in self.handle_confirmation(
                session_id=session_id,
                confirmed=True,
                feedback=None,
            ):
                yield event

    # ============================================================
    # 指标匹配处理
    # ============================================================

    async def _handle_metric_match(
        self,
        session: SessionState,
        message: str,
        match_result,
    ) -> AsyncGenerator[StreamEvent, None]:
        """处理指标匹配命中的情况

        提取参数、检测缺失参数、填充 SQL 模板。

        Args:
            session: 会话状态
            message: 用户消息
            match_result: 指标匹配结果

        Yields:
            StreamEvent 对象
        """
        metric = match_result.metric
        logger.info(
            "Metric matched, metric_name=%s, similarity=%.4f",
            metric.name, match_result.similarity,
        )

        yield StreamEvent(
            type=StreamEventType.thinking,
            data={
                "message": f"匹配到指标「{metric.name}」，正在提取参数...",
            },
        )

        # 1.提取参数
        extracted_params = await metric_engine.extract_parameters(
            message, metric
        )

        # 2.检测缺失参数
        missing_params = await metric_engine.detect_missing_parameters(
            metric, extracted_params
        )

        if missing_params:
            # 3.缺失必填参数，请求用户补充
            logger.info(
                "Missing parameters detected, metric=%s, missing=%s",
                metric.name, missing_params,
            )
            yield StreamEvent(
                type=StreamEventType.clarification,
                data={
                    "message": f"指标「{metric.name}」需要以下参数，请补充：",
                    "missing_parameters": missing_params,
                },
            )
            return

        # 4.填充 SQL 模板
        sql = metric.sql_template
        for param_name, param_value in extracted_params.items():
            sql = sql.replace(f"${{{param_name}}}", str(param_value))

        explanation = (
            f"基于指标「{metric.name}」生成 SQL，"
            f"参数：{extracted_params}"
        )

        # 5.设置待确认状态
        session.pending_sql = sql
        session.pending_explanation = explanation
        session.pending_referenced_tables = []

        # 6.yield sql_preview 事件
        yield StreamEvent(
            type=StreamEventType.sql_preview,
            data={
                "sql": sql,
                "explanation": explanation,
                "source": "metric",
                "metric_name": metric.name,
            },
        )

    # ============================================================
    # SQL 生成处理
    # ============================================================

    async def _handle_sql_generation(
        self, session: SessionState, message: str
    ) -> AsyncGenerator[StreamEvent, None]:
        """处理基于 DDL 的 SQL 生成

        获取对话上下文，构建 SQL 生成参数，调用 SQL Generator。

        Args:
            session: 会话状态
            message: 用户消息

        Yields:
            StreamEvent 对象
        """
        logger.info(
            "Falling back to SQL generation, session_id=%s", session.session_id
        )

        yield StreamEvent(
            type=StreamEventType.thinking,
            data={"message": "未匹配到预定义指标，正在基于表结构生成 SQL..."},
        )

        # 1.获取对话上下文（多轮对话支持）
        conversation_history = []
        if session.conversation_id:
            context = await conversation_manager.get_context(
                session.conversation_id
            )
            messages = context.get("messages", [])
            for msg in messages:
                msg_dict = {
                    "role": msg.role,
                    "content": msg.content,
                }
                if msg.sql:
                    msg_dict["sql"] = msg.sql
                conversation_history.append(msg_dict)

        # 2.检测未加载的表（如果 DDL 上下文为空，提示用户）
        if not session.ddl_context:
            logger.warning("No DDL context available, session_id=%s", session.session_id)
            yield StreamEvent(
                type=StreamEventType.clarification,
                data={
                    "message": "当前没有已加载的表结构信息，请先在 DDL 管理页面加载数据库表结构。",
                },
            )
            return

        # 3.构建 SQL 生成参数
        sql_gen_params = SQLGenParams(
            user_query=message,
            ddl_context=session.ddl_context,
            conversation_history=conversation_history,
            previous_sql=session.pending_sql,
        )

        # 4.调用 SQL Generator
        try:
            result: SQLGenResult = self._sql_generator.generate_sql(
                sql_gen_params
            )
        except Exception as e:
            logger.error(
                "SQL generation failed, session_id=%s, error=%s",
                session.session_id, str(e),
            )
            yield StreamEvent(
                type=StreamEventType.error,
                data={
                    "message": f"SQL 生成失败：{str(e)}",
                    "error_type": "sql_generation_error",
                },
            )
            return

        # 5.检查是否需要澄清（意图不明确）
        if not result.sql:
            logger.info(
                "Intent unclear, requesting clarification, session_id=%s",
                session.session_id,
            )
            yield StreamEvent(
                type=StreamEventType.clarification,
                data={
                    "message": result.explanation
                    or "无法理解您的查询意图，请补充更多细节。",
                },
            )
            return

        # 6.检测 SQL 中引用的未加载表
        if result.referenced_tables:
            database = settings.doris_database
            unloaded = self._ddl_manager.detect_unloaded_tables(
                result.referenced_tables, database
            )
            if unloaded:
                logger.info(
                    "Unloaded tables detected, tables=%s", unloaded
                )
                yield StreamEvent(
                    type=StreamEventType.clarification,
                    data={
                        "message": f"查询涉及以下未加载的表：{', '.join(unloaded)}，建议先加载这些表的结构信息。",
                        "unloaded_tables": unloaded,
                    },
                )
                return

        # 7.设置待确认状态
        session.pending_sql = result.sql
        session.pending_explanation = result.explanation
        session.pending_referenced_tables = result.referenced_tables

        # 8.yield sql_preview 事件
        yield StreamEvent(
            type=StreamEventType.sql_preview,
            data={
                "sql": result.sql,
                "explanation": result.explanation,
                "confidence": result.confidence,
                "referenced_tables": result.referenced_tables,
                "source": "sql_generator",
            },
        )

    # ============================================================
    # 质疑处理
    # ============================================================

    async def _handle_challenge(
        self, session: SessionState
    ) -> AsyncGenerator[StreamEvent, None]:
        """处理用户对查询结果的质疑

        展示当前 SQL 并解释逻辑，提供验证方式。

        Args:
            session: 会话状态

        Yields:
            StreamEvent 对象
        """
        logger.info(
            "Handling challenge query, session_id=%s", session.session_id
        )

        # 1.获取最近的 SQL 和解释
        sql = session.pending_sql
        explanation = session.pending_explanation or ""

        # 2.如果没有待确认的 SQL，从对话历史中获取最近的 SQL
        if not sql and session.conversation_id:
            messages = await conversation_manager.get_messages(
                session.conversation_id
            )
            # 从后往前找最近一条包含 SQL 的消息
            for msg in reversed(messages):
                if msg.sql:
                    sql = msg.sql
                    explanation = msg.content or ""
                    break

        if not sql:
            yield StreamEvent(
                type=StreamEventType.clarification,
                data={
                    "message": "当前没有可供验证的 SQL 查询，请先提出一个数据查询问题。",
                },
            )
            return

        # 3.构建质疑响应
        challenge_data = _build_challenge_response(sql, explanation)

        yield StreamEvent(
            type=StreamEventType.result,
            data={
                "type": "challenge_response",
                "sql": challenge_data["sql"],
                "explanation": challenge_data["explanation"],
                "verification_suggestions": challenge_data[
                    "verification_suggestions"
                ],
            },
        )

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
        拒绝时：接收反馈 → 重新生成 SQL

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
                data={
                    "message": "会话不存在或已过期，请重新发起查询。",
                    "error_type": "session_not_found",
                },
            )
            return

        if not session.pending_sql:
            yield StreamEvent(
                type=StreamEventType.error,
                data={
                    "message": "当前没有待确认的 SQL 语句。",
                    "error_type": "no_pending_sql",
                },
            )
            return

        if confirmed:
            # 用户确认执行 SQL
            async for event in self._execute_and_visualize(session):
                yield event
        else:
            # 用户拒绝，根据反馈重新生成
            async for event in self._refine_sql(session, feedback):
                yield event

    # ============================================================
    # SQL 执行与可视化
    # ============================================================

    async def _execute_and_visualize(
        self, session: SessionState
    ) -> AsyncGenerator[StreamEvent, None]:
        """执行 SQL 并推荐可视化

        流程：yield executing → 执行 SQL（带重试）→ yield result → yield chart_recommendation

        Args:
            session: 会话状态

        Yields:
            StreamEvent 对象
        """
        sql = session.pending_sql
        logger.info(
            "Executing SQL, session_id=%s, sql=%s",
            session.session_id, sql[:200] if sql else "",
        )

        # 1.yield executing 事件
        query_id = str(uuid.uuid4())
        session.active_query_id = query_id

        yield StreamEvent(
            type=StreamEventType.executing,
            data={
                "message": "正在执行查询...",
                "query_id": query_id,
            },
        )

        # 2.定义 SQL 修正回调（用于重试机制）
        async def fix_callback(failed_sql: str, error_msg: str) -> str:
            """SQL 执行失败时的修正回调"""
            context = {
                "ddl_context": session.ddl_context,
                "conversation_history": [],
            }
            refined = self._sql_generator.refine_sql_with_feedback(
                failed_sql, f"执行错误：{error_msg}", context
            )
            return refined.sql if refined.sql else failed_sql

        # 3.执行 SQL（带重试，最多3次）
        try:
            result: QueryResult = await self._query_executor.execute_with_retry(
                sql, fix_callback=fix_callback
            )
        except TimeoutError:
            session.clear_active_query()
            logger.error(
                "Query timed out, session_id=%s, query_id=%s",
                session.session_id, query_id,
            )
            yield StreamEvent(
                type=StreamEventType.error,
                data={
                    "message": "查询超时（超过30秒），请尝试优化查询条件或缩小数据范围。",
                    "error_type": "timeout",
                },
            )
            return
        except ConnectionError as e:
            session.clear_active_query()
            logger.error(
                "Connection failed, session_id=%s, error=%s",
                session.session_id, str(e),
            )
            yield StreamEvent(
                type=StreamEventType.error,
                data={
                    "message": f"数据库连接失败：{str(e)}",
                    "error_type": "connection_error",
                },
            )
            return
        except RuntimeError as e:
            session.clear_active_query()
            logger.error(
                "Query failed after retries, session_id=%s, error=%s",
                session.session_id, str(e),
            )
            yield StreamEvent(
                type=StreamEventType.error,
                data={
                    "message": f"查询执行失败（已重试3次）：{str(e)}",
                    "error_type": "execution_error",
                },
            )
            return

        session.clear_active_query()

        # 4.保存 Agent 回复消息（含 SQL 和结果）
        result_summary = {
            "columns": [col.model_dump() for col in result.columns],
            "row_count": result.row_count,
            "truncated": result.truncated,
            "execution_time": result.execution_time,
        }
        await conversation_manager.add_message(
            session.conversation_id,
            MessageInput(
                role="agent",
                content=session.pending_explanation or "查询执行完成",
                sql=sql,
                query_result=result_summary,
            ),
        )

        # 5.yield result 事件
        yield StreamEvent(
            type=StreamEventType.result,
            data={
                "columns": [col.model_dump() for col in result.columns],
                "rows": result.rows,
                "row_count": result.row_count,
                "execution_time": result.execution_time,
                "truncated": result.truncated,
            },
        )

        # 6.推荐图表类型
        try:
            chart_rec: ChartRecommendation = (
                visualization_engine.recommend_chart_type(result)
            )
            chart_config = visualization_engine.generate_chart_config(
                result, chart_rec.recommended
            )

            yield StreamEvent(
                type=StreamEventType.chart_recommendation,
                data={
                    "recommended": chart_rec.recommended.value,
                    "reason": chart_rec.reason,
                    "alternatives": [
                        alt.value for alt in chart_rec.alternatives
                    ],
                    "chart_config": chart_config,
                },
            )
        except Exception as e:
            logger.warning(
                "Chart recommendation failed, session_id=%s, error=%s",
                session.session_id, str(e),
            )
            # 图表推荐失败不影响主流程

        # 7.清除待确认状态
        session.clear_pending()

    # ============================================================
    # SQL 修正（拒绝后重新生成）
    # ============================================================

    async def _refine_sql(
        self, session: SessionState, feedback: Optional[str]
    ) -> AsyncGenerator[StreamEvent, None]:
        """根据用户反馈修正 SQL

        接收用户的修改意见，调用 SQL Generator 重新生成 SQL。

        Args:
            session: 会话状态
            feedback: 用户反馈/修改意见

        Yields:
            StreamEvent 对象
        """
        original_sql = session.pending_sql
        effective_feedback = feedback or "请重新生成 SQL"

        logger.info(
            "Refining SQL, session_id=%s, feedback=%s",
            session.session_id, effective_feedback[:100],
        )

        yield StreamEvent(
            type=StreamEventType.thinking,
            data={"message": "正在根据您的反馈修正 SQL..."},
        )

        # 1.获取对话上下文
        conversation_history = []
        if session.conversation_id:
            context = await conversation_manager.get_context(
                session.conversation_id
            )
            messages = context.get("messages", [])
            for msg in messages:
                msg_dict = {
                    "role": msg.role,
                    "content": msg.content,
                }
                if msg.sql:
                    msg_dict["sql"] = msg.sql
                conversation_history.append(msg_dict)

        # 2.调用 SQL Generator 修正
        context_data = {
            "ddl_context": session.ddl_context,
            "conversation_history": conversation_history,
        }

        try:
            refined_result: SQLGenResult = (
                self._sql_generator.refine_sql_with_feedback(
                    original_sql, effective_feedback, context_data
                )
            )
        except Exception as e:
            logger.error(
                "SQL refinement failed, session_id=%s, error=%s",
                session.session_id, str(e),
            )
            yield StreamEvent(
                type=StreamEventType.error,
                data={
                    "message": f"SQL 修正失败：{str(e)}",
                    "error_type": "refinement_error",
                },
            )
            return

        if not refined_result.sql:
            yield StreamEvent(
                type=StreamEventType.clarification,
                data={
                    "message": refined_result.explanation
                    or "无法根据反馈生成有效的 SQL，请提供更具体的修改意见。",
                },
            )
            return

        # 3.更新待确认状态
        session.pending_sql = refined_result.sql
        session.pending_explanation = refined_result.explanation
        session.pending_referenced_tables = refined_result.referenced_tables

        # 4.yield 新的 sql_preview 事件
        yield StreamEvent(
            type=StreamEventType.sql_preview,
            data={
                "sql": refined_result.sql,
                "explanation": refined_result.explanation,
                "confidence": refined_result.confidence,
                "referenced_tables": refined_result.referenced_tables,
                "source": "sql_generator_refined",
            },
        )

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
                data={
                    "message": "会话不存在或已过期。",
                    "error_type": "session_not_found",
                },
            )

        if not session.active_query_id:
            return StreamEvent(
                type=StreamEventType.error,
                data={
                    "message": "当前没有正在执行的查询。",
                    "error_type": "no_active_query",
                },
            )

        # 1.调用 QueryExecutor 取消查询
        try:
            await self._query_executor.cancel_query(session.active_query_id)
            session.clear_active_query()
            logger.info(
                "Query cancelled successfully, session_id=%s", session_id
            )
            return StreamEvent(
                type=StreamEventType.result,
                data={
                    "message": "查询已取消。",
                    "cancelled": True,
                },
            )
        except ValueError as e:
            logger.warning(
                "Cancel failed, session_id=%s, error=%s",
                session_id, str(e),
            )
            session.clear_active_query()
            return StreamEvent(
                type=StreamEventType.error,
                data={
                    "message": f"取消查询失败：{str(e)}",
                    "error_type": "cancel_error",
                },
            )

    # ============================================================
    # 会话状态查询
    # ============================================================

    def get_session_state(self, session_id: str) -> Optional[dict]:
        """获取会话状态摘要

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
            "has_active_query": session.active_query_id is not None,
        }


# ============================================================
# 全局单例
# ============================================================

agent_orchestrator = AgentOrchestrator()
