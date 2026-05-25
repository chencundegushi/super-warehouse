"""
Skill Manager 单元测试

测试技能管理器的核心功能：
- 导入验证（文件大小、格式校验）
- CRUD 操作
- 参数校验
- 沙箱执行（超时、异常捕获）
"""

import pytest
import pytest_asyncio
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.database import Base, Skill, SkillParameter
from app.models.schemas import SkillFile
from app.services.skill_manager import (
    SkillManager,
    SkillNotFoundError,
    SkillValidationError,
    _validate_skill_format,
    _extract_skill_metadata,
    _contains_python_script,
    _extract_python_script,
    _execute_python_in_sandbox,
)


# ============================================================
# 测试 Fixtures
# ============================================================


@pytest_asyncio.fixture
async def test_engine():
    """创建内存数据库引擎用于测试"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def test_session_factory(test_engine):
    """创建测试用异步会话工厂"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    return factory


@pytest.fixture
def skill_manager(test_session_factory):
    """创建 SkillManager 实例，使用内存数据库"""
    with patch(
        "app.services.skill_manager.async_session_factory",
        test_session_factory,
    ):
        manager = SkillManager()
        yield manager


@pytest.fixture
def valid_skill_content():
    """有效的 Claude Code skill 格式内容"""
    return """# Data Analysis Skill
name: data-analysis
description: Analyze sales data and generate reports

## Instructions
1. Load the data from the specified source
2. Apply filters based on parameters
3. Generate summary statistics
content: This skill analyzes sales data
"""


@pytest.fixture
def valid_skill_file(valid_skill_content):
    """有效的技能文件"""
    return SkillFile(
        name="data-analysis",
        content=valid_skill_content,
        format="claude-skill",
    )


@pytest.fixture
def python_skill_content():
    """包含 Python 脚本的技能内容"""
    return """# Python Analysis Skill
name: python-analysis
description: Run Python analysis script

## Instructions
Execute the following Python script:

```python
result = x * 2 + y
print(f"Result: {result}")
```

content: Python-based analysis
"""


# ============================================================
# 格式验证测试
# ============================================================


class TestValidateSkillFormat:
    """技能格式验证测试"""

    def test_valid_format(self, valid_skill_content):
        """有效格式应通过验证"""
        is_valid, errors = _validate_skill_format(valid_skill_content)
        assert is_valid is True
        assert errors == []

    def test_empty_content(self):
        """空内容应拒绝"""
        is_valid, errors = _validate_skill_format("")
        assert is_valid is False
        assert "Skill content must not be empty" in errors[0]

    def test_whitespace_only(self):
        """仅空白内容应拒绝"""
        is_valid, errors = _validate_skill_format("   \n\t  ")
        assert is_valid is False

    def test_missing_name(self):
        """缺少 name 部分应报错"""
        content = "description: test\ncontent: test instructions"
        is_valid, errors = _validate_skill_format(content)
        assert is_valid is False
        assert any("name" in e.lower() for e in errors)

    def test_missing_description(self):
        """缺少 description 部分应报错"""
        content = "# My Skill\ncontent: test instructions"
        is_valid, errors = _validate_skill_format(content)
        assert is_valid is False
        assert any("description" in e.lower() for e in errors)

    def test_missing_content(self):
        """缺少 instructions/content 部分应报错"""
        content = "# My Skill\ndescription: test desc"
        is_valid, errors = _validate_skill_format(content)
        assert is_valid is False
        assert any("instructions" in e.lower() or "content" in e.lower() for e in errors)


# ============================================================
# 元数据提取测试
# ============================================================


class TestExtractMetadata:
    """元数据提取测试"""

    def test_extract_name_from_field(self):
        """从 name: 字段提取名称"""
        content = "name: my-skill\ndescription: test"
        metadata = _extract_skill_metadata(content)
        assert metadata["name"] == "my-skill"

    def test_extract_name_from_heading(self):
        """从 Markdown 标题提取名称"""
        content = "# My Skill\ndescription: test"
        metadata = _extract_skill_metadata(content)
        assert metadata["name"] == "My Skill"

    def test_extract_description(self):
        """提取 description 字段"""
        content = "name: test\ndescription: This is a test skill"
        metadata = _extract_skill_metadata(content)
        assert metadata["description"] == "This is a test skill"


# ============================================================
# Python 脚本检测测试
# ============================================================


class TestPythonScriptDetection:
    """Python 脚本检测测试"""

    def test_detect_python_code_block(self):
        """检测 ```python 代码块"""
        content = "some text\n```python\nprint('hello')\n```"
        assert _contains_python_script(content) is True

    def test_detect_shebang(self):
        """检测 shebang 行"""
        content = "#!/usr/bin/env python\nprint('hello')"
        assert _contains_python_script(content) is True

    def test_no_python_script(self):
        """无 Python 脚本标记"""
        content = "This is just plain text with instructions"
        assert _contains_python_script(content) is False

    def test_extract_python_from_code_block(self):
        """从代码块中提取 Python 脚本"""
        content = "text\n```python\nx = 1\nprint(x)\n```\nmore text"
        script = _extract_python_script(content)
        assert script is not None
        assert "x = 1" in script
        assert "print(x)" in script


# ============================================================
# 导入技能测试
# ============================================================


class TestImportSkill:
    """技能导入测试"""

    @pytest.mark.asyncio
    async def test_import_valid_skill(self, skill_manager, valid_skill_file, test_session_factory):
        """导入有效技能应成功"""
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            skill = await skill_manager.import_skill(valid_skill_file)
            assert skill is not None
            assert skill.id is not None
            assert skill.name == "Data Analysis Skill"
            assert skill.file_size > 0

    @pytest.mark.asyncio
    async def test_import_oversized_file(self, skill_manager, test_session_factory):
        """超过 1MB 的文件应拒绝导入（Pydantic 层或 Service 层）"""
        from pydantic import ValidationError

        large_content = "# Skill\nname: big\ndescription: test\ncontent: x\n" + "x" * (1048577)
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            with pytest.raises((ValidationError, SkillValidationError)):
                file = SkillFile(name="big-skill", content=large_content, format="claude-skill")
                await skill_manager.import_skill(file)

    @pytest.mark.asyncio
    async def test_import_invalid_format(self, skill_manager, test_session_factory):
        """格式不合规范的文件应拒绝导入"""
        file = SkillFile(
            name="bad-skill",
            content="just some random text without proper sections",
            format="claude-skill",
        )
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            with pytest.raises(SkillValidationError) as exc_info:
                await skill_manager.import_skill(file)
            assert "format is invalid" in exc_info.value.message


# ============================================================
# CRUD 操作测试
# ============================================================


class TestSkillCRUD:
    """技能 CRUD 操作测试"""

    @pytest.mark.asyncio
    async def test_list_skills(self, skill_manager, valid_skill_file, test_session_factory):
        """列出所有技能"""
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            await skill_manager.import_skill(valid_skill_file)
            skills = await skill_manager.list_skills()
            assert len(skills) == 1

    @pytest.mark.asyncio
    async def test_get_skill(self, skill_manager, valid_skill_file, test_session_factory):
        """获取技能详情"""
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            imported = await skill_manager.import_skill(valid_skill_file)
            skill = await skill_manager.get_skill(imported.id)
            assert skill is not None
            assert skill.name == imported.name

    @pytest.mark.asyncio
    async def test_get_nonexistent_skill(self, skill_manager, test_session_factory):
        """获取不存在的技能应返回 None"""
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            skill = await skill_manager.get_skill("nonexistent-id")
            assert skill is None

    @pytest.mark.asyncio
    async def test_export_skill(self, skill_manager, valid_skill_file, test_session_factory):
        """导出技能"""
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            imported = await skill_manager.import_skill(valid_skill_file)
            exported = await skill_manager.export_skill(imported.id)
            assert exported.name == imported.name
            assert exported.content == valid_skill_file.content
            assert exported.format == "claude-skill"


    @pytest.mark.asyncio
    async def test_export_nonexistent_skill(self, skill_manager, test_session_factory):
        """导出不存在的技能应抛出异常"""
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            with pytest.raises(SkillNotFoundError):
                await skill_manager.export_skill("nonexistent-id")

    @pytest.mark.asyncio
    async def test_update_skill(self, skill_manager, valid_skill_file, test_session_factory):
        """更新技能字段"""
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            imported = await skill_manager.import_skill(valid_skill_file)
            updated = await skill_manager.update_skill(
                imported.id, {"name": "Updated Skill Name"}
            )
            assert updated.name == "Updated Skill Name"

    @pytest.mark.asyncio
    async def test_update_nonexistent_skill(self, skill_manager, test_session_factory):
        """更新不存在的技能应抛出异常"""
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            with pytest.raises(SkillNotFoundError):
                await skill_manager.update_skill("nonexistent-id", {"name": "x"})

    @pytest.mark.asyncio
    async def test_delete_skill(self, skill_manager, valid_skill_file, test_session_factory):
        """删除技能"""
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            imported = await skill_manager.import_skill(valid_skill_file)
            await skill_manager.delete_skill(imported.id)
            skill = await skill_manager.get_skill(imported.id)
            assert skill is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_skill(self, skill_manager, test_session_factory):
        """删除不存在的技能应抛出异常"""
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            with pytest.raises(SkillNotFoundError):
                await skill_manager.delete_skill("nonexistent-id")


# ============================================================
# 参数校验测试
# ============================================================


class TestValidateParams:
    """参数校验测试"""

    @pytest.mark.asyncio
    async def test_valid_params(self, skill_manager, valid_skill_file, test_session_factory):
        """有效参数应通过校验"""
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            skill = await skill_manager.import_skill(valid_skill_file)
            # 无参数定义时，空参数应通过
            is_valid, errors = await skill_manager.validate_params(skill, {})
            assert is_valid is True
            assert errors == []

    @pytest.mark.asyncio
    async def test_missing_required_param(self, skill_manager, valid_skill_file, test_session_factory):
        """缺少必填参数应校验失败"""
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            skill = await skill_manager.import_skill(valid_skill_file)
            # 手动添加参数定义
            async with test_session_factory() as session:
                param = SkillParameter(
                    id="param-1",
                    skill_id=skill.id,
                    name="start_date",
                    type="date",
                    required=1,
                    constraint_desc=None,
                    sort_order=0,
                )
                session.add(param)
                await session.commit()

            is_valid, errors = await skill_manager.validate_params(skill, {})
            assert is_valid is False
            assert any("start_date" in e for e in errors)

    @pytest.mark.asyncio
    async def test_wrong_type_param(self, skill_manager, valid_skill_file, test_session_factory):
        """类型不匹配的参数应校验失败"""
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            skill = await skill_manager.import_skill(valid_skill_file)
            # 添加 number 类型参数
            async with test_session_factory() as session:
                param = SkillParameter(
                    id="param-2",
                    skill_id=skill.id,
                    name="count",
                    type="number",
                    required=1,
                    constraint_desc=None,
                    sort_order=0,
                )
                session.add(param)
                await session.commit()

            is_valid, errors = await skill_manager.validate_params(
                skill, {"count": "not-a-number"}
            )
            assert is_valid is False
            assert any("number" in e.lower() for e in errors)


# ============================================================
# 沙箱执行测试
# ============================================================


class TestSandboxExecution:
    """沙箱执行测试"""

    def test_simple_script_execution(self):
        """简单脚本应成功执行"""
        result = _execute_python_in_sandbox("print('hello world')", timeout=10)
        assert result["success"] is True
        assert "hello world" in result["output"]

    def test_script_with_calculation(self):
        """包含计算的脚本应正确输出"""
        script = "x = 10\ny = 20\nprint(x + y)"
        result = _execute_python_in_sandbox(script, timeout=10)
        assert result["success"] is True
        assert "30" in result["output"]

    def test_script_timeout(self):
        """超时脚本应被终止"""
        script = "import time\ntime.sleep(60)"
        result = _execute_python_in_sandbox(script, timeout=2)
        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    def test_script_runtime_error(self):
        """运行时错误应被捕获"""
        script = "x = 1 / 0"
        result = _execute_python_in_sandbox(script, timeout=10)
        assert result["success"] is False
        assert result["error"] is not None

    def test_blocked_module_import(self):
        """禁止的模块导入应失败"""
        script = "import os\nprint(os.getcwd())"
        result = _execute_python_in_sandbox(script, timeout=10)
        assert result["success"] is False
        assert result["error"] is not None

    def test_blocked_file_write(self):
        """文件写入操作应被禁止"""
        script = "f = open('/tmp/test.txt', 'w')\nf.write('hack')"
        result = _execute_python_in_sandbox(script, timeout=10)
        assert result["success"] is False
        assert result["error"] is not None


# ============================================================
# 技能执行集成测试
# ============================================================


class TestExecuteSkill:
    """技能执行测试"""

    @pytest.mark.asyncio
    async def test_execute_context_skill(self, skill_manager, valid_skill_file, test_session_factory):
        """执行非脚本技能应注入上下文"""
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            skill = await skill_manager.import_skill(valid_skill_file)
            result = await skill_manager.execute_skill(skill.id, {})
            assert result.success is True
            assert result.output is not None
            assert "Data Analysis Skill" in result.output

    @pytest.mark.asyncio
    async def test_execute_python_skill(self, skill_manager, python_skill_content, test_session_factory):
        """执行包含 Python 脚本的技能"""
        file = SkillFile(
            name="python-skill",
            content=python_skill_content,
            format="claude-skill",
        )
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            skill = await skill_manager.import_skill(file)
            result = await skill_manager.execute_skill(skill.id, {"x": 5, "y": 3})
            assert result.success is True
            assert "Result: 13" in result.output

    @pytest.mark.asyncio
    async def test_execute_nonexistent_skill(self, skill_manager, test_session_factory):
        """执行不存在的技能应抛出异常"""
        with patch("app.services.skill_manager.async_session_factory", test_session_factory):
            with pytest.raises(SkillNotFoundError):
                await skill_manager.execute_skill("nonexistent-id", {})
