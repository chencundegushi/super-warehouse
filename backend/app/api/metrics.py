"""
指标管理 API 路由

提供指标的创建、查询、更新、删除和参考 SQL 生成接口。
通过 MetricEngine 服务管理指标生命周期，通过 SQLGenerator 生成参考 SQL。

路由前缀: /api/metrics
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.models.schemas import (
    MetricCreateInput,
    MetricUpdateInput,
    PaginatedResult,
    PaginationParams,
)
from app.services.metric_engine import (
    MetricNotFoundError,
    MetricValidationError,
    metric_engine,
)

logger = logging.getLogger(__name__)

# 创建路由器，设置前缀和标签
router = APIRouter(prefix="/api/metrics", tags=["指标管理"])


# ============================================================
# 请求/响应模型
# ============================================================


class MetricParameterResponse(BaseModel):
    """指标参数响应"""
    id: str = Field(..., description="参数ID")
    name: str = Field(..., description="参数名称")
    type: str = Field(..., description="参数类型")
    required: bool = Field(..., description="是否必填")
    default_value: Optional[str] = Field(
        None, alias="defaultValue", description="默认值"
    )
    enum_values: Optional[str] = Field(
        None, alias="enumValues", description="枚举可选值（JSON字符串）"
    )
    sort_order: int = Field(0, alias="sortOrder", description="排序序号")

    model_config = {"populate_by_name": True}


class MetricResponse(BaseModel):
    """指标响应"""
    id: str = Field(..., description="指标ID")
    name: str = Field(..., description="指标名称")
    description: str = Field(..., description="用途说明")
    sql_template: str = Field(..., alias="sqlTemplate", description="SQL模板")
    created_at: str = Field(..., alias="createdAt", description="创建时间")
    updated_at: str = Field(..., alias="updatedAt", description="更新时间")
    parameters: list[MetricParameterResponse] = Field(
        default_factory=list, description="参数列表"
    )

    model_config = {"populate_by_name": True}


class GenerateSQLRequest(BaseModel):
    """生成参考 SQL 请求"""
    name: str = Field(..., description="指标名称")
    description: str = Field(..., description="指标用途说明")


class GenerateSQLResponse(BaseModel):
    """生成参考 SQL 响应"""
    sql: str = Field(..., description="生成的参考SQL")


# ============================================================
# 辅助函数
# ============================================================


async def _build_metric_response(metric) -> MetricResponse:
    """将 ORM 指标对象转换为响应模型

    从数据库加载指标的关联参数并构建完整响应。

    Args:
        metric: 指标 ORM 对象

    Returns:
        指标响应模型
    """
    from sqlalchemy import select

    from app.models.database import MetricParameter as MetricParameterModel
    from app.models.database import async_session_factory

    # 1.加载关联参数
    async with async_session_factory() as session:
        result = await session.execute(
            select(MetricParameterModel)
            .where(MetricParameterModel.metric_id == metric.id)
            .order_by(MetricParameterModel.sort_order)
        )
        params = result.scalars().all()

    # 2.构建参数响应列表
    param_responses = [
        MetricParameterResponse(
            id=p.id,
            name=p.name,
            type=p.type,
            required=bool(p.required),
            defaultValue=p.default_value,
            enumValues=p.enum_values,
            sortOrder=p.sort_order,
        )
        for p in params
    ]

    return MetricResponse(
        id=metric.id,
        name=metric.name,
        description=metric.description,
        sqlTemplate=metric.sql_template,
        createdAt=metric.created_at,
        updatedAt=metric.updated_at,
        parameters=param_responses,
    )


# ============================================================
# generate-sql 接口（放在 {id} 路由之前，避免路径冲突）
# ============================================================


@router.post("/generate-sql", summary="生成参考SQL")
async def generate_reference_sql(
    request: GenerateSQLRequest,
) -> GenerateSQLResponse:
    """根据指标名称和用途自动生成参考 SQL

    使用 SQLGenerator 结合已加载的 DDL 信息，为指标生成参考 SQL 模板。
    用户可在此基础上进行手动修改后保存。

    Args:
        request: 包含指标名称和用途说明的请求

    Returns:
        生成的参考 SQL

    Raises:
        HTTPException: SQL 生成失败时返回 500
    """
    logger.info(
        "POST /api/metrics/generate-sql, name=%s, description=%s",
        request.name, request.description[:50],
    )

    try:
        from app.services.ddl_manager import DDLManager
        from app.services.sql_generator import SQLGenerator

        # 1.获取已加载的 DDL 上下文
        ddl_manager = DDLManager()
        ddl_list = ddl_manager.list_loaded_ddl()

        # 2.调用 SQL 生成器生成参考 SQL
        sql_generator = SQLGenerator()
        reference_sql = sql_generator.generate_reference_sql(
            metric_name=request.name,
            description=request.description,
            ddl_context=ddl_list,
        )

        logger.info(
            "Reference SQL generated, name=%s, sql_length=%d",
            request.name, len(reference_sql),
        )
        return GenerateSQLResponse(sql=reference_sql)

    except Exception as e:
        logger.error(
            "Failed to generate reference SQL, name=%s, error=%s",
            request.name, str(e),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate reference SQL: {str(e)}",
        )


# ============================================================
# 指标 CRUD 接口
# ============================================================


@router.post("", summary="创建指标", status_code=201)
async def create_metric(request: MetricCreateInput) -> MetricResponse:
    """创建新指标

    验证规则：
    - 名称不超过64字符且系统内唯一
    - 用途说明不超过512字符
    - 参数数量不超过20个

    创建成功后自动刷新 Agent 工具列表。

    Args:
        request: 指标创建输入

    Returns:
        创建的指标信息

    Raises:
        HTTPException: 验证失败时返回 400
    """
    logger.info("POST /api/metrics, name=%s", request.name)

    try:
        metric = await metric_engine.create_metric(request)
        response = await _build_metric_response(metric)
        logger.info("Metric created, id=%s, name=%s", metric.id, metric.name)

        # 刷新 Agent 工具列表
        from app.services.agent_orchestrator import agent_orchestrator
        await agent_orchestrator.refresh_tools()

        return response
    except MetricValidationError as e:
        logger.warning(
            "Metric creation validation failed, error=%s, field=%s",
            e.message, e.field,
        )
        raise HTTPException(status_code=400, detail=e.message)


@router.get("", summary="获取指标列表")
async def list_metrics(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(
        20, ge=1, alias="pageSize", description="每页条数"
    ),
) -> dict[str, Any]:
    """分页查询指标列表

    按创建时间降序展示所有指标。

    Args:
        page: 页码
        page_size: 每页条数

    Returns:
        分页结果，包含指标列表和总数
    """
    logger.info(
        "GET /api/metrics, page=%d, page_size=%d", page, page_size
    )

    params = PaginationParams(page=page, page_size=page_size)
    result = await metric_engine.list_metrics(params)

    # 将 ORM 对象转换为响应模型
    items = []
    for metric in result.items:
        response = await _build_metric_response(metric)
        items.append(response.model_dump(by_alias=True))

    logger.info("List metrics completed, total=%d", result.total)
    return {
        "items": items,
        "total": result.total,
        "page": result.page,
        "pageSize": result.page_size,
    }


@router.get("/{metric_id}", summary="获取指标详情")
async def get_metric(metric_id: str) -> MetricResponse:
    """获取指定指标的详细信息，包含参数定义

    Args:
        metric_id: 指标ID

    Returns:
        指标详情

    Raises:
        HTTPException: 指标不存在时返回 404
    """
    logger.info("GET /api/metrics/%s", metric_id)

    metric = await metric_engine.get_metric(metric_id)
    if metric is None:
        logger.warning("Metric not found, id=%s", metric_id)
        raise HTTPException(status_code=404, detail="Metric not found")

    response = await _build_metric_response(metric)
    return response


@router.put("/{metric_id}", summary="更新指标")
async def update_metric(
    metric_id: str, request: MetricUpdateInput
) -> MetricResponse:
    """更新指定指标

    仅更新请求中提供的字段，验证规则同创建。
    更新成功后自动刷新 Agent 工具列表。

    Args:
        metric_id: 指标ID
        request: 指标更新输入

    Returns:
        更新后的指标信息

    Raises:
        HTTPException: 指标不存在时返回 404，验证失败时返回 400
    """
    logger.info("PUT /api/metrics/%s", metric_id)

    try:
        metric = await metric_engine.update_metric(metric_id, request)
        response = await _build_metric_response(metric)
        logger.info("Metric updated, id=%s", metric_id)

        # 刷新 Agent 工具列表
        from app.services.agent_orchestrator import agent_orchestrator
        await agent_orchestrator.refresh_tools()

        return response
    except MetricNotFoundError:
        logger.warning("Metric not found for update, id=%s", metric_id)
        raise HTTPException(status_code=404, detail="Metric not found")
    except MetricValidationError as e:
        logger.warning(
            "Metric update validation failed, id=%s, error=%s, field=%s",
            metric_id, e.message, e.field,
        )
        raise HTTPException(status_code=400, detail=e.message)


@router.delete("/{metric_id}", summary="删除指标", status_code=204)
async def delete_metric(metric_id: str) -> None:
    """删除指定指标及其所有参数

    删除成功后自动刷新 Agent 工具列表。

    Args:
        metric_id: 指标ID

    Raises:
        HTTPException: 指标不存在时返回 404
    """
    logger.info("DELETE /api/metrics/%s", metric_id)

    try:
        await metric_engine.delete_metric(metric_id)
        logger.info("Metric deleted, id=%s", metric_id)

        # 刷新 Agent 工具列表
        from app.services.agent_orchestrator import agent_orchestrator
        await agent_orchestrator.refresh_tools()

    except MetricNotFoundError:
        logger.warning("Metric not found for deletion, id=%s", metric_id)
        raise HTTPException(status_code=404, detail="Metric not found")
