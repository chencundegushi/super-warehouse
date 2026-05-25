"""
Metric Engine 单元测试

验证指标 CRUD、创建验证、语义匹配、参数提取和缺失参数检测功能。
使用内存数据库隔离测试环境。
"""

import json
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.database import Base, Metric, MetricParameter
from app.models.schemas import (
    MetricCreateInput,
    MetricParameter as MetricParameterSchema,
    MetricParameterType,
    MetricUpdateInput,
    PaginationParams,
)
from app.services.metric_engine import (
    MetricEngine,
    MetricNotFoundError,
    MetricValidationError,
    _compute_similarity,
    _jaccard_similarity,
    _tokenize,
)


@pytest.fixture
async def test_engine():
    """创建内存数据库引擎用于测试"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def test_session_factory(test_engine):
    """创建测试用会话工厂"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    return factory


@pytest.fixture
async def engine_instance(test_session_factory):
    """创建使用测试数据库的 MetricEngine 实例"""
    eng = MetricEngine()
    with patch(
        "app.services.metric_engine.async_session_factory",
        test_session_factory,
    ):
        yield eng


# ============================================================
# 辅助函数测试
# ============================================================


class TestTokenize:
    """验证分词函数"""

    def test_tokenize_chinese(self):
        """测试中文 bigram 分词"""
        tokens = _tokenize("销售额")
        assert "销售" in tokens
        assert "售额" in tokens

    def test_tokenize_english(self):
        """测试英文单词分词（转小写）"""
        tokens = _tokenize("Hello World")
        assert "hello" in tokens
        assert "world" in tokens

    def test_tokenize_numbers(self):
        """测试数字提取"""
        tokens = _tokenize("2024年销售额100万")
        assert "2024" in tokens
        assert "100" in tokens

    def test_tokenize_mixed(self):
        """测试中英文混合分词"""
        tokens = _tokenize("查询order表的销售额")
        assert "order" in tokens
        assert "销售" in tokens

    def test_tokenize_empty(self):
        """测试空字符串"""
        tokens = _tokenize("")
        assert tokens == []


class TestJaccardSimilarity:
    """验证 Jaccard 相似度计算"""

    def test_identical_tokens(self):
        """测试完全相同的 token 列表"""
        sim = _jaccard_similarity(["a", "b", "c"], ["a", "b", "c"])
        assert sim == 1.0

    def test_no_overlap(self):
        """测试完全不重叠的 token 列表"""
        sim = _jaccard_similarity(["a", "b"], ["c", "d"])
        assert sim == 0.0

    def test_partial_overlap(self):
        """测试部分重叠"""
        sim = _jaccard_similarity(["a", "b", "c"], ["b", "c", "d"])
        # 交集 {b, c} = 2, 并集 {a, b, c, d} = 4, 相似度 = 0.5
        assert sim == 0.5

    def test_empty_list(self):
        """测试空列表"""
        assert _jaccard_similarity([], ["a"]) == 0.0
        assert _jaccard_similarity(["a"], []) == 0.0
        assert _jaccard_similarity([], []) == 0.0


class TestComputeSimilarity:
    """验证综合相似度计算"""

    def test_exact_name_match(self):
        """测试名称完全匹配时相似度较高"""
        sim = _compute_similarity("销售额", "销售额", "统计每日销售总额")
        assert sim > 0.5

    def test_no_match(self):
        """测试完全不相关时相似度为0"""
        sim = _compute_similarity("天气预报", "销售额", "统计每日销售总额")
        assert sim == 0.0

    def test_partial_match(self):
        """测试部分匹配"""
        sim = _compute_similarity("查询销售额", "销售额", "统计每日销售总额")
        assert sim > 0.0


# ============================================================
# 指标 CRUD 测试
# ============================================================


class TestCreateMetric:
    """验证指标创建功能"""

    async def test_create_metric_success(self, engine_instance, test_session_factory):
        """测试正常创建指标"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            input_data = MetricCreateInput(
                name="日销售额",
                description="统计每日销售总额",
                sqlTemplate="SELECT SUM(amount) FROM orders WHERE date = :date",
                parameters=[
                    MetricParameterSchema(
                        name="date",
                        type=MetricParameterType.date,
                        required=True,
                    )
                ],
            )
            metric = await engine_instance.create_metric(input_data)
            assert metric.name == "日销售额"
            assert metric.description == "统计每日销售总额"
            assert metric.id is not None

    async def test_create_metric_name_too_long(self, engine_instance, test_session_factory):
        """测试名称超过64字符时拒绝创建（Pydantic 层验证）"""
        from pydantic import ValidationError

        long_name = "a" * 65
        with pytest.raises(ValidationError) as exc_info:
            MetricCreateInput(
                name=long_name,
                description="desc",
                sqlTemplate="SELECT 1",
                parameters=[],
            )
        assert "string_too_long" in str(exc_info.value)

    async def test_create_metric_description_too_long(
        self, engine_instance, test_session_factory
    ):
        """测试说明超过512字符时拒绝创建（Pydantic 层验证）"""
        from pydantic import ValidationError

        long_desc = "d" * 513
        with pytest.raises(ValidationError) as exc_info:
            MetricCreateInput(
                name="valid_name",
                description=long_desc,
                sqlTemplate="SELECT 1",
                parameters=[],
            )
        assert "string_too_long" in str(exc_info.value)

    async def test_create_metric_too_many_parameters(
        self, engine_instance, test_session_factory
    ):
        """测试参数超过20个时拒绝创建（Pydantic 层验证）"""
        from pydantic import ValidationError

        params = [
            MetricParameterSchema(
                name=f"param_{i}",
                type=MetricParameterType.string,
                required=False,
            )
            for i in range(21)
        ]
        with pytest.raises(ValidationError) as exc_info:
            MetricCreateInput(
                name="too_many_params",
                description="desc",
                sqlTemplate="SELECT 1",
                parameters=params,
            )
        assert "too_long" in str(exc_info.value)

    async def test_create_metric_duplicate_name(
        self, engine_instance, test_session_factory
    ):
        """测试名称重复时拒绝创建"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            input_data = MetricCreateInput(
                name="唯一指标",
                description="desc",
                sqlTemplate="SELECT 1",
                parameters=[],
            )
            await engine_instance.create_metric(input_data)

            # 尝试创建同名指标
            with pytest.raises(MetricValidationError) as exc_info:
                await engine_instance.create_metric(input_data)
            assert "already exists" in exc_info.value.message


class TestUpdateMetric:
    """验证指标更新功能"""

    async def test_update_metric_name(self, engine_instance, test_session_factory):
        """测试更新指标名称"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            input_data = MetricCreateInput(
                name="原始名称",
                description="desc",
                sqlTemplate="SELECT 1",
                parameters=[],
            )
            metric = await engine_instance.create_metric(input_data)

            update_data = MetricUpdateInput(name="新名称")
            updated = await engine_instance.update_metric(metric.id, update_data)
            assert updated.name == "新名称"

    async def test_update_metric_not_found(self, engine_instance, test_session_factory):
        """测试更新不存在的指标"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            update_data = MetricUpdateInput(name="new")
            with pytest.raises(MetricNotFoundError):
                await engine_instance.update_metric("non-existent", update_data)

    async def test_update_metric_name_conflict(
        self, engine_instance, test_session_factory
    ):
        """测试更新名称与其他指标冲突"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            # 创建两个指标
            m1 = await engine_instance.create_metric(
                MetricCreateInput(
                    name="指标A", description="d", sqlTemplate="S", parameters=[]
                )
            )
            await engine_instance.create_metric(
                MetricCreateInput(
                    name="指标B", description="d", sqlTemplate="S", parameters=[]
                )
            )

            # 尝试将 A 改名为 B
            with pytest.raises(MetricValidationError) as exc_info:
                await engine_instance.update_metric(
                    m1.id, MetricUpdateInput(name="指标B")
                )
            assert "already exists" in exc_info.value.message


class TestDeleteMetric:
    """验证指标删除功能"""

    async def test_delete_metric_success(self, engine_instance, test_session_factory):
        """测试正常删除指标"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            metric = await engine_instance.create_metric(
                MetricCreateInput(
                    name="待删除", description="d", sqlTemplate="S", parameters=[]
                )
            )
            await engine_instance.delete_metric(metric.id)
            result = await engine_instance.get_metric(metric.id)
            assert result is None

    async def test_delete_metric_not_found(self, engine_instance, test_session_factory):
        """测试删除不存在的指标"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            with pytest.raises(MetricNotFoundError):
                await engine_instance.delete_metric("non-existent")


class TestListAndGetMetric:
    """验证指标列表和详情查询"""

    async def test_list_metrics_pagination(self, engine_instance, test_session_factory):
        """测试分页查询指标列表"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            for i in range(5):
                await engine_instance.create_metric(
                    MetricCreateInput(
                        name=f"指标{i}",
                        description=f"desc{i}",
                        sqlTemplate="SELECT 1",
                        parameters=[],
                    )
                )

            params = PaginationParams(page=1, pageSize=3)
            result = await engine_instance.list_metrics(params)
            assert result.total == 5
            assert len(result.items) == 3

    async def test_get_metric_success(self, engine_instance, test_session_factory):
        """测试获取指标详情"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            metric = await engine_instance.create_metric(
                MetricCreateInput(
                    name="详情测试", description="d", sqlTemplate="S", parameters=[]
                )
            )
            fetched = await engine_instance.get_metric(metric.id)
            assert fetched is not None
            assert fetched.name == "详情测试"

    async def test_get_metric_not_found(self, engine_instance, test_session_factory):
        """测试获取不存在的指标返回 None"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            result = await engine_instance.get_metric("non-existent")
            assert result is None


# ============================================================
# 语义匹配测试
# ============================================================


class TestMatchMetric:
    """验证语义匹配功能"""

    async def test_match_metric_success(self, engine_instance, test_session_factory):
        """测试成功匹配指标"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            await engine_instance.create_metric(
                MetricCreateInput(
                    name="日销售额",
                    description="统计每日销售总额",
                    sqlTemplate="SELECT SUM(amount) FROM orders",
                    parameters=[],
                )
            )
            # 使用低阈值确保匹配
            result = await engine_instance.match_metric("查询日销售额", threshold=0.1)
            assert result is not None
            assert result.metric.name == "日销售额"
            assert result.similarity > 0.0

    async def test_match_metric_no_match(self, engine_instance, test_session_factory):
        """测试无指标达到阈值时返回 None"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            await engine_instance.create_metric(
                MetricCreateInput(
                    name="日销售额",
                    description="统计每日销售总额",
                    sqlTemplate="SELECT 1",
                    parameters=[],
                )
            )
            # 使用高阈值确保不匹配
            result = await engine_instance.match_metric("天气预报", threshold=0.9)
            assert result is None

    async def test_match_metric_empty_db(self, engine_instance, test_session_factory):
        """测试数据库无指标时返回 None"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            result = await engine_instance.match_metric("任意查询")
            assert result is None

    async def test_match_metric_returns_best(self, engine_instance, test_session_factory):
        """测试返回相似度最高的指标"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            await engine_instance.create_metric(
                MetricCreateInput(
                    name="月销售额",
                    description="统计每月销售总额",
                    sqlTemplate="SELECT 1",
                    parameters=[],
                )
            )
            await engine_instance.create_metric(
                MetricCreateInput(
                    name="日销售额",
                    description="统计每日销售总额",
                    sqlTemplate="SELECT 1",
                    parameters=[],
                )
            )
            result = await engine_instance.match_metric("查询日销售额", threshold=0.1)
            assert result is not None
            # 日销售额应该比月销售额更匹配
            assert result.metric.name == "日销售额"


# ============================================================
# 参数提取测试
# ============================================================


class TestExtractParameters:
    """验证参数提取功能"""

    async def test_extract_date_parameter(self, engine_instance, test_session_factory):
        """测试提取日期类型参数"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            metric = await engine_instance.create_metric(
                MetricCreateInput(
                    name="日销售额",
                    description="desc",
                    sqlTemplate="SELECT SUM(amount) FROM orders WHERE date = :date",
                    parameters=[
                        MetricParameterSchema(
                            name="date",
                            type=MetricParameterType.date,
                            required=True,
                        )
                    ],
                )
            )
            extracted = await engine_instance.extract_parameters(
                "查询2024-01-15的销售额", metric
            )
            assert "date" in extracted
            assert "2024-01-15" in extracted["date"]

    async def test_extract_enum_parameter(self, engine_instance, test_session_factory):
        """测试提取枚举类型参数"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            metric = await engine_instance.create_metric(
                MetricCreateInput(
                    name="分类销售额",
                    description="desc",
                    sqlTemplate="SELECT SUM(amount) FROM orders WHERE category = :category",
                    parameters=[
                        MetricParameterSchema(
                            name="category",
                            type=MetricParameterType.enum,
                            required=True,
                            enumValues=["电子产品", "服装", "食品"],
                        )
                    ],
                )
            )
            extracted = await engine_instance.extract_parameters(
                "查询电子产品的销售额", metric
            )
            assert "category" in extracted
            assert extracted["category"] == "电子产品"

    async def test_extract_number_parameter(self, engine_instance, test_session_factory):
        """测试提取数字类型参数"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            metric = await engine_instance.create_metric(
                MetricCreateInput(
                    name="Top销售",
                    description="desc",
                    sqlTemplate="SELECT * FROM orders LIMIT :limit",
                    parameters=[
                        MetricParameterSchema(
                            name="limit",
                            type=MetricParameterType.number,
                            required=True,
                        )
                    ],
                )
            )
            extracted = await engine_instance.extract_parameters(
                "查询前10名销售", metric
            )
            assert "limit" in extracted
            assert extracted["limit"] == "10"


# ============================================================
# 缺失参数检测测试
# ============================================================


class TestDetectMissingParameters:
    """验证缺失参数检测功能"""

    async def test_detect_missing_required_param(
        self, engine_instance, test_session_factory
    ):
        """测试检测缺失的必填参数"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            metric = await engine_instance.create_metric(
                MetricCreateInput(
                    name="测试指标",
                    description="desc",
                    sqlTemplate="SELECT 1",
                    parameters=[
                        MetricParameterSchema(
                            name="start_date",
                            type=MetricParameterType.date,
                            required=True,
                        ),
                        MetricParameterSchema(
                            name="end_date",
                            type=MetricParameterType.date,
                            required=True,
                        ),
                    ],
                )
            )
            # 只提取到 start_date
            missing = await engine_instance.detect_missing_parameters(
                metric, {"start_date": "2024-01-01"}
            )
            assert "end_date" in missing
            assert "start_date" not in missing

    async def test_no_missing_when_all_provided(
        self, engine_instance, test_session_factory
    ):
        """测试所有必填参数都已提取时返回空列表"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            metric = await engine_instance.create_metric(
                MetricCreateInput(
                    name="完整参数",
                    description="desc",
                    sqlTemplate="SELECT 1",
                    parameters=[
                        MetricParameterSchema(
                            name="date",
                            type=MetricParameterType.date,
                            required=True,
                        ),
                    ],
                )
            )
            missing = await engine_instance.detect_missing_parameters(
                metric, {"date": "2024-01-01"}
            )
            assert missing == []

    async def test_no_missing_when_has_default(
        self, engine_instance, test_session_factory
    ):
        """测试必填参数有默认值时不视为缺失"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            metric = await engine_instance.create_metric(
                MetricCreateInput(
                    name="默认值测试",
                    description="desc",
                    sqlTemplate="SELECT 1",
                    parameters=[
                        MetricParameterSchema(
                            name="limit",
                            type=MetricParameterType.number,
                            required=True,
                            defaultValue="10",
                        ),
                    ],
                )
            )
            missing = await engine_instance.detect_missing_parameters(metric, {})
            assert missing == []

    async def test_optional_param_not_missing(
        self, engine_instance, test_session_factory
    ):
        """测试非必填参数不视为缺失"""
        with patch(
            "app.services.metric_engine.async_session_factory",
            test_session_factory,
        ):
            metric = await engine_instance.create_metric(
                MetricCreateInput(
                    name="可选参数",
                    description="desc",
                    sqlTemplate="SELECT 1",
                    parameters=[
                        MetricParameterSchema(
                            name="optional_field",
                            type=MetricParameterType.string,
                            required=False,
                        ),
                    ],
                )
            )
            missing = await engine_instance.detect_missing_parameters(metric, {})
            assert missing == []
