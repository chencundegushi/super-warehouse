"""
系统设置 API

提供系统配置查询和快捷问题标签管理接口。
"""

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# 快捷标签持久化文件路径
SUGGESTIONS_FILE = Path("./cache/settings/suggestions.json")

# 默认快捷标签
DEFAULT_SUGGESTIONS = [
    {"icon": "DollarOutlined", "label": "充值收入分析", "text": "查询本月平台充值总收入，按天汇总趋势"},
    {"icon": "RiseOutlined", "label": "新增用户趋势", "text": "查询最近7天每天的新增注册用户数"},
    {"icon": "BarChartOutlined", "label": "游戏消耗排行", "text": "查询本月游戏消耗金额TOP10"},
    {"icon": "TeamOutlined", "label": "活跃用户统计", "text": "查询最近30天的日活跃用户数趋势"},
    {"icon": "ThunderboltOutlined", "label": "送礼消耗概览", "text": "查询本月送礼消耗总额及同比变化"},
    {"icon": "SearchOutlined", "label": "短剧消费分析", "text": "查询本月短剧消费金额及观看人数"},
]


class SuggestionItem(BaseModel):
    """快捷标签数据模型"""

    icon: str
    label: str
    text: str


class SuggestionsUpdate(BaseModel):
    """快捷标签更新请求体"""

    suggestions: list[SuggestionItem]


def _load_suggestions() -> list[dict[str, str]]:
    """从文件加载快捷标签配置

    Returns:
        快捷标签列表
    """
    if SUGGESTIONS_FILE.exists():
        try:
            data = json.loads(SUGGESTIONS_FILE.read_text(encoding="utf-8"))
            logger.info("Loaded suggestions from file, count=%d", len(data))
            return data
        except (json.JSONDecodeError, IOError) as e:
            logger.warn("Failed to load suggestions file, using defaults, error=%s", e)
    return DEFAULT_SUGGESTIONS.copy()


def _save_suggestions(suggestions: list[dict[str, str]]) -> None:
    """持久化快捷标签配置到文件

    Args:
        suggestions: 快捷标签列表
    """
    SUGGESTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUGGESTIONS_FILE.write_text(
        json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Saved suggestions to file, count=%d", len(suggestions))


@router.get("/system")
async def get_system_settings() -> dict[str, Any]:
    """获取系统配置信息（脱敏）

    Returns:
        系统配置字典，不包含敏感信息
    """
    logger.info("Getting system settings")
    return {
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "debug": settings.debug,
        "llm_model": settings.llm_model,
        "llm_base_url": settings.llm_base_url,
        "llm_temperature": settings.llm_temperature,
        "llm_max_tokens": settings.llm_max_tokens,
        "doris_host": settings.doris_host,
        "doris_port": settings.doris_port,
        "doris_database": settings.doris_database,
        "query_timeout_seconds": settings.query_timeout_seconds,
        "query_max_rows": settings.query_max_rows,
        "query_max_retries": settings.query_max_retries,
        "conversation_max_turns": settings.conversation_max_turns,
        "metric_match_threshold": settings.metric_match_threshold,
    }


@router.get("/suggestions")
async def get_suggestions() -> list[dict[str, str]]:
    """获取快捷问题标签列表

    Returns:
        快捷标签列表
    """
    logger.info("Getting quick suggestions")
    return _load_suggestions()


@router.put("/suggestions")
async def update_suggestions(body: SuggestionsUpdate) -> dict[str, Any]:
    """更新快捷问题标签列表

    Args:
        body: 包含新标签列表的请求体

    Returns:
        更新结果
    """
    logger.info("Updating quick suggestions, count=%d", len(body.suggestions))
    suggestions = [item.model_dump() for item in body.suggestions]
    _save_suggestions(suggestions)
    return {"success": True, "count": len(suggestions)}
