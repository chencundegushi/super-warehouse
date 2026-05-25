"""
Skill Tools 动态加载器

从 backend/skills/ 目录自动加载所有技能并注册为 LangChain Tool。
每个技能目录需包含 SKILL.md（描述）和至少一个 .py 脚本。

加载规则：
- 读取 SKILL.md 的 frontmatter 获取 name、description
- 找到目录下的 .py 脚本作为执行入口
- 自动生成 BaseTool 子类，执行时调用 python 脚本
- 脚本参数通过 JSON 字符串传入（--params '{...}'）
- 支持热加载：调用 load_skill_tools() 即可刷新

技能目录结构示例：
    backend/skills/
    ├── business-analysis/
    │   ├── SKILL.md
    │   └── query_business_data.py
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


class SkillInput(BaseModel):
    """通用技能工具输入

    所有参数通过 JSON 字符串传递，由脚本自行解析。
    """
    params_json: str = Field(
        default="{}",
        description="技能参数 JSON 字符串。具体参数见工具描述。"
    )


def _parse_skill_md(skill_md_path: Path) -> dict:
    """解析 SKILL.md 的 frontmatter

    Args:
        skill_md_path: SKILL.md 文件路径

    Returns:
        包含 name、description、allowed_tools 的字典
    """
    content = skill_md_path.read_text(encoding="utf-8")
    result = {"name": "", "description": "", "content": content}

    if content.startswith("---"):
        end = content.find("---", 3)
        if end > 0:
            frontmatter = content[3:end].strip()
            for line in frontmatter.split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip().lower().replace("-", "_")
                    val = val.strip()
                    if key == "name":
                        result["name"] = val
                    elif key == "description":
                        result["description"] = val

    return result


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


def _create_skill_tool(skill_dir: Path, meta: dict, script_path: Path) -> BaseTool:
    """为单个技能创建 Tool 实例

    Args:
        skill_dir: 技能目录
        meta: SKILL.md 解析结果
        script_path: 脚本路径

    Returns:
        BaseTool 实例
    """
    skill_name = meta["name"] or skill_dir.name
    skill_desc = meta["description"] or f"技能：{skill_name}"

    # Tool name 只能用 ASCII
    tool_name = f"skill_{re.sub(r'[^a-zA-Z0-9_]', '_', skill_dir.name)}"

    # 捕获到闭包
    _script = str(script_path)
    _cwd = str(skill_dir)
    _skill_content = meta.get("content", "")

    class DynamicSkillTool(BaseTool):
        """动态加载的技能工具"""
        name: str = tool_name
        description: str = skill_desc
        args_schema: Type[BaseModel] = SkillInput

        def _run(self, params_json: str = "{}") -> str:
            """执行技能脚本"""
            logger.info("Skill tool called, name=%s, params=%s", skill_name, params_json[:200])

            try:
                params = json.loads(params_json) if params_json else {}
            except json.JSONDecodeError:
                params = {}

            # 构建命令行参数
            cmd = [sys.executable, _script]

            # 将 JSON 参数展开为命令行参数（--key value）
            for key, value in params.items():
                cmd.append(f"--{key}")
                cmd.append(str(value))

            # 注入数据库连接参数（如果脚本支持）
            if "--host" not in cmd:
                cmd.extend(["--host", settings.doris_host])
            if "--port" not in cmd:
                cmd.extend(["--port", str(settings.doris_port)])
            if "--user" not in cmd:
                cmd.extend(["--user", settings.doris_user])
            if "--password" not in cmd:
                cmd.extend(["--password", settings.doris_password])

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=_cwd,
                )

                if result.returncode != 0:
                    logger.error("Skill script failed, name=%s, stderr=%s", skill_name, result.stderr[:300])
                    return json.dumps({
                        "error": f"脚本执行失败：{result.stderr[:200]}"
                    }, ensure_ascii=False)

                output = result.stdout.strip()
                logger.info("Skill script completed, name=%s, output_length=%d", skill_name, len(output))
                return output

            except subprocess.TimeoutExpired:
                return json.dumps({"error": "脚本执行超时（60秒）"}, ensure_ascii=False)
            except Exception as e:
                logger.error("Skill script error, name=%s, error=%s", skill_name, str(e))
                return json.dumps({"error": f"执行错误：{str(e)}"}, ensure_ascii=False)

    return DynamicSkillTool()


def load_skill_tools() -> list[BaseTool]:
    """从 backend/skills/ 目录动态加载所有技能

    扫描每个子目录，解析 SKILL.md，找到脚本，创建 Tool。

    Returns:
        技能 Tool 列表
    """
    tools = []

    if not SKILLS_DIR.exists():
        logger.info("Skills directory not found: %s, creating it", SKILLS_DIR)
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        return tools

    for skill_dir in SKILLS_DIR.iterdir():
        if not skill_dir.is_dir():
            continue

        # 必须有 SKILL.md
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            logger.debug("Skipping %s: no SKILL.md", skill_dir.name)
            continue

        # 解析元数据
        meta = _parse_skill_md(skill_md)

        # 找到脚本
        script = _find_script(skill_dir)
        if not script:
            logger.warning("Skipping %s: no .py script found", skill_dir.name)
            continue

        # 创建 Tool
        tool = _create_skill_tool(skill_dir, meta, script)
        tools.append(tool)
        logger.info("Loaded skill tool: %s (%s)", tool.name, meta.get("name", skill_dir.name))

    logger.info("Loaded %d skill tools from %s", len(tools), SKILLS_DIR)
    return tools
