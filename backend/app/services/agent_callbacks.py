"""
Agent SSE 回调处理器

将 LangChain Agent 的执行事件转换为前端期望的 SSE StreamEvent。
通过 AsyncCallbackHandler 拦截 Agent 的思考、工具调用和输出，
实时推送到异步队列供 SSE 流式响应消费。
"""

import asyncio
import json
import logging
from typing import Any, Optional

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from app.models.schemas import StreamEvent, StreamEventType

logger = logging.getLogger(__name__)


class SSECallbackHandler(AsyncCallbackHandler):
    """SSE 流式回调处理器

    拦截 LangChain Agent 的各阶段事件，转换为 StreamEvent 并放入队列。
    前端通过消费队列中的事件实现 SSE 流式输出。

    Attributes:
        queue: 异步队列，存放 StreamEvent
        _current_tool: 当前正在调用的工具名称
    """

    def __init__(self) -> None:
        """初始化回调处理器"""
        super().__init__()
        self.queue: asyncio.Queue[Optional[StreamEvent]] = asyncio.Queue()
        self._current_tool: str = ""
        self._thinking_sent: bool = False

    async def _emit(self, event: StreamEvent) -> None:
        """将事件放入队列

        Args:
            event: 流事件对象
        """
        await self.queue.put(event)

    async def on_llm_start(self, serialized: dict, prompts: list[str], **kwargs) -> None:
        """LLM 开始调用时触发

        发送 thinking 事件通知前端 Agent 正在思考。
        """
        if not self._thinking_sent:
            await self._emit(StreamEvent(
                type=StreamEventType.thinking,
                data={"message": "正在分析您的查询意图..."},
            ))
            self._thinking_sent = True

    async def on_chat_model_start(self, serialized: dict, messages: list, **kwargs) -> None:
        """Chat Model 开始调用时触发"""
        if not self._thinking_sent:
            await self._emit(StreamEvent(
                type=StreamEventType.thinking,
                data={"message": "正在分析您的查询意图..."},
            ))
            self._thinking_sent = True

    async def on_tool_start(self, serialized: dict, input_str: str, **kwargs) -> None:
        """工具开始调用时触发

        根据工具类型发送不同的 SSE 事件。
        """
        tool_name = serialized.get("name", kwargs.get("name", ""))
        self._current_tool = tool_name
        logger.info("Agent calling tool: %s", tool_name)

        if tool_name == "execute_sql":
            await self._emit(StreamEvent(
                type=StreamEventType.executing,
                data={"message": "正在执行查询..."},
            ))

    async def on_tool_end(self, output: str, **kwargs) -> None:
        """工具调用完成时触发

        根据工具类型和返回结果发送对应的 SSE 事件。
        """
        tool_name = self._current_tool
        logger.info("Tool completed: %s, output_length=%d", tool_name, len(output) if output else 0)

        try:
            result = json.loads(output) if output else {}
        except (json.JSONDecodeError, TypeError):
            result = {"raw": output}

        # 1.generate_sql 或 metric tool 返回 SQL
        if tool_name == "generate_sql" or tool_name.startswith("metric_"):
            if result.get("clarification_needed"):
                await self._emit(StreamEvent(
                    type=StreamEventType.clarification,
                    data={"message": result.get("message", "请补充更多信息")},
                ))
            elif result.get("sql"):
                await self._emit(StreamEvent(
                    type=StreamEventType.sql_preview,
                    data={
                        "sql": result["sql"],
                        "explanation": result.get("explanation", ""),
                        "source": result.get("source", "sql_generator"),
                        "metric_name": result.get("metric_name"),
                    },
                ))
            elif result.get("error"):
                await self._emit(StreamEvent(
                    type=StreamEventType.error,
                    data={"message": result["error"], "error_type": "tool_error"},
                ))

        # 2.execute_sql 返回查询结果
        elif tool_name == "execute_sql":
            if result.get("error"):
                await self._emit(StreamEvent(
                    type=StreamEventType.error,
                    data={"message": result["error"], "error_type": "execution_error"},
                ))
            elif result.get("columns"):
                await self._emit(StreamEvent(
                    type=StreamEventType.result,
                    data={
                        "columns": result["columns"],
                        "rows": result.get("rows", []),
                        "row_count": result.get("row_count", 0),
                        "execution_time": result.get("execution_time", 0),
                        "truncated": result.get("truncated", False),
                    },
                ))

        # 3.recommend_chart 返回图表推荐
        elif tool_name == "recommend_chart":
            if result.get("recommended"):
                await self._emit(StreamEvent(
                    type=StreamEventType.chart_recommendation,
                    data={
                        "recommended": result["recommended"],
                        "reason": result.get("reason", ""),
                        "alternatives": result.get("alternatives", []),
                    },
                ))

        self._current_tool = ""

    async def on_tool_error(self, error: BaseException, **kwargs) -> None:
        """工具调用出错时触发"""
        logger.error("Tool error: %s, tool=%s", str(error), self._current_tool)
        await self._emit(StreamEvent(
            type=StreamEventType.error,
            data={"message": f"工具执行错误：{str(error)}", "error_type": "tool_error"},
        ))
        self._current_tool = ""

    async def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        """LLM 调用完成时触发"""
        pass

    async def on_agent_finish(self, finish, **kwargs) -> None:
        """Agent 完成时触发

        如果 Agent 直接输出文本（非工具调用），作为 clarification 发送。
        """
        output = finish.return_values.get("output", "") if hasattr(finish, "return_values") else ""
        if output and not self._current_tool:
            # Agent 直接回复用户（追问或解释）
            await self._emit(StreamEvent(
                type=StreamEventType.clarification,
                data={"message": output},
            ))

    async def on_agent_action(self, action, **kwargs) -> None:
        """Agent 决定调用工具时触发"""
        pass

    async def mark_done(self) -> None:
        """标记流结束，放入 None 作为终止信号"""
        await self.queue.put(None)
