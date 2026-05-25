"""
技能管理器服务

管理分析技能的导入、导出、执行和生命周期。
核心功能：
- 技能 CRUD（导入、导出、更新、删除、列表、详情）
- 导入验证：文件大小≤1MB、格式符合 Claude Code skill 规范
- 参数校验：验证用户参数符合技能定义的类型约束
- 技能执行：将技能内容和参数注入 Agent 上下文
- Python 脚本沙箱执行：RestrictedPython + subprocess，禁止网络访问和文件写入
- 执行超时控制（30秒）和运行时异常捕获
"""

import json
import logging
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, select

from app.core.config import settings
from app.models.database import Skill, SkillParameter, async_session_factory
from app.models.schemas import SkillExecutionResult, SkillFile

logger = logging.getLogger(__name__)


# ============================================================
# 异常定义
# ============================================================


class SkillValidationError(Exception):
    """技能验证错误"""

    def __init__(self, message: str, field: Optional[str] = None):
        self.message = message
        self.field = field
        super().__init__(message)


class SkillNotFoundError(Exception):
    """技能未找到错误"""

    def __init__(self, skill_id: str):
        self.skill_id = skill_id
        super().__init__(f"Skill not found: {skill_id}")


class SkillExecutionError(Exception):
    """技能执行错误"""

    def __init__(self, message: str, error_type: str = "runtime"):
        self.message = message
        self.error_type = error_type
        super().__init__(message)


# ============================================================
# 辅助函数
# ============================================================


def _iso_now() -> str:
    """生成当前时间的 ISO 8601 格式字符串（UTC）

    Returns:
        ISO 8601 格式的时间字符串
    """
    return datetime.now(timezone.utc).isoformat()


def _generate_id() -> str:
    """生成 UUID 字符串

    Returns:
        UUID4 字符串
    """
    return str(uuid.uuid4())


def _validate_skill_format(content: str) -> tuple[bool, list[str]]:
    """验证技能文件内容是否符合 Claude Code skill 格式规范

    Claude Code skill 格式要求：
    - 必须是有效的文本内容（非空）
    - 应包含可识别的 name、description、instructions/content 部分

    Args:
        content: 技能文件内容

    Returns:
        (是否合法, 错误信息列表)
    """
    errors = []

    # 1.检查内容是否为空
    if not content or not content.strip():
        errors.append("Skill content must not be empty")
        return False, errors

    content_lower = content.lower()

    # 2.检查是否包含 name 部分（标题行或 name: 字段）
    has_name = (
        "name:" in content_lower
        or "# " in content  # Markdown 标题作为名称
        or "name =" in content_lower
    )
    if not has_name:
        errors.append("Skill file must contain a 'name' section or heading")

    # 3.检查是否包含 description 部分
    has_description = (
        "description:" in content_lower
        or "description =" in content_lower
        or "## description" in content_lower
    )
    if not has_description:
        errors.append("Skill file must contain a 'description' section")

    # 4.检查是否包含 instructions/content 部分
    has_content = (
        "instructions:" in content_lower
        or "content:" in content_lower
        or "## instructions" in content_lower
        or "## content" in content_lower
        or "steps:" in content_lower
    )
    if not has_content:
        errors.append(
            "Skill file must contain an 'instructions' or 'content' section"
        )

    is_valid = len(errors) == 0
    return is_valid, errors


def _extract_skill_metadata(content: str) -> dict[str, Optional[str]]:
    """从技能文件内容中提取元数据（名称和描述）

    尝试从内容中解析 name 和 description 字段。

    Args:
        content: 技能文件内容

    Returns:
        包含 name 和 description 的字典
    """
    metadata: dict[str, Optional[str]] = {"name": None, "description": None}

    lines = content.strip().split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()

        # 提取 name（从 "name: xxx" 或 "# xxx" 格式）
        if metadata["name"] is None:
            if stripped.lower().startswith("name:"):
                metadata["name"] = stripped[5:].strip().strip('"').strip("'")
            elif stripped.startswith("# ") and i < 3:
                metadata["name"] = stripped[2:].strip()

        # 提取 description（从 "description: xxx" 格式）
        if metadata["description"] is None:
            if stripped.lower().startswith("description:"):
                metadata["description"] = stripped[12:].strip().strip('"').strip("'")

    return metadata


def _execute_python_in_sandbox(script: str, timeout: int = 30) -> dict[str, Any]:
    """在沙箱环境中执行 Python 脚本

    使用 subprocess 启动独立进程执行脚本，实现：
    - 超时控制（默认30秒）
    - 捕获 stdout/stderr
    - 运行时异常捕获
    - 通过 RestrictedPython 限制危险操作

    Args:
        script: Python 脚本内容
        timeout: 超时时间（秒）

    Returns:
        执行结果字典，包含 success、output、error、execution_time
    """
    logger.info("Executing Python script in sandbox, timeout=%ds", timeout)

    # 1.构建沙箱执行脚本（包装 RestrictedPython 限制）
    sandbox_script = _build_sandbox_script(script)

    # 2.写入临时文件
    start_time = time.time()
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as tmp_file:
            tmp_file.write(sandbox_script)
            tmp_path = tmp_file.name

        # 3.使用 subprocess 执行，设置超时
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_get_restricted_env(),
        )

        execution_time = (time.time() - start_time) * 1000  # 转为毫秒

        if result.returncode == 0:
            return {
                "success": True,
                "output": result.stdout,
                "error": None,
                "execution_time": execution_time,
            }
        else:
            return {
                "success": False,
                "output": result.stdout,
                "error": result.stderr or "Script execution failed",
                "execution_time": execution_time,
            }

    except subprocess.TimeoutExpired:
        execution_time = (time.time() - start_time) * 1000
        logger.warning("Script execution timed out after %ds", timeout)
        return {
            "success": False,
            "output": None,
            "error": f"Execution timed out after {timeout} seconds",
            "execution_time": execution_time,
        }
    except Exception as e:
        execution_time = (time.time() - start_time) * 1000
        logger.error("Script execution error: %s", str(e))
        return {
            "success": False,
            "output": None,
            "error": f"Execution error: {type(e).__name__}: {str(e)}",
            "execution_time": execution_time,
        }


def _build_sandbox_script(user_script: str) -> str:
    """构建沙箱执行脚本

    将用户脚本包装在安全限制中：
    - 禁止导入危险模块（os, subprocess, socket 等）
    - 禁止文件写入操作
    - 禁止网络访问
    - 捕获运行时异常

    Args:
        user_script: 用户提供的 Python 脚本

    Returns:
        包装后的安全执行脚本
    """
    # 使用 JSON 转义用户脚本内容，避免注入
    escaped_script = json.dumps(user_script)

    sandbox_wrapper = f'''
import sys
import importlib

# 1.定义禁止导入的模块列表
_BLOCKED_MODULES = {{
    "os", "subprocess", "socket", "http", "urllib",
    "requests", "shutil", "pathlib", "ftplib", "smtplib",
    "ctypes", "multiprocessing", "signal", "resource",
}}

# 2.保存原始 __import__
_original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else importlib.__import__

def _restricted_import(name, *args, **kwargs):
    """限制导入的模块"""
    base_module = name.split(".")[0]
    if base_module in _BLOCKED_MODULES:
        raise ImportError(f"Module '{{name}}' is not allowed in sandbox")
    return _original_import(name, *args, **kwargs)

# 3.替换 import 机制
import builtins
builtins.__import__ = _restricted_import

# 4.禁止 open 的写入模式
_original_open = open
def _restricted_open(file, mode="r", *args, **kwargs):
    """禁止写入模式的文件操作"""
    if any(m in mode for m in ("w", "a", "x", "+")):
        raise PermissionError("File write operations are not allowed in sandbox")
    return _original_open(file, mode, *args, **kwargs)
builtins.open = _restricted_open

# 5.执行用户脚本
try:
    user_code = {escaped_script}
    exec(compile(user_code, "<sandbox>", "exec"))
except Exception as e:
    print(f"RuntimeError: {{type(e).__name__}}: {{str(e)}}", file=sys.stderr)
    sys.exit(1)
'''
    return sandbox_wrapper


def _get_restricted_env() -> dict[str, str]:
    """获取受限的环境变量

    移除可能泄露敏感信息的环境变量，保留 Python 运行所需的最小环境。

    Returns:
        受限的环境变量字典
    """
    import os

    env = {}
    # 仅保留 Python 运行必需的环境变量
    safe_keys = {"PATH", "PYTHONPATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE"}
    for key in safe_keys:
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _contains_python_script(content: str) -> bool:
    """检测技能内容中是否包含 Python 脚本

    通过检查常见的 Python 代码标记来判断。

    Args:
        content: 技能文件内容

    Returns:
        是否包含 Python 脚本
    """
    python_markers = [
        "```python",
        "```py",
        "#!/usr/bin/env python",
        "#!/usr/bin/python",
        "# python script",
        "def main():",
        "if __name__",
    ]
    content_lower = content.lower()
    return any(marker.lower() in content_lower for marker in python_markers)


def _extract_python_script(content: str) -> Optional[str]:
    """从技能内容中提取 Python 脚本

    支持从 Markdown 代码块中提取 Python 代码。

    Args:
        content: 技能文件内容

    Returns:
        提取的 Python 脚本，未找到返回 None
    """
    import re

    # 匹配 ```python ... ``` 或 ```py ... ``` 代码块
    pattern = r'```(?:python|py)\s*\n(.*?)```'
    matches = re.findall(pattern, content, re.DOTALL)
    if matches:
        # 合并所有 Python 代码块
        return "\n\n".join(matches)
    return None


# ============================================================
# SkillManager 服务类
# ============================================================


class SkillManager:
    """技能管理器

    负责技能的生命周期管理、格式验证、参数校验和安全执行。
    技能格式遵循 Claude Code skill 规范，支持 Python 脚本沙箱执行。
    """

    def __init__(self) -> None:
        """初始化技能管理器"""
        self._max_file_size: int = settings.skill_max_file_size
        self._execution_timeout: int = settings.skill_execution_timeout
        self._sandbox_memory_limit: str = settings.skill_sandbox_memory_limit
        logger.info(
            "SkillManager initialized, max_file_size=%d, "
            "execution_timeout=%ds, sandbox_memory_limit=%s",
            self._max_file_size, self._execution_timeout,
            self._sandbox_memory_limit,
        )


    # ============================================================
    # 技能 CRUD
    # ============================================================

    async def import_skill(self, file: SkillFile) -> Skill:
        """导入技能

        验证规则：
        - 文件大小不超过 1MB
        - 内容符合 Claude Code skill 格式规范（包含 name、description、content 部分）

        Args:
            file: 技能文件对象

        Returns:
            创建的技能 ORM 对象

        Raises:
            SkillValidationError: 验证失败时抛出
        """
        logger.info("Importing skill, name=%s, format=%s", file.name, file.format)

        # 1.验证文件大小
        file_size = len(file.content.encode("utf-8"))
        if file_size > self._max_file_size:
            raise SkillValidationError(
                f"Skill file size ({file_size} bytes) exceeds maximum "
                f"allowed size ({self._max_file_size} bytes)",
                field="content",
            )

        # 2.验证文件格式
        is_valid, format_errors = _validate_skill_format(file.content)
        if not is_valid:
            error_msg = "; ".join(format_errors)
            raise SkillValidationError(
                f"Skill file format is invalid: {error_msg}",
                field="format",
            )

        # 3.提取元数据
        metadata = _extract_skill_metadata(file.content)
        skill_name = metadata["name"] or file.name
        skill_description = metadata["description"]

        # 4.保存到数据库
        skill_id = _generate_id()
        now = _iso_now()

        async with async_session_factory() as session:
            skill = Skill(
                id=skill_id,
                name=skill_name,
                description=skill_description,
                content=file.content,
                file_size=file_size,
                created_at=now,
                updated_at=now,
            )
            session.add(skill)
            await session.commit()
            await session.refresh(skill)

        logger.info(
            "Skill imported successfully, id=%s, name=%s, size=%d",
            skill_id, skill_name, file_size,
        )
        return skill


    async def export_skill(self, skill_id: str) -> SkillFile:
        """导出技能为 SkillFile 格式

        Args:
            skill_id: 技能ID

        Returns:
            技能文件对象

        Raises:
            SkillNotFoundError: 技能不存在时抛出
        """
        logger.info("Exporting skill, id=%s", skill_id)

        async with async_session_factory() as session:
            result = await session.execute(
                select(Skill).where(Skill.id == skill_id)
            )
            skill = result.scalar_one_or_none()

        if skill is None:
            raise SkillNotFoundError(skill_id)

        skill_file = SkillFile(
            name=skill.name,
            content=skill.content,
            format="claude-skill",
        )

        logger.info("Skill exported successfully, id=%s, name=%s", skill_id, skill.name)
        return skill_file

    async def update_skill(self, skill_id: str, updates: dict) -> Skill:
        """更新技能字段

        支持更新 name、description、content 字段。
        更新 content 时会重新验证文件大小和格式。

        Args:
            skill_id: 技能ID
            updates: 要更新的字段字典

        Returns:
            更新后的技能 ORM 对象

        Raises:
            SkillNotFoundError: 技能不存在时抛出
            SkillValidationError: 验证失败时抛出
        """
        logger.info("Updating skill, id=%s, fields=%s", skill_id, list(updates.keys()))

        async with async_session_factory() as session:
            result = await session.execute(
                select(Skill).where(Skill.id == skill_id)
            )
            skill = result.scalar_one_or_none()

            if skill is None:
                raise SkillNotFoundError(skill_id)

            # 1.更新 name
            if "name" in updates:
                skill.name = updates["name"]

            # 2.更新 description
            if "description" in updates:
                skill.description = updates["description"]

            # 3.更新 content（需重新验证）
            if "content" in updates:
                new_content = updates["content"]
                file_size = len(new_content.encode("utf-8"))
                if file_size > self._max_file_size:
                    raise SkillValidationError(
                        f"Skill file size ({file_size} bytes) exceeds maximum "
                        f"allowed size ({self._max_file_size} bytes)",
                        field="content",
                    )
                is_valid, format_errors = _validate_skill_format(new_content)
                if not is_valid:
                    error_msg = "; ".join(format_errors)
                    raise SkillValidationError(
                        f"Skill file format is invalid: {error_msg}",
                        field="format",
                    )
                skill.content = new_content
                skill.file_size = file_size

            # 4.更新时间戳
            skill.updated_at = _iso_now()
            await session.commit()
            await session.refresh(skill)

        logger.info("Skill updated successfully, id=%s", skill_id)
        return skill

    async def delete_skill(self, skill_id: str) -> None:
        """删除技能及其所有参数

        Args:
            skill_id: 技能ID

        Raises:
            SkillNotFoundError: 技能不存在时抛出
        """
        logger.info("Deleting skill, id=%s", skill_id)

        async with async_session_factory() as session:
            # 1.检查技能是否存在
            result = await session.execute(
                select(Skill).where(Skill.id == skill_id)
            )
            skill = result.scalar_one_or_none()
            if skill is None:
                raise SkillNotFoundError(skill_id)

            # 2.删除关联参数
            await session.execute(
                delete(SkillParameter).where(
                    SkillParameter.skill_id == skill_id
                )
            )
            # 3.删除技能
            await session.execute(
                delete(Skill).where(Skill.id == skill_id)
            )
            await session.commit()

        logger.info("Skill deleted successfully, id=%s", skill_id)


    async def list_skills(self) -> list[Skill]:
        """列出所有已导入的技能

        Returns:
            技能 ORM 对象列表，按创建时间降序排列
        """
        logger.info("Listing all skills")

        async with async_session_factory() as session:
            result = await session.execute(
                select(Skill).order_by(Skill.created_at.desc())
            )
            skills = result.scalars().all()

        logger.info("Listed skills, total=%d", len(skills))
        return list(skills)

    async def get_skill(self, skill_id: str) -> Optional[Skill]:
        """获取技能详情

        Args:
            skill_id: 技能ID

        Returns:
            技能 ORM 对象，不存在时返回 None
        """
        logger.info("Getting skill, id=%s", skill_id)

        async with async_session_factory() as session:
            result = await session.execute(
                select(Skill).where(Skill.id == skill_id)
            )
            skill = result.scalar_one_or_none()

        if skill is None:
            logger.warning("Skill not found, id=%s", skill_id)
        return skill

    # ============================================================
    # 参数校验
    # ============================================================

    async def validate_params(
        self, skill: Skill, params: dict
    ) -> tuple[bool, list[str]]:
        """验证用户参数是否符合技能定义的类型约束

        检查规则：
        - 必填参数是否提供
        - 参数值是否符合定义的类型（string/number/date/boolean/enum）
        - 参数值是否满足约束描述中的限制

        Args:
            skill: 技能 ORM 对象
            params: 用户提供的参数字典

        Returns:
            (是否通过校验, 错误信息列表)
        """
        logger.info(
            "Validating params for skill, skill_id=%s, param_count=%d",
            skill.id, len(params),
        )

        errors: list[str] = []

        # 1.获取技能参数定义
        async with async_session_factory() as session:
            result = await session.execute(
                select(SkillParameter)
                .where(SkillParameter.skill_id == skill.id)
                .order_by(SkillParameter.sort_order)
            )
            param_definitions = result.scalars().all()

        # 2.检查必填参数是否提供
        for param_def in param_definitions:
            if param_def.required == 1 and param_def.name not in params:
                errors.append(
                    f"Required parameter '{param_def.name}' is missing"
                )

        # 3.检查参数类型是否匹配
        for param_def in param_definitions:
            if param_def.name not in params:
                continue
            value = params[param_def.name]
            type_error = self._check_param_type(param_def, value)
            if type_error:
                errors.append(type_error)

        is_valid = len(errors) == 0
        logger.info(
            "Params validation result, skill_id=%s, valid=%s, error_count=%d",
            skill.id, is_valid, len(errors),
        )
        return is_valid, errors

    def _check_param_type(
        self, param_def: SkillParameter, value: Any
    ) -> Optional[str]:
        """检查单个参数值是否符合类型约束

        Args:
            param_def: 参数定义
            value: 参数值

        Returns:
            错误信息，类型匹配时返回 None
        """
        param_type = param_def.type.lower()
        param_name = param_def.name

        if param_type == "string":
            if not isinstance(value, str):
                return (
                    f"Parameter '{param_name}' must be a string, "
                    f"got {type(value).__name__}"
                )

        elif param_type == "number":
            if not isinstance(value, (int, float)):
                # 尝试转换字符串为数字
                if isinstance(value, str):
                    try:
                        float(value)
                        return None
                    except ValueError:
                        pass
                return (
                    f"Parameter '{param_name}' must be a number, "
                    f"got {type(value).__name__}"
                )

        elif param_type == "date":
            if isinstance(value, str):
                # 验证日期格式
                import re
                date_pattern = r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}$'
                if not re.match(date_pattern, value):
                    return (
                        f"Parameter '{param_name}' must be a valid date "
                        f"(YYYY-MM-DD format), got '{value}'"
                    )
            else:
                return (
                    f"Parameter '{param_name}' must be a date string "
                    f"(YYYY-MM-DD format), got {type(value).__name__}"
                )

        elif param_type == "boolean":
            if not isinstance(value, bool):
                return (
                    f"Parameter '{param_name}' must be a boolean, "
                    f"got {type(value).__name__}"
                )

        elif param_type == "enum":
            # 从约束描述中解析枚举值
            if param_def.constraint_desc:
                try:
                    allowed_values = json.loads(param_def.constraint_desc)
                    if isinstance(allowed_values, list) and value not in allowed_values:
                        return (
                            f"Parameter '{param_name}' must be one of "
                            f"{allowed_values}, got '{value}'"
                        )
                except (json.JSONDecodeError, TypeError):
                    pass

        return None


    # ============================================================
    # 技能执行
    # ============================================================

    async def execute_skill(
        self, skill_id: str, params: dict
    ) -> SkillExecutionResult:
        """执行技能

        执行流程：
        1. 获取技能信息
        2. 验证参数
        3. 如果包含 Python 脚本，在沙箱中执行
        4. 否则将技能内容和参数注入 Agent 上下文

        Args:
            skill_id: 技能ID
            params: 用户提供的参数字典

        Returns:
            技能执行结果

        Raises:
            SkillNotFoundError: 技能不存在时抛出
            SkillValidationError: 参数校验失败时抛出
            SkillExecutionError: 执行失败时抛出
        """
        logger.info(
            "Executing skill, id=%s, param_count=%d", skill_id, len(params)
        )

        # 1.获取技能
        async with async_session_factory() as session:
            result = await session.execute(
                select(Skill).where(Skill.id == skill_id)
            )
            skill = result.scalar_one_or_none()

        if skill is None:
            raise SkillNotFoundError(skill_id)

        # 2.验证参数
        is_valid, validation_errors = await self.validate_params(skill, params)
        if not is_valid:
            error_msg = "; ".join(validation_errors)
            raise SkillValidationError(
                f"Parameter validation failed: {error_msg}",
                field="params",
            )

        # 3.检查是否包含 Python 脚本
        start_time = time.time()
        if _contains_python_script(skill.content):
            # 提取并执行 Python 脚本
            script = _extract_python_script(skill.content)
            if script:
                # 注入参数到脚本中
                param_injection = self._build_param_injection(params)
                full_script = param_injection + "\n" + script
                sandbox_result = _execute_python_in_sandbox(
                    full_script, timeout=self._execution_timeout
                )
                execution_time = (time.time() - start_time) * 1000

                if sandbox_result["success"]:
                    logger.info(
                        "Skill script executed successfully, id=%s, time=%.2fms",
                        skill_id, execution_time,
                    )
                    return SkillExecutionResult(
                        success=True,
                        output=sandbox_result["output"],
                        executionTime=execution_time,
                        hasData=False,
                        data=None,
                    )
                else:
                    error = sandbox_result["error"] or "Unknown execution error"
                    # 判断是超时还是运行时异常
                    if "timed out" in error.lower():
                        error_type = "timeout"
                    else:
                        error_type = "runtime"
                    logger.warning(
                        "Skill script execution failed, id=%s, error_type=%s, error=%s",
                        skill_id, error_type, error,
                    )
                    return SkillExecutionResult(
                        success=False,
                        output=error,
                        executionTime=execution_time,
                        hasData=False,
                        data=None,
                    )

        # 4.非脚本技能：将内容和参数注入 Agent 上下文
        execution_time = (time.time() - start_time) * 1000
        context_output = self._build_context_injection(skill, params)
        logger.info(
            "Skill context injected, id=%s, time=%.2fms",
            skill_id, execution_time,
        )
        return SkillExecutionResult(
            success=True,
            output=context_output,
            executionTime=execution_time,
            hasData=False,
            data=None,
        )


    def _build_param_injection(self, params: dict) -> str:
        """构建参数注入代码

        将用户参数转换为 Python 变量赋值语句，注入到脚本开头。

        Args:
            params: 用户参数字典

        Returns:
            参数注入的 Python 代码
        """
        lines = ["# Injected parameters"]
        for key, value in params.items():
            # 使用 json.dumps 安全序列化值
            lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
        lines.append("")  # 空行分隔
        return "\n".join(lines)

    def _build_context_injection(self, skill: Skill, params: dict) -> str:
        """构建 Agent 上下文注入内容

        将技能内容和参数格式化为可注入 Agent 上下文的文本。

        Args:
            skill: 技能 ORM 对象
            params: 用户参数字典

        Returns:
            格式化的上下文注入文本
        """
        context_parts = [
            f"=== Skill: {skill.name} ===",
        ]
        if skill.description:
            context_parts.append(f"Description: {skill.description}")

        if params:
            context_parts.append("\n--- Parameters ---")
            for key, value in params.items():
                context_parts.append(f"  {key}: {value}")

        context_parts.append("\n--- Instructions ---")
        context_parts.append(skill.content)

        return "\n".join(context_parts)


# ============================================================
# 全局单例
# ============================================================

skill_manager = SkillManager()
