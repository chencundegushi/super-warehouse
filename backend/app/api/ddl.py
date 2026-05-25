"""
DDL 管理 API 路由

提供 DDL 信息的加载、刷新、列表查询和缓存清除接口。
通过 DDLManager 服务与 Doris 数据库交互，管理表结构缓存。

路由前缀: /api/ddl
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.models.schemas import DDLFilterParams, DDLInfo, DDLLoadParams
from app.services.ddl_manager import DDLManager, DorisConnectionError

logger = logging.getLogger(__name__)

# 创建路由器，设置前缀和标签
router = APIRouter(prefix="/api/ddl", tags=["DDL管理"])

# DDL 管理器实例
_ddl_manager: Optional[DDLManager] = None


def get_ddl_manager() -> DDLManager:
    """获取 DDL 管理器单例实例

    Returns:
        DDLManager 实例
    """
    global _ddl_manager
    if _ddl_manager is None:
        _ddl_manager = DDLManager()
    return _ddl_manager


@router.post("/load", response_model=list[DDLInfo])
async def load_ddl(params: DDLLoadParams):
    """加载 DDL 接口

    连接 Doris 数据库，获取指定数据库或表的 DDL 信息并缓存到本地。
    若未指定表名列表，则加载整个数据库的所有表。

    Args:
        params: DDL 加载参数，包含数据库名和可选的表名列表

    Returns:
        成功加载的 DDL 信息列表

    Raises:
        HTTPException: Doris 连接失败时返回 503
    """
    logger.info(
        "POST /api/ddl/load, database=%s, tables=%s",
        params.database, params.tables,
    )

    try:
        manager = get_ddl_manager()
        results = manager.load_ddl(params)
        logger.info(
            "DDL load success, database=%s, loaded_count=%d",
            params.database, len(results),
        )
        return results
    except DorisConnectionError as e:
        logger.error("DDL load failed, error=%s", str(e))
        raise HTTPException(
            status_code=503,
            detail=f"Doris connection failed: {str(e)}",
        )


class RefreshRequest(BaseModel):
    """DDL 刷新请求模型"""
    table_ids: Optional[list[str]] = Field(
        None, alias="tableIds", description="要刷新的表标识列表"
    )

    model_config = {"populate_by_name": True}


@router.post("/refresh", response_model=list[DDLInfo])
async def refresh_ddl(request: Optional[RefreshRequest] = None):
    """刷新 DDL 接口

    重新从 Doris 获取已加载表的最新 DDL 并更新本地缓存。
    若指定 tableIds，则只刷新指定的表；否则刷新所有已缓存的表。

    Args:
        request: 刷新请求，包含可选的 tableIds 列表

    Returns:
        成功刷新的 DDL 信息列表

    Raises:
        HTTPException: Doris 连接失败时返回 503
    """
    table_ids = request.table_ids if request else None
    logger.info("POST /api/ddl/refresh, table_ids=%s", table_ids)

    try:
        manager = get_ddl_manager()
        results = manager.refresh_ddl(table_ids)
        logger.info("DDL refresh success, refreshed_count=%d", len(results))
        return results
    except DorisConnectionError as e:
        logger.error("DDL refresh failed, error=%s", str(e))
        raise HTTPException(
            status_code=503,
            detail=f"Doris connection failed: {str(e)}",
        )


@router.get("/list", response_model=list[DDLInfo])
async def list_ddl(
    database: Optional[str] = Query(None, description="数据库名过滤"),
    table_name: Optional[str] = Query(
        None, alias="tableName", description="表名过滤（模糊匹配）"
    ),
):
    """列表查询接口

    从本地文件缓存中读取已加载的 DDL 信息，支持按数据库名和表名过滤。

    Args:
        database: 数据库名过滤条件，可选
        table_name: 表名过滤条件（模糊匹配），可选

    Returns:
        匹配过滤条件的 DDL 信息列表
    """
    logger.info(
        "GET /api/ddl/list, database=%s, table_name=%s",
        database, table_name,
    )

    # 1.构建过滤参数
    params = None
    if database or table_name:
        params = DDLFilterParams(database=database, table_name=table_name)

    manager = get_ddl_manager()
    results = manager.list_loaded_ddl(params)
    logger.info("DDL list success, count=%d", len(results))
    return results


@router.delete("/cache")
async def clear_cache(
    database: Optional[str] = Query(None, description="数据库名"),
    table: Optional[str] = Query(None, description="表名"),
):
    """清除缓存接口

    根据参数清除指定范围的 DDL 缓存文件：
    - 指定 database 和 table：删除单个表的缓存
    - 仅指定 database：删除该数据库所有表的缓存
    - 都不指定：删除所有缓存

    Args:
        database: 数据库名，可选
        table: 表名，可选

    Returns:
        操作结果消息
    """
    logger.info(
        "DELETE /api/ddl/cache, database=%s, table=%s",
        database, table,
    )

    manager = get_ddl_manager()
    manager.clear_cache(database=database, table=table)
    logger.info(
        "DDL cache cleared, database=%s, table=%s", database, table
    )
    return {"message": "Cache cleared successfully"}
