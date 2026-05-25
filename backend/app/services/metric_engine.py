"""
指标引擎服务

管理预定义指标，提供语义匹配能力。
核心功能：
- 指标 CRUD（创建、更新、删除、列表、详情）
- 创建验证：名称≤64字符且唯一、说明≤512字符、参数≤20个
- 语义匹配：基于文本相似度（Jaccard / 关键词重叠）计算
- 参数提取：从用户查询中提取指标参数值
- 缺失参数检测：必填参数未提取且无默认值时返回缺失列表
"""

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, func, select

from app.core.config import settings
from app.models.database import Metric, MetricParameter, async_session_factory
from app.models.schemas import (
    MetricCreateInput,
    MetricMatchResult,
    MetricUpdateInput,
    PaginatedResult,
    PaginationParams,
)

logger = logging.getLogger(__name__)


# ============================================================
# 异常定义
# ============================================================


class MetricValidationError(Exception):
    """指标验证错误"""

    def __init__(self, message: str, field: Optional[str] = None):
        self.message = message
        self.field = field
        super().__init__(message)


class MetricNotFoundError(Exception):
    """指标未找到错误"""

    def __init__(self, metric_id: str):
        self.metric_id = metric_id
        super().__init__(f"Metric not found: {metric_id}")


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


def _tokenize(text: str) -> list[str]:
    """对文本进行分词处理

    支持中文字符逐字拆分和英文单词拆分，用于文本相似度计算。

    Args:
        text: 输入文本

    Returns:
        分词结果列表
    """
    tokens = []
    # 1.提取中文字符（逐字或双字组合）
    chinese_chars = re.findall(r'[\u4e00-\u9fa5]+', text)
    for segment in chinese_chars:
        # 使用 bigram 方式拆分中文
        if len(segment) >= 2:
            for i in range(len(segment) - 1):
                tokens.append(segment[i:i + 2])
        else:
            tokens.append(segment)
    # 2.提取英文单词（转小写）
    english_words = re.findall(r'[a-zA-Z]+', text)
    tokens.extend([w.lower() for w in english_words])
    # 3.提取数字
    numbers = re.findall(r'\d+', text)
    tokens.extend(numbers)
    return tokens


def _compute_similarity(query: str, target_name: str, target_desc: str) -> float:
    """计算用户查询与指标（名称+用途说明）的文本相似度

    使用 Jaccard 相似度结合 TF 加权的方式计算。
    名称匹配权重更高（0.6），说明匹配权重较低（0.4）。

    Args:
        query: 用户查询文本
        target_name: 指标名称
        target_desc: 指标用途说明

    Returns:
        相似度分数（0.0 ~ 1.0）
    """
    query_tokens = _tokenize(query)
    if not query_tokens:
        return 0.0

    # 1.计算与名称的相似度
    name_tokens = _tokenize(target_name)
    name_sim = _jaccard_similarity(query_tokens, name_tokens)

    # 2.计算与说明的相似度
    desc_tokens = _tokenize(target_desc)
    desc_sim = _jaccard_similarity(query_tokens, desc_tokens)

    # 3.加权合并（名称权重 0.6，说明权重 0.4）
    combined = name_sim * 0.6 + desc_sim * 0.4
    return combined


def _jaccard_similarity(tokens_a: list[str], tokens_b: list[str]) -> float:
    """计算两个 token 列表的 Jaccard 相似度

    Args:
        tokens_a: 第一个 token 列表
        tokens_b: 第二个 token 列表

    Returns:
        Jaccard 相似度（0.0 ~ 1.0）
    """
    if not tokens_a or not tokens_b:
        return 0.0

    set_a = set(tokens_a)
    set_b = set(tokens_b)
    intersection = set_a & set_b
    union = set_a | set_b

    if not union:
        return 0.0
    return len(intersection) / len(union)


# ============================================================
# MetricEngine 服务类
# ============================================================


class MetricEngine:
    """指标引擎

    负责指标的生命周期管理、语义匹配、参数提取和缺失参数检测。
    语义匹配使用文本相似度（Jaccard）作为主要方法，
    当 LLM API Key 配置时可选使用 LLM embedding 方式。
    """

    def __init__(self) -> None:
        """初始化指标引擎"""
        self._match_threshold: float = settings.metric_match_threshold
        self._llm_api_key: str = settings.llm_api_key
        logger.info(
            "MetricEngine initialized, match_threshold=%.2f, llm_available=%s",
            self._match_threshold, bool(self._llm_api_key),
        )

    # ============================================================
    # 指标 CRUD
    # ============================================================

    async def create_metric(self, input_data: MetricCreateInput) -> Metric:
        """创建指标

        验证规则：
        - 名称不超过64字符且系统内唯一
        - 用途说明不超过512字符
        - 参数数量不超过20个

        Args:
            input_data: 指标创建输入

        Returns:
            创建的指标 ORM 对象

        Raises:
            MetricValidationError: 验证失败时抛出
        """
        logger.info("Creating metric, name=%s", input_data.name)

        # 1.验证名称长度
        if len(input_data.name) > 64:
            raise MetricValidationError(
                "Metric name must not exceed 64 characters", field="name"
            )

        # 2.验证说明长度
        if len(input_data.description) > 512:
            raise MetricValidationError(
                "Metric description must not exceed 512 characters",
                field="description",
            )

        # 3.验证参数数量
        if len(input_data.parameters) > 20:
            raise MetricValidationError(
                "Metric parameters must not exceed 20",
                field="parameters",
            )

        # 4.验证名称唯一性
        async with async_session_factory() as session:
            existing = await session.execute(
                select(Metric).where(Metric.name == input_data.name)
            )
            if existing.scalar_one_or_none() is not None:
                raise MetricValidationError(
                    f"Metric name '{input_data.name}' already exists",
                    field="name",
                )

            # 5.创建指标记录
            metric_id = _generate_id()
            now = _iso_now()
            metric = Metric(
                id=metric_id,
                name=input_data.name,
                description=input_data.description,
                sql_template=input_data.sql_template,
                created_at=now,
                updated_at=now,
            )
            session.add(metric)

            # 6.创建参数记录
            for idx, param in enumerate(input_data.parameters):
                enum_values_str = None
                if param.enum_values:
                    enum_values_str = json.dumps(
                        param.enum_values, ensure_ascii=False
                    )
                param_record = MetricParameter(
                    id=_generate_id(),
                    metric_id=metric_id,
                    name=param.name,
                    type=param.type.value,
                    required=1 if param.required else 0,
                    default_value=str(param.default_value) if param.default_value is not None else None,
                    enum_values=enum_values_str,
                    sort_order=idx,
                )
                session.add(param_record)

            await session.commit()
            await session.refresh(metric)

        logger.info("Metric created successfully, id=%s, name=%s", metric_id, input_data.name)
        return metric

    async def update_metric(self, metric_id: str, input_data: MetricUpdateInput) -> Metric:
        """更新指标

        仅更新提供的字段，验证规则同创建。

        Args:
            metric_id: 指标ID
            input_data: 指标更新输入

        Returns:
            更新后的指标 ORM 对象

        Raises:
            MetricNotFoundError: 指标不存在时抛出
            MetricValidationError: 验证失败时抛出
        """
        logger.info("Updating metric, id=%s", metric_id)

        async with async_session_factory() as session:
            # 1.查找指标
            result = await session.execute(
                select(Metric).where(Metric.id == metric_id)
            )
            metric = result.scalar_one_or_none()
            if metric is None:
                raise MetricNotFoundError(metric_id)

            # 2.验证并更新名称
            if input_data.name is not None:
                if len(input_data.name) > 64:
                    raise MetricValidationError(
                        "Metric name must not exceed 64 characters",
                        field="name",
                    )
                # 检查唯一性（排除自身）
                existing = await session.execute(
                    select(Metric).where(
                        Metric.name == input_data.name,
                        Metric.id != metric_id,
                    )
                )
                if existing.scalar_one_or_none() is not None:
                    raise MetricValidationError(
                        f"Metric name '{input_data.name}' already exists",
                        field="name",
                    )
                metric.name = input_data.name

            # 3.验证并更新说明
            if input_data.description is not None:
                if len(input_data.description) > 512:
                    raise MetricValidationError(
                        "Metric description must not exceed 512 characters",
                        field="description",
                    )
                metric.description = input_data.description

            # 4.更新 SQL 模板
            if input_data.sql_template is not None:
                metric.sql_template = input_data.sql_template

            # 5.验证并更新参数
            if input_data.parameters is not None:
                if len(input_data.parameters) > 20:
                    raise MetricValidationError(
                        "Metric parameters must not exceed 20",
                        field="parameters",
                    )
                # 删除旧参数
                await session.execute(
                    delete(MetricParameter).where(
                        MetricParameter.metric_id == metric_id
                    )
                )
                # 创建新参数
                for idx, param in enumerate(input_data.parameters):
                    enum_values_str = None
                    if param.enum_values:
                        enum_values_str = json.dumps(
                            param.enum_values, ensure_ascii=False
                        )
                    param_record = MetricParameter(
                        id=_generate_id(),
                        metric_id=metric_id,
                        name=param.name,
                        type=param.type.value,
                        required=1 if param.required else 0,
                        default_value=str(param.default_value) if param.default_value is not None else None,
                        enum_values=enum_values_str,
                        sort_order=idx,
                    )
                    session.add(param_record)

            # 6.更新时间戳
            metric.updated_at = _iso_now()
            await session.commit()
            await session.refresh(metric)

        logger.info("Metric updated successfully, id=%s", metric_id)
        return metric

    async def delete_metric(self, metric_id: str) -> None:
        """删除指标及其所有参数

        Args:
            metric_id: 指标ID

        Raises:
            MetricNotFoundError: 指标不存在时抛出
        """
        logger.info("Deleting metric, id=%s", metric_id)

        async with async_session_factory() as session:
            # 1.检查指标是否存在
            result = await session.execute(
                select(Metric).where(Metric.id == metric_id)
            )
            metric = result.scalar_one_or_none()
            if metric is None:
                raise MetricNotFoundError(metric_id)

            # 2.删除关联参数（级联删除也会处理，但显式删除更清晰）
            await session.execute(
                delete(MetricParameter).where(
                    MetricParameter.metric_id == metric_id
                )
            )
            # 3.删除指标
            await session.execute(
                delete(Metric).where(Metric.id == metric_id)
            )
            await session.commit()

        logger.info("Metric deleted successfully, id=%s", metric_id)

    async def list_metrics(self, params: PaginationParams) -> PaginatedResult:
        """分页查询指标列表

        Args:
            params: 分页参数

        Returns:
            分页结果，包含指标列表和总数
        """
        page_size = params.page_size
        offset = (params.page - 1) * page_size
        logger.info("Listing metrics, page=%d, page_size=%d", params.page, page_size)

        async with async_session_factory() as session:
            # 1.查询总数
            count_stmt = select(func.count(Metric.id))
            total_result = await session.execute(count_stmt)
            total = total_result.scalar() or 0

            # 2.分页查询，按创建时间降序
            query_stmt = (
                select(Metric)
                .order_by(Metric.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
            result = await session.execute(query_stmt)
            metrics = result.scalars().all()

        logger.info("Listed metrics, total=%d, returned=%d", total, len(metrics))
        return PaginatedResult(
            items=metrics, total=total, page=params.page, pageSize=page_size
        )

    async def get_metric(self, metric_id: str) -> Optional[Metric]:
        """获取指标详情

        Args:
            metric_id: 指标ID

        Returns:
            指标 ORM 对象，不存在时返回 None
        """
        logger.info("Getting metric, id=%s", metric_id)

        async with async_session_factory() as session:
            result = await session.execute(
                select(Metric).where(Metric.id == metric_id)
            )
            metric = result.scalar_one_or_none()

        if metric is None:
            logger.warning("Metric not found, id=%s", metric_id)
        return metric

    # ============================================================
    # 语义匹配
    # ============================================================

    async def match_metric(
        self, query: str, threshold: Optional[float] = None
    ) -> Optional[MetricMatchResult]:
        """语义匹配指标

        基于用户查询与指标名称及用途说明进行文本相似度匹配。
        返回相似度最高且达到阈值的指标。

        Args:
            query: 用户查询文本
            threshold: 匹配阈值，为空时使用配置默认值

        Returns:
            匹配结果（包含最佳指标和候选列表），无匹配时返回 None
        """
        effective_threshold = threshold if threshold is not None else self._match_threshold
        logger.info(
            "Matching metric, query=%s, threshold=%.2f",
            query[:50], effective_threshold,
        )

        # 1.获取所有指标
        async with async_session_factory() as session:
            result = await session.execute(select(Metric))
            metrics = result.scalars().all()

        if not metrics:
            logger.info("No metrics available for matching")
            return None

        # 2.计算每个指标的相似度
        candidates = []
        for metric in metrics:
            similarity = _compute_similarity(
                query, metric.name, metric.description
            )
            if similarity >= effective_threshold:
                candidates.append({"metric": metric, "similarity": similarity})

        if not candidates:
            logger.info("No metric matched above threshold %.2f", effective_threshold)
            return None

        # 3.按相似度降序排列，取最高的作为匹配结果
        candidates.sort(key=lambda x: x["similarity"], reverse=True)
        best = candidates[0]

        logger.info(
            "Metric matched, best=%s, similarity=%.4f, candidates_count=%d",
            best["metric"].name, best["similarity"], len(candidates),
        )

        return MetricMatchResult(
            metric=best["metric"],
            similarity=best["similarity"],
            candidates=candidates,
        )

    # ============================================================
    # 参数提取
    # ============================================================

    async def extract_parameters(self, query: str, metric: Metric) -> dict:
        """从用户查询中提取指标参数值

        基于参数名称和类型，使用正则匹配从查询文本中提取参数值。
        支持日期、数字、枚举和字符串类型的参数提取。

        Args:
            query: 用户查询文本
            metric: 指标 ORM 对象（需包含 parameters 关系）

        Returns:
            提取到的参数值字典 {参数名: 参数值}
        """
        logger.info(
            "Extracting parameters, query=%s, metric=%s",
            query[:50], metric.name,
        )

        extracted = {}

        # 1.获取指标参数定义
        async with async_session_factory() as session:
            result = await session.execute(
                select(MetricParameter)
                .where(MetricParameter.metric_id == metric.id)
                .order_by(MetricParameter.sort_order)
            )
            parameters = result.scalars().all()

        # 2.逐个参数尝试提取
        for param in parameters:
            value = self._extract_single_parameter(query, param)
            if value is not None:
                extracted[param.name] = value

        logger.info(
            "Parameters extracted, metric=%s, extracted_count=%d, total_params=%d",
            metric.name, len(extracted), len(parameters),
        )
        return extracted

    def _extract_single_parameter(
        self, query: str, param: MetricParameter
    ) -> Optional[str]:
        """从查询文本中提取单个参数值

        根据参数类型使用不同的提取策略：
        - date: 匹配日期格式（YYYY-MM-DD、YYYY/MM/DD 等）
        - number: 匹配数字
        - enum: 匹配枚举值列表中的值
        - string: 匹配参数名称后的文本

        Args:
            query: 用户查询文本
            param: 参数定义

        Returns:
            提取到的参数值，未提取到返回 None
        """
        param_type = param.type

        # 1.日期类型提取
        if param_type == "date":
            date_patterns = [
                r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
                r'(\d{4}年\d{1,2}月\d{1,2}日)',
            ]
            for pattern in date_patterns:
                match = re.search(pattern, query)
                if match:
                    return match.group(1)

        # 2.枚举类型提取
        elif param_type == "enum":
            if param.enum_values:
                try:
                    enum_list = json.loads(param.enum_values)
                    for enum_val in enum_list:
                        if enum_val in query:
                            return enum_val
                except (json.JSONDecodeError, TypeError):
                    pass

        # 3.数字类型提取
        elif param_type == "number":
            # 尝试匹配参数名称附近的数字
            param_name_pattern = re.escape(param.name)
            # 匹配 "参数名 数字" 或 "参数名:数字" 或 "参数名=数字"
            patterns = [
                rf'{param_name_pattern}\s*[:=：]\s*(\d+(?:\.\d+)?)',
                rf'{param_name_pattern}\s+(\d+(?:\.\d+)?)',
            ]
            for pattern in patterns:
                match = re.search(pattern, query, re.IGNORECASE)
                if match:
                    return match.group(1)
            # 回退：匹配查询中的第一个数字
            number_match = re.search(r'(\d+(?:\.\d+)?)', query)
            if number_match:
                return number_match.group(1)

        # 4.字符串类型提取
        elif param_type == "string":
            # 尝试匹配参数名称后的内容
            param_name_pattern = re.escape(param.name)
            patterns = [
                rf'{param_name_pattern}\s*[:=：]\s*["\']?([^"\'\s,，]+)',
                rf'{param_name_pattern}\s+["\']?([^"\'\s,，]+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, query, re.IGNORECASE)
                if match:
                    return match.group(1)

        return None

    # ============================================================
    # 缺失参数检测
    # ============================================================

    async def detect_missing_parameters(
        self, metric: Metric, extracted_params: dict
    ) -> list[str]:
        """检测缺失的必填参数

        必填参数未从用户查询中提取到且未配置默认值时，视为缺失。

        Args:
            metric: 指标 ORM 对象
            extracted_params: 已提取的参数值字典

        Returns:
            缺失的必填参数名称列表
        """
        logger.info(
            "Detecting missing parameters, metric=%s, extracted_count=%d",
            metric.name, len(extracted_params),
        )

        # 1.获取指标参数定义
        async with async_session_factory() as session:
            result = await session.execute(
                select(MetricParameter)
                .where(MetricParameter.metric_id == metric.id)
                .order_by(MetricParameter.sort_order)
            )
            parameters = result.scalars().all()

        # 2.检查每个必填参数
        missing = []
        for param in parameters:
            # 仅检查必填参数（required == 1）
            if param.required != 1:
                continue
            # 已提取到值则跳过
            if param.name in extracted_params:
                continue
            # 有默认值则跳过
            if param.default_value is not None:
                continue
            # 标记为缺失
            missing.append(param.name)

        logger.info(
            "Missing parameters detected, metric=%s, missing=%s",
            metric.name, missing,
        )
        return missing


# ============================================================
# 全局单例
# ============================================================

metric_engine = MetricEngine()
