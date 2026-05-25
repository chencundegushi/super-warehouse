"""
查询执行 API 路由

提供 SQL 查询执行和查询取消接口。
通过 QueryExecutor 服务连接 Doris 执行 SQL，支持超时控制和查询取消。

路由前缀: /api/query
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models.schemas import ExecuteOptions, QueryResult
from app.services.query_executor import QueryExecutor

logger = logging.getLogger(__name__)

# 创建路由器，设置前缀和标签
router = APIRouter(prefix="/api/query", tags=["查询执行"])

# QueryExecutor 单例实例
_query_executor: Optional[QueryExecutor] = None


def get_query_executor() -> QueryExecutor:
    """获取查询执行器单例实例

    Returns:
        QueryExecutor 实例
    """
    global _query_executor
    if _query_executor is None:
        _query_executor = QueryExecutor()
    return _query_executor



# ============================================================
# 请求模型
# ============================================================

class ExecuteRequest(BaseModel):
    """SQL 执行请求模型"""
    sql: str = Field(..., description="要执行的SQL语句")
    timeout: int = Field(30000, description="超时时间(ms)，默认30000")
    max_rows: int = Field(
        1000, alias="maxRows", description="最大返回行数，默认1000"
    )
    query_id: Optional[str] = Field(
        None, alias="queryId", description="查询标识，用于取消查询"
    )

    model_config = {"populate_by_name": True}


class CancelRequest(BaseModel):
    """查询取消请求模型"""
    query_id: str = Field(
        ..., alias="queryId", description="要取消的查询标识"
    )

    model_config = {"populate_by_name": True}



# ============================================================
# API 端点
# ============================================================

@router.post("/execute", response_model=QueryResult)
async def execute_sql(request: ExecuteRequest):
    """执行 SQL 接口

    将 SQL 提交到 Doris 执行，支持超时控制和结果行数限制。
    超过 maxRows 时截断结果并设置 truncated=true。

    Args:
        request: SQL 执行请求，包含 sql、timeout、maxRows、queryId

    Returns:
        查询结果，包含列信息、数据行、执行耗时等

    Raises:
        HTTPException 408: 查询超时
        HTTPException 503: Doris 连接失败
        HTTPException 500: 查询执行错误
    """
    logger.info(
        "POST /api/query/execute, sql=%s, timeout=%d, max_rows=%d, query_id=%s",
        request.sql[:200],
        request.timeout,
        request.max_rows,
        request.query_id,
    )

    # 1.构建执行选项
    options = ExecuteOptions(
        timeout=request.timeout,
        max_rows=request.max_rows,
        query_id=request.query_id,
    )

    try:
        executor = get_query_executor()
        result = await executor.execute_sql(request.sql, options)
        logger.info(
            "Query executed successfully, rows=%d, truncated=%s, time=%.2fms",
            result.row_count,
            result.truncated,
            result.execution_time,
        )
        return result

    except TimeoutError as e:
        logger.error("Query timed out, error=%s", str(e))
        raise HTTPException(status_code=408, detail=str(e))

    except ConnectionError as e:
        logger.error("Doris connection failed, error=%s", str(e))
        raise HTTPException(status_code=503, detail=str(e))

    except RuntimeError as e:
        logger.error("Query execution failed, error=%s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel")
async def cancel_query(request: CancelRequest):
    """取消查询接口

    取消正在执行的查询，通过关闭对应的数据库连接来终止查询。

    Args:
        request: 取消请求，包含 queryId

    Returns:
        操作结果消息

    Raises:
        HTTPException 404: 查询ID不存在或已完成
    """
    logger.info("POST /api/query/cancel, query_id=%s", request.query_id)

    try:
        executor = get_query_executor()
        await executor.cancel_query(request.query_id)
        logger.info(
            "Query cancelled successfully, query_id=%s", request.query_id
        )
        return {"message": f"Query '{request.query_id}' cancelled successfully"}

    except ValueError as e:
        logger.warning("Cancel query failed, error=%s", str(e))
        raise HTTPException(status_code=404, detail=str(e))
