"""
数据库层单元测试

验证 ORM 模型定义、表创建和基本 CRUD 操作。
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.database import (
    Base,
    Conversation,
    Message,
    Metric,
    MetricParameter,
    Skill,
    SkillParameter,
    _iso_now,
)


@pytest.fixture
async def async_engine():
    """创建内存数据库引擎用于测试"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(async_engine):
    """创建测试用异步会话"""
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess


class TestTableCreation:
    """验证所有表正确创建"""

    async def test_all_tables_exist(self, async_engine):
        """验证6张表全部创建成功"""
        async with async_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            )
            tables = {row[0] for row in result.fetchall()}

        expected = {"conversations", "messages", "metrics", "metric_parameters", "skills", "skill_parameters"}
        assert expected.issubset(tables)


class TestConversationModel:
    """验证 Conversation 模型"""

    async def test_create_conversation(self, session: AsyncSession):
        """测试创建会话"""
        conv = Conversation(
            id=str(uuid.uuid4()),
            title="测试会话",
            created_at=_iso_now(),
            updated_at=_iso_now(),
            message_count=0,
        )
        session.add(conv)
        await session.commit()

        result = await session.execute(select(Conversation))
        saved = result.scalar_one()
        assert saved.title == "测试会话"
        assert saved.message_count == 0
        assert saved.context_summary is None


class TestMessageModel:
    """验证 Message 模型"""

    async def test_create_message_with_conversation(self, session: AsyncSession):
        """测试创建消息并关联会话"""
        conv_id = str(uuid.uuid4())
        conv = Conversation(
            id=conv_id,
            title="对话",
            created_at=_iso_now(),
            updated_at=_iso_now(),
            message_count=1,
        )
        msg = Message(
            id=str(uuid.uuid4()),
            conversation_id=conv_id,
            role="user",
            content="查询今日销售额",
            created_at=_iso_now(),
        )
        session.add(conv)
        session.add(msg)
        await session.commit()

        result = await session.execute(select(Message))
        saved_msg = result.scalar_one()
        assert saved_msg.role == "user"
        assert saved_msg.content == "查询今日销售额"
        assert saved_msg.sql is None
        assert saved_msg.query_result is None


class TestMetricModel:
    """验证 Metric 和 MetricParameter 模型"""

    async def test_create_metric_with_parameters(self, session: AsyncSession):
        """测试创建指标及其参数"""
        metric_id = str(uuid.uuid4())
        metric = Metric(
            id=metric_id,
            name="日销售额",
            description="查询指定日期的总销售额",
            sql_template="SELECT SUM(amount) FROM orders WHERE date = :date",
            created_at=_iso_now(),
            updated_at=_iso_now(),
        )
        param = MetricParameter(
            id=str(uuid.uuid4()),
            metric_id=metric_id,
            name="date",
            type="date",
            required=1,
            default_value=None,
            enum_values=None,
            sort_order=0,
        )
        session.add(metric)
        session.add(param)
        await session.commit()

        result = await session.execute(select(Metric))
        saved = result.scalar_one()
        assert saved.name == "日销售额"

        params_result = await session.execute(select(MetricParameter))
        saved_param = params_result.scalar_one()
        assert saved_param.name == "date"
        assert saved_param.type == "date"
        assert saved_param.required == 1


class TestSkillModel:
    """验证 Skill 和 SkillParameter 模型"""

    async def test_create_skill_with_parameters(self, session: AsyncSession):
        """测试创建技能及其参数"""
        skill_id = str(uuid.uuid4())
        skill = Skill(
            id=skill_id,
            name="销售趋势分析",
            description="分析指定时间段的销售趋势",
            content="skill content here",
            file_size=128,
            created_at=_iso_now(),
            updated_at=_iso_now(),
        )
        param = SkillParameter(
            id=str(uuid.uuid4()),
            skill_id=skill_id,
            name="start_date",
            type="date",
            required=1,
            constraint_desc="格式为 YYYY-MM-DD",
            sort_order=0,
        )
        session.add(skill)
        session.add(param)
        await session.commit()

        result = await session.execute(select(Skill))
        saved = result.scalar_one()
        assert saved.name == "销售趋势分析"
        assert saved.file_size == 128

        params_result = await session.execute(select(SkillParameter))
        saved_param = params_result.scalar_one()
        assert saved_param.name == "start_date"
        assert saved_param.constraint_desc == "格式为 YYYY-MM-DD"


class TestCascadeDelete:
    """验证级联删除行为"""

    async def test_delete_conversation_cascades_messages(self, session: AsyncSession):
        """删除会话时关联消息应被级联删除"""
        conv_id = str(uuid.uuid4())
        conv = Conversation(
            id=conv_id, title="待删除", created_at=_iso_now(), updated_at=_iso_now(), message_count=1
        )
        msg = Message(
            id=str(uuid.uuid4()), conversation_id=conv_id, role="user", content="hello", created_at=_iso_now()
        )
        session.add(conv)
        session.add(msg)
        await session.commit()

        await session.delete(conv)
        await session.commit()

        result = await session.execute(select(Message))
        assert result.scalars().all() == []
