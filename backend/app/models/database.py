"""
SQLite 数据库层

配置 SQLAlchemy 异步引擎和会话工厂，定义 ORM 模型，
提供数据库初始化函数自动建表。

ORM 模型包括：
- Conversation: 会话
- Message: 消息
- Metric: 指标
- MetricParameter: 指标参数
- Skill: 技能
- SkillParameter: 技能参数
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    Text,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship

from app.core.config import settings

logger = logging.getLogger(__name__)


# 1.创建异步引擎
engine = create_async_engine(
    settings.sqlite_url,
    echo=settings.debug,
    future=True,
)

# 2.创建异步会话工厂
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# 3.启用 SQLite 外键约束（同步事件监听）
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """启用 SQLite 外键约束支持"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _iso_now() -> str:
    """生成当前时间的 ISO 8601 格式字符串（UTC）

    Returns:
        ISO 8601 格式的时间字符串
    """
    return datetime.now(timezone.utc).isoformat()


# 4.声明基类
class Base(DeclarativeBase):
    """SQLAlchemy ORM 声明基类"""
    pass


# ============================================================
# ORM 模型定义
# ============================================================


class Conversation(Base):
    """会话模型

    存储用户与 Agent 的对话会话信息，包含标题、时间戳和上下文摘要。
    """

    __tablename__ = "conversations"

    id = Column(Text, primary_key=True, comment="会话唯一标识（UUID字符串）")
    title = Column(Text, nullable=False, comment="会话标题")
    created_at = Column(Text, nullable=False, default=_iso_now, comment="创建时间（ISO 8601）")
    updated_at = Column(Text, nullable=False, default=_iso_now, onupdate=_iso_now, comment="最后活跃时间（ISO 8601）")
    context_summary = Column(Text, nullable=True, comment="上下文摘要（超出窗口时生成）")
    message_count = Column(Integer, nullable=False, default=0, comment="消息总数")

    # 关联关系
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id!r}, title={self.title!r})>"


class Message(Base):
    """消息模型

    存储会话中的每条消息，包括角色、内容、关联SQL和查询结果。
    """

    __tablename__ = "messages"

    id = Column(Text, primary_key=True, comment="消息唯一标识（UUID字符串）")
    conversation_id = Column(
        Text,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属会话ID",
    )
    role = Column(Text, nullable=False, comment="消息角色（user/agent）")
    content = Column(Text, nullable=False, comment="消息文本内容")
    sql = Column(Text, nullable=True, comment="关联的SQL语句")
    query_result = Column(Text, nullable=True, comment="查询结果（JSON字符串）")
    created_at = Column(Text, nullable=False, default=_iso_now, comment="创建时间（ISO 8601）")

    # 关联关系
    conversation = relationship("Conversation", back_populates="messages")

    def __repr__(self) -> str:
        return f"<Message(id={self.id!r}, role={self.role!r})>"


class Metric(Base):
    """指标模型

    存储预定义的业务指标，包含名称、用途说明和SQL模板。
    指标名称系统内唯一，最长64字符；用途说明最长512字符。
    """

    __tablename__ = "metrics"

    id = Column(Text, primary_key=True, comment="指标唯一标识（UUID字符串）")
    name = Column(Text, unique=True, nullable=False, comment="指标名称（最长64字符，唯一）")
    description = Column(Text, nullable=False, comment="用途说明（最长512字符）")
    sql_template = Column(Text, nullable=False, comment="SQL模板")
    created_at = Column(Text, nullable=False, default=_iso_now, comment="创建时间（ISO 8601）")
    updated_at = Column(Text, nullable=False, default=_iso_now, onupdate=_iso_now, comment="更新时间（ISO 8601）")

    # 关联关系
    parameters = relationship("MetricParameter", back_populates="metric", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Metric(id={self.id!r}, name={self.name!r})>"


class MetricParameter(Base):
    """指标参数模型

    定义指标SQL模板中的参数，包括名称、类型、是否必填、默认值和枚举值。
    每个指标最多支持20个参数。
    """

    __tablename__ = "metric_parameters"

    id = Column(Text, primary_key=True, comment="参数唯一标识（UUID字符串）")
    metric_id = Column(
        Text,
        ForeignKey("metrics.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属指标ID",
    )
    name = Column(Text, nullable=False, comment="参数名称")
    type = Column(Text, nullable=False, comment="参数类型（string/number/date/enum）")
    required = Column(Integer, nullable=False, default=1, comment="是否必填（0/1）")
    default_value = Column(Text, nullable=True, comment="默认值")
    enum_values = Column(Text, nullable=True, comment="枚举可选值列表（JSON字符串）")
    sort_order = Column(Integer, nullable=False, comment="排序序号")

    # 关联关系
    metric = relationship("Metric", back_populates="parameters")

    def __repr__(self) -> str:
        return f"<MetricParameter(id={self.id!r}, name={self.name!r})>"


class Skill(Base):
    """技能模型

    存储导入的分析技能，格式与 Claude Code skill 一致。
    技能名称最长128字符，内容不超过1MB。
    """

    __tablename__ = "skills"

    id = Column(Text, primary_key=True, comment="技能唯一标识（UUID字符串）")
    name = Column(Text, nullable=False, comment="技能名称（最长128字符）")
    description = Column(Text, nullable=True, comment="技能描述")
    content = Column(Text, nullable=False, comment="技能文件内容（≤1MB）")
    file_size = Column(Integer, nullable=False, comment="文件大小（字节）")
    created_at = Column(Text, nullable=False, default=_iso_now, comment="创建时间（ISO 8601）")
    updated_at = Column(Text, nullable=False, default=_iso_now, onupdate=_iso_now, comment="更新时间（ISO 8601）")

    # 关联关系
    parameters = relationship("SkillParameter", back_populates="skill", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Skill(id={self.id!r}, name={self.name!r})>"


class SkillParameter(Base):
    """技能参数模型

    定义技能执行所需的参数，包括名称、类型、是否必填和约束描述。
    """

    __tablename__ = "skill_parameters"

    id = Column(Text, primary_key=True, comment="参数唯一标识（UUID字符串）")
    skill_id = Column(
        Text,
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属技能ID",
    )
    name = Column(Text, nullable=False, comment="参数名称")
    type = Column(Text, nullable=False, comment="参数类型")
    required = Column(Integer, nullable=False, comment="是否必填（0/1）")
    constraint_desc = Column(Text, nullable=True, comment="约束描述")
    sort_order = Column(Integer, nullable=False, comment="排序序号")

    # 关联关系
    skill = relationship("Skill", back_populates="parameters")

    def __repr__(self) -> str:
        return f"<SkillParameter(id={self.id!r}, name={self.name!r})>"


# ============================================================
# 数据库初始化与会话管理
# ============================================================


async def init_db() -> None:
    """初始化数据库，自动创建所有表

    使用 SQLAlchemy 异步引擎执行 DDL，根据 ORM 模型定义创建表结构。
    如果表已存在则跳过创建。
    """
    logger.info("Initializing database, url=%s", settings.sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialization completed, tables created successfully")


async def get_session() -> AsyncSession:
    """获取异步数据库会话（用于依赖注入）

    Returns:
        异步数据库会话实例
    """
    async with async_session_factory() as session:
        yield session


async def close_db() -> None:
    """关闭数据库引擎，释放连接池资源"""
    logger.info("Closing database engine")
    await engine.dispose()
    logger.info("Database engine closed")
