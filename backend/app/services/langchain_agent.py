"""
LangChain Deep Agent 核心服务

基于 deepagents 的 create_deep_agent 实现数据查询 Agent。
使用原生 Skills 支持（progressive disclosure），自动加载 SKILL.md。

主要功能：
- 使用 deepagents create_deep_agent 创建 Agent（含内置文件系统工具）
- 原生 Skills 支持：自动发现并加载 backend/skills/ 下的技能
- 动态注册指标 Tools + 固定 Tools（generate_sql、execute_sql、recommend_chart）
- 通过 agent.astream() 流式获取 Agent 输出
- 将 Agent 输出转换为前端期望的 SSE StreamEvent
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncGenerator, Optional

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver

from app.core.config import settings
from app.models.schemas import StreamEvent, StreamEventType
from app.services.agent_tools import (
    ExecuteSQLTool,
    GenerateSQLTool,
    RecommendChartTool,
    _execute_sql_impl,
    _recommend_chart_impl,
    load_metric_tools,
)
from app.services.dashboard_tools import load_dashboard_tools
from app.services.skill_tools import load_skill_tools

logger = logging.getLogger(__name__)

# Skills 目录（相对于 backend 根目录）
SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


# ============================================================
# System Prompt
# ============================================================


def _build_system_prompt() -> str:
    """构建 Agent 系统提示词（含当前时间）"""
    now = datetime.now()
    weekday_map = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    return f"""你是一个专业的数据仓库查询助手。用户会用自然语言提出数据查询需求，你需要帮助他们获取数据。

## 当前时间

当前时间：{now.strftime("%Y-%m-%d %H:%M:%S")}（{weekday_map[now.weekday()]}）
今天日期：{now.strftime("%Y-%m-%d")}
明天日期：{tomorrow}

用户说"最近一周"、"昨天"、"上个月"等相对时间时，请基于上述当前时间计算出具体日期范围。
日期范围使用左闭右开区间，例如"最近7天"应该是 >= 7天前的日期 AND < 明天的日期（{tomorrow}），这样可以包含今天的数据。

## 工作流程

1. 分析用户的查询意图
2. 如果匹配某个技能（Skill），优先按技能指令执行
3. 如果匹配某个指标工具（metric_xxx），调用指标工具获取 SQL
4. 如果没有匹配的指标，调用 generate_sql 生成 SQL
5. 获得 SQL 后，调用 execute_sql 执行查询
6. 查询成功后，调用 recommend_chart 推荐图表（将 execute_sql 返回的 columns 字段原样传入 columns_json，row_count 传入行数）

## 规则

- 如果指标工具的参数有缺失且无默认值，直接向用户提问获取参数
- 不要编造数据，所有数据必须来自工具返回的结果
- 如果查询失败，向用户解释原因并建议修改方向
- 回复使用中文
- 当使用技能时，严格按照技能 SKILL.md 中定义的输出格式要求生成报告
"""


def _build_dashboard_builder_prompt() -> str:
    """构建 Dashboard Builder 模式的系统提示词

    在大屏构建模式下，Agent 使用 dashboard tools（create_panel、update_panel、remove_panel）
    来创建和管理面板，而非直接执行 SQL 查询。
    """
    now = datetime.now()
    weekday_map = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

    return f"""你是一个专业的数据大屏构建助手。用户通过自然语言描述需要的数据指标和展示形式，你需要帮助他们构建 Dashboard 大屏。

## 当前时间

当前时间：{now.strftime("%Y-%m-%d %H:%M:%S")}（{weekday_map[now.weekday()]}）
今天日期：{now.strftime("%Y-%m-%d")}

## 工作流程

1. 分析用户的描述，将其拆解为多个独立的数据指标需求
2. 对每个指标需求，调用 create_panel 工具创建一个面板
3. 如果用户要求修改已有面板，调用 update_panel 工具
4. 如果用户要求删除面板，调用 remove_panel 工具

## 重要规则

- 将用户描述拆解为多个独立指标，每个指标对应一个面板
- 每个面板的 title 应简洁描述展示的数据内容
- 每个面板的 description 应详细说明需要查询的数据，包含时间范围、聚合方式等
- 一次对话中可以多次调用 create_panel 创建多个面板
- 如果用户要求修改某个面板，使用 update_panel 并提供新的描述
- 如果用户要求删除某个面板，使用 remove_panel
- 如果无法理解用户的指标需求，向用户提问请求补充说明
- 回复使用中文，简要说明为用户创建了哪些面板
- 不要调用 generate_sql、execute_sql、recommend_chart 等工具，面板的 SQL 生成由 create_panel 内部完成
"""


# ============================================================
# DataQueryAgent 类
# ============================================================


class DataQueryAgent:
    """数据查询 Agent

    基于 deepagents create_deep_agent 实现，
    原生支持 Skills（progressive disclosure）。

    Attributes:
        _llm: ChatOpenAI 实例
        _metric_tools: 动态指标工具列表
        _agent: deepagents compiled graph
        _checkpointer: 内存检查点（对话记忆）
        _tools_loaded: 工具是否已加载
    """

    def __init__(self) -> None:
        """初始化 Agent"""
        self._llm = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )

        self._checkpointer = MemorySaver()
        self._metric_tools: list = []
        self._fixed_tools = [GenerateSQLTool(), ExecuteSQLTool(), RecommendChartTool()]
        self._dashboard_tools: list = []
        self._agent = None
        self._dashboard_agent = None
        self._tools_loaded = False

        # 使用 FilesystemBackend，以 backend/ 为根目录
        self._backend = FilesystemBackend(
            root_dir=str(BACKEND_ROOT),
            virtual_mode=True,
        )

        logger.info(
            "DataQueryAgent initialized (deepagents mode), model=%s, base_url=%s, skills_dir=%s",
            settings.llm_model, settings.llm_base_url, SKILLS_DIR,
        )

    async def _ensure_tools_loaded(self) -> None:
        """确保指标工具已加载并创建 Agent"""
        if not self._tools_loaded:
            await self.refresh_metric_tools()
            self._tools_loaded = True

    async def refresh_metric_tools(self) -> None:
        """刷新指标工具列表并重建 Agent（含 Dashboard Agent）"""
        logger.info("Refreshing metric tools and rebuilding deep agent")
        self._metric_tools = await load_metric_tools()

        # 加载 skill 脚本执行工具（自定义工具，用于执行 skills 目录下的脚本）
        skill_tools = load_skill_tools()

        # 加载 dashboard tools
        self._dashboard_tools = load_dashboard_tools()

        all_tools = self._fixed_tools + self._metric_tools + skill_tools

        # 构建 skills 路径列表（相对于 backend 根目录）
        skills_paths = []
        if SKILLS_DIR.exists():
            skills_paths = ["/skills/"]

        # 使用 create_deep_agent 创建默认 Agent
        self._agent = create_deep_agent(
            model=self._llm,
            tools=all_tools,
            system_prompt=_build_system_prompt(),
            backend=self._backend,
            skills=skills_paths if skills_paths else None,
            checkpointer=self._checkpointer,
        )

        # 创建 Dashboard Builder Agent（包含 dashboard tools）
        dashboard_all_tools = self._dashboard_tools + skill_tools
        self._dashboard_agent = create_deep_agent(
            model=self._llm,
            tools=dashboard_all_tools,
            system_prompt=_build_dashboard_builder_prompt(),
            backend=self._backend,
            skills=None,
            checkpointer=self._checkpointer,
        )

        logger.info(
            "Deep agent rebuilt, total_custom_tools=%d (fixed=%d, metrics=%d, skills=%d), "
            "dashboard_tools=%d, native_skills_paths=%s",
            len(all_tools), len(self._fixed_tools),
            len(self._metric_tools), len(skill_tools),
            len(self._dashboard_tools), skills_paths,
        )

    async def run(
        self,
        message: str,
        conversation_history: list[dict],
        auto_execute: bool = True,
        thread_id: str = "",
        mode: Optional[str] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """执行 Agent 查询

        使用 deepagents agent.astream() 流式获取输出，
        将 Agent 的工具调用和回复转换为 SSE 事件。
        当 mode="dashboard_builder" 时，使用 Dashboard Agent 并处理面板事件。

        Args:
            message: 用户消息
            conversation_history: 对话历史
            auto_execute: 是否自动执行 SQL
            thread_id: 会话线程ID（用于记忆）
            mode: Agent 工作模式（None 或 'dashboard_builder'）

        Yields:
            StreamEvent 对象
        """
        await self._ensure_tools_loaded()

        # 根据模式选择 Agent
        is_dashboard_mode = mode == "dashboard_builder"
        active_agent = self._dashboard_agent if is_dashboard_mode else self._agent

        logger.info(
            "Agent run started, message=%s, auto_execute=%s, thread_id=%s, mode=%s",
            message[:100], auto_execute, thread_id, mode,
        )

        # 1.发送 thinking 事件
        yield StreamEvent(
            type=StreamEventType.thinking,
            data={"message": "正在分析您的查询意图..."},
        )

        # 2.配置
        config = {"configurable": {"thread_id": thread_id or "default"}}

        # 3.使用 dashboard_builder 专用线程避免与普通查询混淆
        if is_dashboard_mode:
            config = {"configurable": {"thread_id": f"dashboard_{thread_id or 'default'}"}}

        # 4.调用 Agent 流式执行
        produced_sql = None
        produced_explanation = None
        result_sent = False

        try:
            async for event in active_agent.astream(
                {"messages": [{"role": "user", "content": message}]},
                config,
                stream_mode="updates",
            ):
                # 4.解析事件（deepagents 事件结构与 langgraph 一致）
                for node_name, node_output in event.items():
                    logger.debug(
                        "Stream event received, node=%s, output_keys=%s",
                        node_name, list(node_output.keys()) if isinstance(node_output, dict) else type(node_output).__name__,
                    )
                    if node_name == "tools":
                        # 工具执行完成，解析结果
                        messages = node_output.get("messages", [])
                        for msg in messages:
                            if not hasattr(msg, "content"):
                                continue
                            tool_name = getattr(msg, "name", "")
                            content = msg.content

                            try:
                                result_data = json.loads(content) if content else {}
                            except (json.JSONDecodeError, TypeError):
                                result_data = {}

                            # generate_sql 或 metric 工具
                            if tool_name == "generate_sql" or tool_name.startswith("metric_"):
                                if result_data.get("clarification_needed"):
                                    yield StreamEvent(
                                        type=StreamEventType.clarification,
                                        data={"message": result_data.get("message", "")},
                                    )
                                    return
                                if result_data.get("error"):
                                    yield StreamEvent(
                                        type=StreamEventType.error,
                                        data={"message": result_data["error"], "error_type": "tool_error"},
                                    )
                                    return
                                if result_data.get("sql"):
                                    produced_sql = result_data["sql"]
                                    produced_explanation = result_data.get("explanation", "")
                                    yield StreamEvent(
                                        type=StreamEventType.sql_preview,
                                        data={
                                            "sql": produced_sql,
                                            "explanation": produced_explanation,
                                            "source": result_data.get("source", "sql_generator"),
                                            "metric_name": result_data.get("metric_name"),
                                        },
                                    )
                                    # 确认模式：到此暂停
                                    if not auto_execute:
                                        return

                            # execute_sql 工具
                            elif tool_name == "execute_sql":
                                if result_data.get("error"):
                                    yield StreamEvent(
                                        type=StreamEventType.error,
                                        data={"message": result_data["error"], "error_type": "execution_error"},
                                    )
                                    return
                                if result_data.get("columns"):
                                    yield StreamEvent(
                                        type=StreamEventType.executing,
                                        data={"message": "正在执行查询..."},
                                    )
                                    yield StreamEvent(
                                        type=StreamEventType.result,
                                        data={
                                            "columns": result_data.get("columns", []),
                                            "rows": result_data.get("rows", []),
                                            "row_count": result_data.get("row_count", 0),
                                            "execution_time": result_data.get("execution_time", 0),
                                            "truncated": result_data.get("truncated", False),
                                        },
                                    )
                                    result_sent = True

                            # recommend_chart 工具
                            elif tool_name == "recommend_chart":
                                if result_data.get("recommended"):
                                    yield StreamEvent(
                                        type=StreamEventType.chart_recommendation,
                                        data={
                                            "recommended": result_data.get("recommended", "table"),
                                            "reason": result_data.get("reason", ""),
                                            "alternatives": result_data.get("alternatives", []),
                                        },
                                    )

                            # Dashboard tools（大屏构建模式）
                            elif tool_name == "create_panel":
                                if result_data.get("success"):
                                    yield StreamEvent(
                                        type=StreamEventType.panel_created,
                                        data={
                                            "panel_id": result_data.get("panel_id"),
                                            "title": result_data.get("title"),
                                            "sql": result_data.get("sql"),
                                            "chart_type": result_data.get("chart_type"),
                                            "position": result_data.get("position"),
                                            "query_data": result_data.get("query_data"),
                                            "query_error": result_data.get("query_error"),
                                        },
                                    )
                                elif result_data.get("error"):
                                    yield StreamEvent(
                                        type=StreamEventType.error,
                                        data={"message": result_data["error"], "error_type": "panel_error"},
                                    )

                            elif tool_name == "update_panel":
                                if result_data.get("success"):
                                    yield StreamEvent(
                                        type=StreamEventType.panel_updated,
                                        data={
                                            "panel_id": result_data.get("panel_id"),
                                            "title": result_data.get("title"),
                                            "sql": result_data.get("sql"),
                                            "chart_type": result_data.get("chart_type"),
                                            "position": result_data.get("position"),
                                            "query_data": result_data.get("query_data"),
                                            "query_error": result_data.get("query_error"),
                                        },
                                    )
                                elif result_data.get("error"):
                                    yield StreamEvent(
                                        type=StreamEventType.error,
                                        data={"message": result_data["error"], "error_type": "panel_error"},
                                    )

                            elif tool_name == "remove_panel":
                                if result_data.get("success"):
                                    yield StreamEvent(
                                        type=StreamEventType.panel_removed,
                                        data={
                                            "panel_id": result_data.get("panel_id"),
                                            "message": result_data.get("message", "面板已删除"),
                                        },
                                    )
                                elif result_data.get("error"):
                                    yield StreamEvent(
                                        type=StreamEventType.error,
                                        data={"message": result_data["error"], "error_type": "panel_error"},
                                    )

                    elif node_name == "agent":
                        # Agent 输出处理
                        messages = node_output.get("messages", [])
                        for msg in messages:
                            if not hasattr(msg, "content"):
                                continue
                            # 如果有 tool_calls，发送 tool_call 事件通知前端
                            if hasattr(msg, "tool_calls") and msg.tool_calls:
                                for tc in msg.tool_calls:
                                    tc_name = tc.get("name", "")
                                    tc_args = tc.get("args", {})
                                    # 生成友好的工具显示名称
                                    display_name = tc_name
                                    if tc_name.startswith("metric_"):
                                        display_name = "指标查询"
                                    elif tc_name.startswith("skill_"):
                                        display_name = tc_name.replace("skill_", "技能: ")
                                    elif tc_name == "generate_sql":
                                        display_name = "SQL 生成"
                                    elif tc_name == "execute_sql":
                                        display_name = "执行查询"
                                    elif tc_name == "recommend_chart":
                                        display_name = "图表推荐"
                                    elif tc_name == "create_panel":
                                        display_name = "创建面板"
                                    elif tc_name == "update_panel":
                                        display_name = "更新面板"
                                    elif tc_name == "remove_panel":
                                        display_name = "删除面板"
                                    elif tc_name in ("read_file", "write_file", "ls", "glob", "grep"):
                                        display_name = f"文件操作: {tc_name}"

                                    yield StreamEvent(
                                        type=StreamEventType.tool_call,
                                        data={
                                            "tool_name": tc_name,
                                            "display_name": display_name,
                                            "args": tc_args,
                                        },
                                    )
                                    # 捕获 execute_sql 实际执行的 SQL，用于更新前端显示
                                    if tc_name == "execute_sql" and tc_args.get("sql"):
                                        actual_sql = tc_args["sql"]
                                        logger.info(
                                            "execute_sql tool_call detected, actual_sql_preview=%s, produced_sql_preview=%s, match=%s",
                                            actual_sql[:80], (produced_sql or "")[:80], actual_sql == produced_sql,
                                        )
                                        if actual_sql != produced_sql:
                                            produced_sql = actual_sql
                                            logger.info("Sending updated sql_preview, source=agent_modified")
                                            yield StreamEvent(
                                                type=StreamEventType.sql_preview,
                                                data={
                                                    "sql": produced_sql,
                                                    "explanation": produced_explanation or "",
                                                    "source": "agent_modified",
                                                },
                                            )
                                continue
                            # Agent 直接文本回复（无工具调用）
                            if msg.content:
                                yield StreamEvent(
                                    type=StreamEventType.clarification,
                                    data={"message": msg.content},
                                )

                    else:
                        # deepagents 可能使用其他节点名称（如 middleware 节点）
                        # 尝试从任何包含 messages 的节点中提取文本回复
                        if isinstance(node_output, dict) and "messages" in node_output:
                            messages = node_output.get("messages", [])
                            for msg in messages:
                                if not hasattr(msg, "content"):
                                    continue
                                # 处理工具调用消息（content 可能为空）
                                if hasattr(msg, "tool_calls") and msg.tool_calls:
                                    for tc in msg.tool_calls:
                                        tc_name = tc.get("name", "")
                                        tc_args = tc.get("args", {})
                                        display_name = tc_name
                                        if tc_name.startswith("metric_"):
                                            display_name = "指标查询"
                                        elif tc_name == "generate_sql":
                                            display_name = "SQL 生成"
                                        elif tc_name == "execute_sql":
                                            display_name = "执行查询"

                                        yield StreamEvent(
                                            type=StreamEventType.tool_call,
                                            data={
                                                "tool_name": tc_name,
                                                "display_name": display_name,
                                                "args": tc_args,
                                            },
                                        )
                                        # 捕获 execute_sql 实际执行的 SQL，用于更新前端显示
                                        if tc_name == "execute_sql" and tc_args.get("sql"):
                                            actual_sql = tc_args["sql"]
                                            if actual_sql != produced_sql:
                                                produced_sql = actual_sql
                                                yield StreamEvent(
                                                    type=StreamEventType.sql_preview,
                                                    data={
                                                        "sql": produced_sql,
                                                        "explanation": produced_explanation or "",
                                                        "source": "agent_modified",
                                                    },
                                                )
                                    continue
                                # 跳过工具结果消息
                                if hasattr(msg, "type") and getattr(msg, "type", "") == "tool":
                                    continue
                                # 跳过空内容消息
                                if not msg.content:
                                    continue
                                # 文本回复
                                logger.info(
                                    "Text response from node=%s, content_length=%d",
                                    node_name, len(msg.content),
                                )
                                yield StreamEvent(
                                    type=StreamEventType.clarification,
                                    data={"message": msg.content},
                                )

        except Exception as e:
            logger.error("Agent execution error, error=%s", str(e))
            yield StreamEvent(
                type=StreamEventType.error,
                data={"message": f"Agent 执行错误：{str(e)}", "error_type": "agent_error"},
            )

    async def execute_confirmed_sql(
        self, sql: str
    ) -> AsyncGenerator[StreamEvent, None]:
        """执行已确认的 SQL 并推荐图表

        Args:
            sql: 已确认的 SQL 语句

        Yields:
            StreamEvent 对象
        """
        logger.info("Executing confirmed SQL, sql=%s", sql[:200])

        # 1.executing 事件
        yield StreamEvent(
            type=StreamEventType.executing,
            data={"message": "正在执行查询..."},
        )

        # 2.执行 SQL
        result_json = await _execute_sql_impl(sql)
        result = json.loads(result_json)

        if result.get("error"):
            yield StreamEvent(
                type=StreamEventType.error,
                data={"message": result["error"], "error_type": "execution_error"},
            )
            return

        # 3.result 事件
        yield StreamEvent(
            type=StreamEventType.result,
            data={
                "columns": result["columns"],
                "rows": result.get("rows", []),
                "row_count": result.get("row_count", 0),
                "execution_time": result.get("execution_time", 0),
                "truncated": result.get("truncated", False),
            },
        )

        # 4.推荐图表
        try:
            columns_json = json.dumps(result["columns"], ensure_ascii=False)
            chart_json = _recommend_chart_impl(columns_json, result.get("row_count", 0))
            chart_result = json.loads(chart_json)

            yield StreamEvent(
                type=StreamEventType.chart_recommendation,
                data={
                    "recommended": chart_result["recommended"],
                    "reason": chart_result.get("reason", ""),
                    "alternatives": chart_result.get("alternatives", []),
                },
            )
        except Exception as e:
            logger.warning("Chart recommendation failed, error=%s", str(e))


# ============================================================
# 全局单例
# ============================================================

data_query_agent = DataQueryAgent()
