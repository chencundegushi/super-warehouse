"""
LangChain Agent 核心服务

基于 langgraph 的 create_react_agent 实现数据查询 Agent。
使用 @tool 装饰器定义工具，由 langgraph 处理 tool calling 循环。

主要功能：
- 使用 langgraph create_react_agent 创建 Agent
- 动态注册指标 Tools + 固定 Tools（generate_sql、execute_sql、recommend_chart）
- 通过 agent.astream() 流式获取 Agent 输出
- 将 Agent 输出转换为前端期望的 SSE StreamEvent
"""

import json
import logging
from datetime import datetime, timedelta
from typing import AsyncGenerator

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent

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
from app.services.skill_tools import load_skill_tools

logger = logging.getLogger(__name__)


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
2. 如果匹配某个指标工具（metric_xxx），优先调用指标工具获取 SQL
3. 如果没有匹配的指标，调用 generate_sql 生成 SQL
4. 获得 SQL 后，调用 execute_sql 执行查询
5. 查询成功后，调用 recommend_chart 推荐图表（将 execute_sql 返回的 columns 字段原样传入 columns_json，row_count 传入行数）

## 规则

- 如果指标工具的参数有缺失且无默认值，直接向用户提问获取参数
- 不要编造数据，所有数据必须来自 execute_sql 的返回结果
- 如果查询失败，向用户解释原因并建议修改方向
- 回复使用中文
"""


# ============================================================
# DataQueryAgent 类
# ============================================================


class DataQueryAgent:
    """数据查询 Agent

    基于 langgraph create_react_agent 实现，
    与 deepagents 使用相同的底层机制。

    Attributes:
        _llm: ChatOpenAI 实例
        _metric_tools: 动态指标工具列表
        _agent: langgraph react agent
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

        self._checkpointer = InMemorySaver()
        self._metric_tools: list = []
        self._fixed_tools = [GenerateSQLTool(), ExecuteSQLTool(), RecommendChartTool()]
        self._agent = None
        self._tools_loaded = False

        logger.info(
            "DataQueryAgent initialized, model=%s, base_url=%s",
            settings.llm_model, settings.llm_base_url,
        )

    async def _ensure_tools_loaded(self) -> None:
        """确保指标工具已加载并创建 Agent"""
        if not self._tools_loaded:
            await self.refresh_metric_tools()
            self._tools_loaded = True

    async def refresh_metric_tools(self) -> None:
        """刷新指标工具列表并重建 Agent"""
        logger.info("Refreshing metric tools")
        self._metric_tools = await load_metric_tools()

        # 加载 skill tools
        skill_tools = load_skill_tools()

        all_tools = self._fixed_tools + self._metric_tools + skill_tools
        self._agent = create_react_agent(
            self._llm,
            tools=all_tools,
            prompt=_build_system_prompt(),
            checkpointer=self._checkpointer,
        )

        logger.info(
            "Agent rebuilt, total_tools=%d (fixed=%d, metrics=%d, skills=%d)",
            len(all_tools), len(self._fixed_tools), len(self._metric_tools), len(skill_tools),
        )

    async def run(
        self,
        message: str,
        conversation_history: list[dict],
        auto_execute: bool = True,
        thread_id: str = "",
    ) -> AsyncGenerator[StreamEvent, None]:
        """执行 Agent 查询

        使用 langgraph agent.astream() 流式获取输出，
        将 Agent 的工具调用和回复转换为 SSE 事件。

        Args:
            message: 用户消息
            conversation_history: 对话历史
            auto_execute: 是否自动执行 SQL
            thread_id: 会话线程ID（用于 langgraph 记忆）

        Yields:
            StreamEvent 对象
        """
        await self._ensure_tools_loaded()

        logger.info(
            "Agent run started, message=%s, auto_execute=%s, thread_id=%s",
            message[:100], auto_execute, thread_id,
        )

        # 1.发送 thinking 事件
        yield StreamEvent(
            type=StreamEventType.thinking,
            data={"message": "正在分析您的查询意图..."},
        )

        # 2.配置
        config = {"configurable": {"thread_id": thread_id or "default"}}

        # 3.调用 Agent 流式执行
        produced_sql = None
        produced_explanation = None
        result_sent = False

        try:
            async for event in self._agent.astream(
                {"messages": [{"role": "user", "content": message}]},
                config,
                stream_mode="updates",
            ):
                # 4.解析 langgraph 事件
                for node_name, node_output in event.items():
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
                                        display_name = f"指标查询"
                                    elif tc_name.startswith("skill_"):
                                        display_name = tc_name.replace("skill_", "技能: ")
                                    elif tc_name == "generate_sql":
                                        display_name = "SQL 生成"
                                    elif tc_name == "execute_sql":
                                        display_name = "执行查询"
                                    elif tc_name == "recommend_chart":
                                        display_name = "图表推荐"

                                    yield StreamEvent(
                                        type=StreamEventType.tool_call,
                                        data={
                                            "tool_name": tc_name,
                                            "display_name": display_name,
                                            "args": tc_args,
                                        },
                                    )
                                continue
                            # Agent 直接文本回复（无工具调用）
                            if msg.content:
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
