"""
文件型技能管理 API

管理 backend/skills/ 目录下的文件型技能（SKILL.md + 可选脚本）。
支持目录上传导入、列表查询、详情查看、删除。

路由前缀: /api/skill-files
"""

import logging
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skill-files", tags=["文件型技能"])

# 技能存储目录
SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"


# ============================================================
# 响应模型
# ============================================================


class SkillFileInfo(BaseModel):
    """文件型技能信息"""
    name: str = Field(..., description="技能目录名")
    display_name: str = Field(..., alias="displayName", description="技能显示名称")
    description: str = Field("", description="技能描述")
    has_script: bool = Field(False, alias="hasScript", description="是否包含脚本")
    files: list[str] = Field(default_factory=list, description="包含的文件列表")

    model_config = {"populate_by_name": True}


class SkillFileDetail(BaseModel):
    """文件型技能详情"""
    name: str = Field(..., description="技能目录名")
    display_name: str = Field(..., alias="displayName", description="技能显示名称")
    description: str = Field("", description="技能描述")
    skill_md_content: str = Field("", alias="skillMdContent", description="SKILL.md 完整内容")
    files: list[dict] = Field(default_factory=list, description="文件列表（含内容）")
    has_script: bool = Field(False, alias="hasScript", description="是否包含脚本")

    model_config = {"populate_by_name": True}


# ============================================================
# 辅助函数
# ============================================================


def _parse_skill_meta(skill_dir: Path) -> dict:
    """解析技能目录的元数据"""
    skill_md = skill_dir / "SKILL.md"
    meta = {"name": skill_dir.name, "display_name": skill_dir.name, "description": ""}

    if skill_md.exists():
        content = skill_md.read_text(encoding="utf-8")
        if content.startswith("---"):
            end = content.find("---", 3)
            if end > 0:
                for line in content[3:end].strip().split("\n"):
                    if ":" in line:
                        key, val = line.split(":", 1)
                        key = key.strip().lower()
                        val = val.strip()
                        if key == "name":
                            meta["display_name"] = val
                        elif key == "description":
                            meta["description"] = val

    return meta


def _has_script(skill_dir: Path) -> bool:
    """检查技能目录是否包含 Python 脚本"""
    return any(skill_dir.glob("*.py"))


# ============================================================
# API 端点
# ============================================================


@router.get("", summary="获取文件型技能列表")
async def list_skill_files() -> list[SkillFileInfo]:
    """列出 backend/skills/ 下所有技能目录"""
    logger.info("GET /api/skill-files")

    if not SKILLS_DIR.exists():
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        return []

    skills = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        if not (skill_dir / "SKILL.md").exists():
            continue

        meta = _parse_skill_meta(skill_dir)
        files = [f.name for f in skill_dir.iterdir() if f.is_file()]

        skills.append(SkillFileInfo(
            name=skill_dir.name,
            displayName=meta["display_name"],
            description=meta["description"],
            hasScript=_has_script(skill_dir),
            files=files,
        ))

    logger.info("Listed %d file-based skills", len(skills))
    return skills


@router.get("/{skill_name}", summary="获取技能详情")
async def get_skill_file_detail(skill_name: str) -> SkillFileDetail:
    """获取指定技能的详细信息，包含 SKILL.md 完整内容"""
    logger.info("GET /api/skill-files/%s", skill_name)

    skill_dir = SKILLS_DIR / skill_name
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="技能不存在")

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise HTTPException(status_code=404, detail="技能缺少 SKILL.md")

    meta = _parse_skill_meta(skill_dir)
    skill_md_content = skill_md.read_text(encoding="utf-8")

    # 读取所有文件信息
    files = []
    for f in sorted(skill_dir.iterdir()):
        if f.is_file():
            file_info = {"name": f.name, "size": f.stat().st_size}
            # 文本文件读取内容（限制大小）
            if f.suffix in (".md", ".py", ".txt", ".yaml", ".yml", ".json"):
                try:
                    content = f.read_text(encoding="utf-8")
                    if len(content) > 50000:
                        content = content[:50000] + "\n... (内容过长，已截断)"
                    file_info["content"] = content
                except UnicodeDecodeError:
                    file_info["content"] = "(二进制文件)"
            files.append(file_info)

    return SkillFileDetail(
        name=skill_dir.name,
        displayName=meta["display_name"],
        description=meta["description"],
        skillMdContent=skill_md_content,
        files=files,
        hasScript=_has_script(skill_dir),
    )


@router.post("/import", summary="导入技能目录", status_code=201)
async def import_skill_directory(files: list[UploadFile] = File(...)) -> SkillFileInfo:
    """通过目录上传导入技能

    前端使用 webkitdirectory 选择目录，将目录中所有文件上传。
    文件的 filename 包含相对路径（如 "business-analysis/SKILL.md"）。

    Args:
        files: 上传的文件列表

    Returns:
        导入的技能信息
    """
    logger.info("POST /api/skill-files/import, file_count=%d", len(files))

    if not files:
        raise HTTPException(status_code=400, detail="没有上传文件")

    # 1.从第一个文件的路径提取目录名
    first_filename = files[0].filename or ""
    # webkitdirectory 上传的文件名格式: "dirname/filename" 或 "dirname/subdir/filename"
    parts = first_filename.replace("\\", "/").split("/")
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="无法识别目录结构，请选择包含 SKILL.md 的目录")

    skill_dir_name = parts[0]

    # 2.检查是否包含 SKILL.md
    has_skill_md = any(
        (f.filename or "").replace("\\", "/").endswith("SKILL.md")
        for f in files
    )
    if not has_skill_md:
        raise HTTPException(status_code=400, detail="目录中缺少 SKILL.md 文件")

    # 3.创建目标目录
    target_dir = SKILLS_DIR / skill_dir_name
    if target_dir.exists():
        # 已存在则覆盖
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    # 4.保存所有文件
    saved_files = []
    for upload_file in files:
        filename = (upload_file.filename or "").replace("\\", "/")
        # 去掉顶层目录名，得到相对路径
        rel_parts = filename.split("/")[1:]  # 去掉第一层目录名
        if not rel_parts:
            continue

        rel_path = "/".join(rel_parts)
        target_path = target_dir / rel_path

        # 创建子目录
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入文件
        content = await upload_file.read()
        target_path.write_bytes(content)
        saved_files.append(rel_path)
        logger.info("Saved skill file: %s/%s", skill_dir_name, rel_path)

    # 5.解析元数据
    meta = _parse_skill_meta(target_dir)

    # 6.刷新 Agent 工具
    try:
        from app.services.agent_orchestrator import agent_orchestrator
        await agent_orchestrator.refresh_tools()
    except Exception as e:
        logger.warning("Failed to refresh agent tools after skill import, error=%s", str(e))

    logger.info("Skill directory imported: %s, files=%d", skill_dir_name, len(saved_files))

    return SkillFileInfo(
        name=skill_dir_name,
        displayName=meta["display_name"],
        description=meta["description"],
        hasScript=_has_script(target_dir),
        files=saved_files,
    )


@router.delete("/{skill_name}", summary="删除技能", status_code=204)
async def delete_skill_file(skill_name: str) -> None:
    """删除指定的文件型技能目录"""
    logger.info("DELETE /api/skill-files/%s", skill_name)

    skill_dir = SKILLS_DIR / skill_name
    if not skill_dir.exists():
        raise HTTPException(status_code=404, detail="技能不存在")

    shutil.rmtree(skill_dir)
    logger.info("Skill directory deleted: %s", skill_name)

    # 刷新 Agent 工具
    try:
        from app.services.agent_orchestrator import agent_orchestrator
        await agent_orchestrator.refresh_tools()
    except Exception as e:
        logger.warning("Failed to refresh agent tools after skill delete, error=%s", str(e))
