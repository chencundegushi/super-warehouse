"""
技能管理 API 路由

提供技能的导入、导出、列表查询、详情获取、更新、删除和执行接口。
通过 SkillManager 服务管理技能生命周期。

路由前缀: /api/skills
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models.schemas import SkillExecutionResult, SkillFile
from app.services.skill_manager import (
    SkillNotFoundError,
    SkillValidationError,
    skill_manager,
)

logger = logging.getLogger(__name__)

# 创建路由器，设置前缀和标签
router = APIRouter(prefix="/api/skills", tags=["技能管理"])


# ============================================================
# 请求/响应模型
# ============================================================


class SkillResponse(BaseModel):
    """技能响应模型"""
    id: str = Field(..., description="技能ID")
    name: str = Field(..., description="技能名称")
    description: Optional[str] = Field(None, description="技能描述")
    content: str = Field(..., description="技能文件内容")
    file_size: int = Field(..., alias="fileSize", description="文件大小(字节)")
    created_at: str = Field(..., alias="createdAt", description="创建时间")
    updated_at: str = Field(..., alias="updatedAt", description="更新时间")

    model_config = {"populate_by_name": True}


class SkillListItem(BaseModel):
    """技能列表项（不含完整内容）"""
    id: str = Field(..., description="技能ID")
    name: str = Field(..., description="技能名称")
    description: Optional[str] = Field(None, description="技能描述")
    file_size: int = Field(..., alias="fileSize", description="文件大小(字节)")
    created_at: str = Field(..., alias="createdAt", description="创建时间")
    updated_at: str = Field(..., alias="updatedAt", description="更新时间")

    model_config = {"populate_by_name": True}


class SkillUpdateRequest(BaseModel):
    """技能更新请求"""
    name: Optional[str] = Field(None, description="技能名称")
    description: Optional[str] = Field(None, description="技能描述")
    content: Optional[str] = Field(None, description="技能文件内容")


class SkillExecuteRequest(BaseModel):
    """技能执行请求"""
    params: dict[str, Any] = Field(
        default_factory=dict, description="执行参数"
    )


# ============================================================
# 辅助函数
# ============================================================


def _build_skill_response(skill) -> SkillResponse:
    """将 ORM 技能对象转换为响应模型

    Args:
        skill: 技能 ORM 对象

    Returns:
        技能响应模型
    """
    return SkillResponse(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        content=skill.content,
        fileSize=skill.file_size,
        createdAt=skill.created_at,
        updatedAt=skill.updated_at,
    )


def _build_skill_list_item(skill) -> SkillListItem:
    """将 ORM 技能对象转换为列表项模型（不含完整内容）

    Args:
        skill: 技能 ORM 对象

    Returns:
        技能列表项模型
    """
    return SkillListItem(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        fileSize=skill.file_size,
        createdAt=skill.created_at,
        updatedAt=skill.updated_at,
    )


# ============================================================
# 导入接口（放在 {id} 路由之前，避免路径冲突）
# ============================================================


@router.post("/import", summary="导入技能", status_code=201)
async def import_skill(request: SkillFile) -> SkillResponse:
    """导入技能文件

    验证规则：
    - 文件大小不超过 1MB
    - 内容符合 Claude Code skill 格式规范

    Args:
        request: 技能文件对象

    Returns:
        导入的技能信息

    Raises:
        HTTPException: 验证失败时返回 400
    """
    logger.info(
        "POST /api/skills/import, name=%s, format=%s",
        request.name, request.format,
    )

    try:
        skill = await skill_manager.import_skill(request)
        response = _build_skill_response(skill)
        logger.info("Skill imported via API, id=%s, name=%s", skill.id, skill.name)
        return response
    except SkillValidationError as e:
        logger.warning(
            "Skill import validation failed, error=%s, field=%s",
            e.message, e.field,
        )
        raise HTTPException(status_code=400, detail=e.message)


# ============================================================
# 技能 CRUD 接口
# ============================================================


@router.get("", summary="获取技能列表")
async def list_skills() -> list[SkillListItem]:
    """查询所有已导入的技能列表

    按创建时间降序展示所有技能，不含完整文件内容。

    Returns:
        技能列表
    """
    logger.info("GET /api/skills")

    skills = await skill_manager.list_skills()
    result = [_build_skill_list_item(s) for s in skills]

    logger.info("List skills completed, total=%d", len(result))
    return result


@router.get("/{skill_id}", summary="获取技能详情")
async def get_skill(skill_id: str) -> SkillResponse:
    """获取指定技能的详细信息，包含完整文件内容

    Args:
        skill_id: 技能ID

    Returns:
        技能详情

    Raises:
        HTTPException: 技能不存在时返回 404
    """
    logger.info("GET /api/skills/%s", skill_id)

    skill = await skill_manager.get_skill(skill_id)
    if skill is None:
        logger.warning("Skill not found, id=%s", skill_id)
        raise HTTPException(status_code=404, detail="Skill not found")

    response = _build_skill_response(skill)
    return response


@router.put("/{skill_id}", summary="更新技能")
async def update_skill(
    skill_id: str, request: SkillUpdateRequest
) -> SkillResponse:
    """更新指定技能

    仅更新请求中提供的非空字段。更新 content 时会重新验证文件大小和格式。

    Args:
        skill_id: 技能ID
        request: 技能更新请求

    Returns:
        更新后的技能信息

    Raises:
        HTTPException: 技能不存在时返回 404，验证失败时返回 400
    """
    logger.info("PUT /api/skills/%s", skill_id)

    # 1.构建更新字典，仅包含非空字段
    updates = {}
    if request.name is not None:
        updates["name"] = request.name
    if request.description is not None:
        updates["description"] = request.description
    if request.content is not None:
        updates["content"] = request.content

    if not updates:
        logger.warning("No fields to update for skill, id=%s", skill_id)
        raise HTTPException(
            status_code=400, detail="No fields provided for update"
        )

    try:
        skill = await skill_manager.update_skill(skill_id, updates)
        response = _build_skill_response(skill)
        logger.info("Skill updated via API, id=%s", skill_id)
        return response
    except SkillNotFoundError:
        logger.warning("Skill not found for update, id=%s", skill_id)
        raise HTTPException(status_code=404, detail="Skill not found")
    except SkillValidationError as e:
        logger.warning(
            "Skill update validation failed, id=%s, error=%s, field=%s",
            skill_id, e.message, e.field,
        )
        raise HTTPException(status_code=400, detail=e.message)


@router.delete("/{skill_id}", summary="删除技能", status_code=204)
async def delete_skill(skill_id: str) -> None:
    """删除指定技能及其所有参数

    Args:
        skill_id: 技能ID

    Raises:
        HTTPException: 技能不存在时返回 404
    """
    logger.info("DELETE /api/skills/%s", skill_id)

    try:
        await skill_manager.delete_skill(skill_id)
        logger.info("Skill deleted via API, id=%s", skill_id)
    except SkillNotFoundError:
        logger.warning("Skill not found for deletion, id=%s", skill_id)
        raise HTTPException(status_code=404, detail="Skill not found")


@router.get("/{skill_id}/export", summary="导出技能")
async def export_skill(skill_id: str) -> SkillFile:
    """导出指定技能为 SkillFile 格式

    Args:
        skill_id: 技能ID

    Returns:
        技能文件对象

    Raises:
        HTTPException: 技能不存在时返回 404
    """
    logger.info("GET /api/skills/%s/export", skill_id)

    try:
        skill_file = await skill_manager.export_skill(skill_id)
        logger.info("Skill exported via API, id=%s", skill_id)
        return skill_file
    except SkillNotFoundError:
        logger.warning("Skill not found for export, id=%s", skill_id)
        raise HTTPException(status_code=404, detail="Skill not found")


@router.post("/{skill_id}/execute", summary="执行技能")
async def execute_skill(
    skill_id: str, request: SkillExecuteRequest
) -> SkillExecutionResult:
    """执行指定技能

    执行流程：
    1. 获取技能信息
    2. 验证参数
    3. 如果包含 Python 脚本，在沙箱中执行
    4. 否则将技能内容和参数注入 Agent 上下文

    Args:
        skill_id: 技能ID
        request: 执行请求，包含参数

    Returns:
        技能执行结果

    Raises:
        HTTPException: 技能不存在时返回 404，参数校验失败时返回 400
    """
    logger.info(
        "POST /api/skills/%s/execute, param_count=%d",
        skill_id, len(request.params),
    )

    try:
        result = await skill_manager.execute_skill(skill_id, request.params)
        logger.info(
            "Skill executed via API, id=%s, success=%s, time=%.2fms",
            skill_id, result.success, result.execution_time,
        )
        return result
    except SkillNotFoundError:
        logger.warning("Skill not found for execution, id=%s", skill_id)
        raise HTTPException(status_code=404, detail="Skill not found")
    except SkillValidationError as e:
        logger.warning(
            "Skill execution validation failed, id=%s, error=%s, field=%s",
            skill_id, e.message, e.field,
        )
        raise HTTPException(status_code=400, detail=e.message)
