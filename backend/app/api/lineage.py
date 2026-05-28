"""
表血缘关系 API 路由

提供表层级关系分析、缓存查询和原始 Job 数据查询接口。
通过 LineageService 查询 Doris ETL Job 并调用 LLM 分析血缘关系。

路由前缀: /api/lineage
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.lineage_service import LineageService

logger = logging.getLogger(__name__)

# 创建路由器，设置前缀和标签
router = APIRouter(prefix="/api/lineage", tags=["表血缘关系"])

# 服务实例
_lineage_service: Optional[LineageService] = None


def get_lineage_service() -> LineageService:
    """获取 LineageService 单例实例

    Returns:
        LineageService 实例
    """
    global _lineage_service
    if _lineage_service is None:
        _lineage_service = LineageService()
    return _lineage_service


class AnalyzeRequest(BaseModel):
    """血缘分析请求模型"""
    force_refresh: bool = Field(
        False, alias="forceRefresh",
        description="是否强制刷新（忽略缓存）"
    )

    model_config = {"populate_by_name": True}


@router.post("/analyze")
async def analyze_lineage(request: Optional[AnalyzeRequest] = None):
    """分析表血缘关系

    查询 Doris ETL Job 列表，调用 LLM 分析表之间的层级关系和调度周期。
    分析结果缓存到本地 JSON 文件。

    Args:
        request: 分析请求，包含是否强制刷新选项

    Returns:
        表血缘关系分析结果，包含层级、边和表信息

    Raises:
        HTTPException: Doris 连接失败或 LLM 分析失败时返回 500
    """
    force_refresh = request.force_refresh if request else False
    logger.info("POST /api/lineage/analyze, force_refresh=%s", force_refresh)

    try:
        service = get_lineage_service()
        result = await service.analyze_lineage(force_refresh=force_refresh)
        logger.info(
            "Lineage analysis completed, layers=%d, edges=%d, tables=%d",
            len(result.get("layers", [])),
            len(result.get("edges", [])),
            len(result.get("tables", [])),
        )
        return result
    except RuntimeError as e:
        logger.error("Lineage analysis failed, error=%s", str(e))
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        logger.error("Lineage analysis parse error, error=%s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cache")
async def get_cached_lineage():
    """获取缓存的血缘关系数据

    直接从本地缓存文件读取已分析的血缘关系数据，不触发新的分析。

    Returns:
        缓存的血缘关系数据，无缓存时返回空结构

    """
    logger.info("GET /api/lineage/cache")
    service = get_lineage_service()
    cached = service._load_cache()
    if cached:
        logger.info("Returning cached lineage data")
        return cached
    logger.info("No cached lineage data found, returning empty structure")
    return {"layers": [], "edges": [], "tables": []}


@router.get("/jobs")
async def get_jobs():
    """获取原始 Job 列表

    直接查询 Doris 的 ETL Job 列表，返回原始数据。

    Returns:
        Job 列表

    Raises:
        HTTPException: Doris 连接失败时返回 500
    """
    logger.info("GET /api/lineage/jobs")
    try:
        service = get_lineage_service()
        jobs = await service.get_jobs_raw()
        logger.info("Jobs query completed, count=%d", len(jobs))
        return {"jobs": jobs, "count": len(jobs)}
    except RuntimeError as e:
        logger.error("Jobs query failed, error=%s", str(e))
        raise HTTPException(status_code=500, detail=str(e))
