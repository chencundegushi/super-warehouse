"""
Skill Tools 脚本执行器

为 deepagents 原生 Skills 提供脚本执行能力。
deepagents 负责 Skill 发现和 progressive disclosure（SKILL.md 加载），
本模块提供自定义 Tool 让 agent 能够执行 skills 目录下的 Python 脚本。

技能目录结构示例：
    backend/skills/
    ├── business-analysis/
    │   ├── SKILL.md          ← deepagents 原生加载
    │   └── query_business_data.py  ← 通过本模块的 Tool 执行
    └── another-skill/
        ├── SKILL.md
        └── main.py
"""

import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)

# 技能目录
SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"


class SkillScriptInput(BaseModel):
    """技能脚本执行工具输入

    Attributes:
        skill_name: 技能目录名称（如 business-analysis）
        params_json: 脚本参数 JSON 字符串
    """
    skill_name: str = Field(
        description="技能目录名称，如 'business-analysis'"
    )
    params_json: str = Field(
        default="{}",
        description="脚本参数 JSON 字符串，如 {\"month\": \"2026-04\"}"
    )


def _find_script(skill_dir: Path) -> Path | None:
    """找到技能目录下的主脚本

    优先级：main.py > query_*.py > 第一个 .py 文件

    Args:
        skill_dir: 技能目录

    Returns:
        脚本路径，未找到返回 None
    """
    # 优先 main.py
    main_py = skill_dir / "main.py"
    if main_py.exists():
        return main_py

    # 其次 query_*.py
    query_scripts = list(skill_dir.glob("query_*.py"))
    if query_scripts:
        return query_scripts[0]

    # 最后任意 .py
    py_files = [f for f in skill_dir.glob("*.py") if f.name != "__init__.py"]
    if py_files:
        return py_files[0]

    return None


class RunSkillScriptTool(BaseTool):
    """执行技能脚本工具

    在 skills 目录下找到指定技能的 Python 脚本并执行。
    自动注入数据库连接参数。
    """
    name: str = "run_skill_script"
    description: str = (
        "执行指定技能目录下的 Python 脚本。"
        "可用技能：business-analysis（DramaTalk 平台经营数据查询，参数：month=YYYY-MM）。"
        "脚本会连接数据库查询数据并返回 JSON 结果。"
    )
    args_schema: Type[BaseModel] = SkillScriptInput

    def _run(self, skill_name: str, params_json: str = "{}") -> str:
        """执行技能脚本

        Args:
            skill_name: 技能目录名称
            params_json: 参数 JSON 字符串

        Returns:
            脚本输出（通常为 JSON）
        """
        logger.info(
            "Skill script execution requested, skill_name=%s, params=%s",
            skill_name, params_json[:200],
        )

        # 1.查找技能目录
        skill_dir = SKILLS_DIR / skill_name
        if not skill_dir.exists() or not skill_dir.is_dir():
            available = [d.name for d in SKILLS_DIR.iterdir() if d.is_dir()] if SKILLS_DIR.exists() else []
            return json.dumps({
                "error": f"技能 '{skill_name}' 不存在。可用技能：{available}"
            }, ensure_ascii=False)

        # 2.查找脚本
        script = _find_script(skill_dir)
        if not script:
            return json.dumps({
                "error": f"技能 '{skill_name}' 目录下未找到可执行的 Python 脚本"
            }, ensure_ascii=False)

        # 3.解析参数
        try:
            params = json.loads(params_json) if params_json else {}
        except json.JSONDecodeError:
            params = {}

        # 4.构建命令行
        cmd = [sys.executable, str(script)]

        # 将 JSON 参数展开为命令行参数（--key value）
        for key, value in params.items():
            cmd.append(f"--{key}")
            cmd.append(str(value))

        # 注入数据库连接参数
        if "--host" not in cmd:
            cmd.extend(["--host", settings.doris_host])
        if "--port" not in cmd:
            cmd.extend(["--port", str(settings.doris_port)])
        if "--user" not in cmd:
            cmd.extend(["--user", settings.doris_user])
        if "--password" not in cmd:
            cmd.extend(["--password", settings.doris_password])

        # 5.执行脚本
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(skill_dir),
            )

            if result.returncode != 0:
                error_detail = result.stderr.strip() or result.stdout.strip()
                logger.error(
                    "Skill script failed, skill_name=%s, stderr=%s, stdout=%s",
                    skill_name, result.stderr[:300], result.stdout[:300],
                )
                return json.dumps({
                    "error": f"脚本执行失败：{error_detail[:500]}"
                }, ensure_ascii=False)

            output = result.stdout.strip()
            logger.info(
                "Skill script completed, skill_name=%s, output_length=%d",
                skill_name, len(output),
            )
            return output

        except subprocess.TimeoutExpired:
            logger.error("Skill script timeout, skill_name=%s", skill_name)
            return json.dumps({"error": "脚本执行超时（120秒）"}, ensure_ascii=False)
        except Exception as e:
            logger.error("Skill script error, skill_name=%s, error=%s", skill_name, str(e))
            return json.dumps({"error": f"执行错误：{str(e)}"}, ensure_ascii=False)


def load_skill_tools() -> list[BaseTool]:
    """加载技能脚本执行工具

    返回一个通用的脚本执行工具，agent 可通过指定 skill_name 执行任意技能脚本。

    Returns:
        技能 Tool 列表
    """
    tools = []

    if not SKILLS_DIR.exists():
        logger.info("Skills directory not found: %s, creating it", SKILLS_DIR)
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        return tools

    # 检查是否有可用的技能（至少有一个目录包含 .py 脚本）
    has_skills = False
    for skill_dir in SKILLS_DIR.iterdir():
        if skill_dir.is_dir() and _find_script(skill_dir):
            has_skills = True
            break

    if has_skills:
        tools.append(RunSkillScriptTool())
        logger.info("Loaded run_skill_script tool, skills_dir=%s", SKILLS_DIR)
    else:
        logger.info("No executable skills found in %s", SKILLS_DIR)

    return tools
