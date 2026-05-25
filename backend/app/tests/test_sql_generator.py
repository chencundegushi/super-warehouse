"""
SQL 生成器单元测试

测试 SQL 引用验证、表名提取、列名提取、LLM 响应解析等核心功能。
LLM 调用使用 Mock 替代。
"""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from app.models.schemas import ColumnDefinition, DDLInfo, SQLGenParams, SQLGenResult
from app.services.sql_generator import SQLGenerator, SQLGeneratorError, LLMCallError

logger = logging.getLogger(__name__)


# ============================================================
# 测试辅助工具
# ============================================================

def make_ddl_info(
    database: str,
    table_name: str,
    columns: list[dict],
    ddl_content: str = "",
) -> DDLInfo:
    """构建测试用 DDLInfo 对象"""
    col_defs = [
        ColumnDefinition(
            name=c["name"],
            type=c.get("type", "VARCHAR(255)"),
            nullable=c.get("nullable", True),
            comment=c.get("comment"),
            is_primary_key=c.get("is_primary_key", False),
        )
        for c in columns
    ]
    return DDLInfo(
        id=f"{database}.{table_name}",
        database=database,
        table_name=table_name,
        ddl_content=ddl_content or f"CREATE TABLE `{table_name}` (...)",
        columns=col_defs,
        field_count=len(col_defs),
        loaded_at="2024-01-01T00:00:00",
    )


@pytest.fixture
def sample_ddl_context():
    """示例 DDL 上下文：订单系统"""
    return [
        make_ddl_info(
            database="warehouse",
            table_name="orders",
            columns=[
                {"name": "order_id", "type": "BIGINT", "is_primary_key": True},
                {"name": "user_id", "type": "BIGINT"},
                {"name": "amount", "type": "DECIMAL(10,2)"},
                {"name": "status", "type": "VARCHAR(32)"},
                {"name": "created_at", "type": "DATETIME"},
            ],
        ),
        make_ddl_info(
            database="warehouse",
            table_name="users",
            columns=[
                {"name": "user_id", "type": "BIGINT", "is_primary_key": True},
                {"name": "username", "type": "VARCHAR(64)"},
                {"name": "email", "type": "VARCHAR(128)"},
                {"name": "region", "type": "VARCHAR(32)"},
            ],
        ),
        make_ddl_info(
            database="warehouse",
            table_name="products",
            columns=[
                {"name": "product_id", "type": "BIGINT", "is_primary_key": True},
                {"name": "product_name", "type": "VARCHAR(128)"},
                {"name": "category", "type": "VARCHAR(64)"},
                {"name": "price", "type": "DECIMAL(10,2)"},
            ],
        ),
    ]


@pytest.fixture
def sql_generator():
    """创建 SQL 生成器实例（Mock OpenAI 客户端）"""
    with patch("app.services.sql_generator.OpenAI") as mock_openai:
        generator = SQLGenerator(
            api_key="test-key",
            base_url="http://localhost:8080/v1",
            model="test-model",
            temperature=0.0,
            max_tokens=2048,
        )
        yield generator


# ============================================================
# SQL 引用验证测试
# ============================================================

class TestValidateSqlReferences:
    """SQL 引用验证测试"""

    def test_valid_single_table_query(self, sql_generator, sample_ddl_context):
        """验证单表查询中所有引用均有效"""
        sql = "SELECT order_id, amount, status FROM orders WHERE status = 'paid'"
        is_valid, errors = sql_generator.validate_sql_references(sql, sample_ddl_context)
        assert is_valid is True
        assert errors == []

    def test_valid_join_query(self, sql_generator, sample_ddl_context):
        """验证多表 JOIN 查询中所有引用均有效"""
        sql = (
            "SELECT o.order_id, u.username, o.amount "
            "FROM orders o "
            "JOIN users u ON o.user_id = u.user_id "
            "WHERE o.status = 'paid'"
        )
        is_valid, errors = sql_generator.validate_sql_references(sql, sample_ddl_context)
        assert is_valid is True
        assert errors == []

    def test_invalid_table_reference(self, sql_generator, sample_ddl_context):
        """验证引用不存在的表时返回错误"""
        sql = "SELECT * FROM non_existent_table WHERE id = 1"
        is_valid, errors = sql_generator.validate_sql_references(sql, sample_ddl_context)
        assert is_valid is False
        assert any("non_existent_table" in e for e in errors)

    def test_invalid_column_reference(self, sql_generator, sample_ddl_context):
        """验证引用不存在的列时返回错误（qualified 格式）"""
        sql = "SELECT orders.order_id, orders.non_existent_col FROM orders"
        is_valid, errors = sql_generator.validate_sql_references(sql, sample_ddl_context)
        assert is_valid is False
        assert any("non_existent_col" in e for e in errors)

    def test_qualified_column_invalid(self, sql_generator, sample_ddl_context):
        """验证 table.column 格式中列不存在时返回错误"""
        sql = "SELECT orders.fake_column FROM orders"
        is_valid, errors = sql_generator.validate_sql_references(sql, sample_ddl_context)
        assert is_valid is False
        assert any("fake_column" in e for e in errors)

    def test_empty_ddl_context(self, sql_generator):
        """验证空 DDL 上下文时所有引用均无效"""
        sql = "SELECT id FROM some_table"
        is_valid, errors = sql_generator.validate_sql_references(sql, [])
        assert is_valid is False

    def test_multiple_join_tables(self, sql_generator, sample_ddl_context):
        """验证多表 JOIN 中所有表名均被正确提取和验证"""
        sql = (
            "SELECT o.order_id, u.username, p.product_name "
            "FROM orders o "
            "LEFT JOIN users u ON o.user_id = u.user_id "
            "INNER JOIN products p ON o.order_id = p.product_id"
        )
        is_valid, errors = sql_generator.validate_sql_references(sql, sample_ddl_context)
        assert is_valid is True
        assert errors == []


# ============================================================
# 表名提取测试
# ============================================================

class TestExtractTableReferences:
    """表名提取测试"""

    def test_simple_from(self, sql_generator):
        """从简单 FROM 子句提取表名"""
        sql = "SELECT * FROM orders"
        tables = sql_generator._extract_table_references(sql)
        assert "orders" in tables

    def test_from_with_alias(self, sql_generator):
        """从带别名的 FROM 子句提取表名"""
        sql = "SELECT * FROM orders o"
        tables = sql_generator._extract_table_references(sql)
        assert "orders" in tables

    def test_join_tables(self, sql_generator):
        """从 JOIN 子句提取表名"""
        sql = "SELECT * FROM orders o JOIN users u ON o.user_id = u.user_id"
        tables = sql_generator._extract_table_references(sql)
        assert "orders" in tables
        assert "users" in tables

    def test_multiple_joins(self, sql_generator):
        """从多个 JOIN 子句提取所有表名"""
        sql = (
            "SELECT * FROM orders o "
            "LEFT JOIN users u ON o.user_id = u.user_id "
            "INNER JOIN products p ON o.product_id = p.product_id"
        )
        tables = sql_generator._extract_table_references(sql)
        assert "orders" in tables
        assert "users" in tables
        assert "products" in tables

    def test_backtick_table_names(self, sql_generator):
        """从反引号包裹的表名中正确提取"""
        sql = "SELECT * FROM `orders` o JOIN `users` u ON o.user_id = u.user_id"
        tables = sql_generator._extract_table_references(sql)
        assert "orders" in tables
        assert "users" in tables

    def test_no_sql_keywords_as_tables(self, sql_generator):
        """确保 SQL 关键字不被误识别为表名"""
        sql = "SELECT * FROM orders WHERE status = 'active'"
        tables = sql_generator._extract_table_references(sql)
        assert "orders" in tables
        # WHERE, SELECT 等不应出现
        assert "WHERE" not in [t.upper() for t in tables]
        assert "SELECT" not in [t.upper() for t in tables]


# ============================================================
# LLM 响应解析测试
# ============================================================

class TestParseLlmResponse:
    """LLM 响应解析测试"""

    def test_parse_plain_json(self, sql_generator):
        """解析纯 JSON 响应"""
        response = json.dumps({
            "sql": "SELECT * FROM orders",
            "explanation": "查询所有订单",
            "confidence": 0.9,
            "referenced_tables": ["orders"],
        })
        result = sql_generator._parse_llm_response(response)
        assert result["sql"] == "SELECT * FROM orders"
        assert result["confidence"] == 0.9

    def test_parse_markdown_code_block(self, sql_generator):
        """解析 markdown 代码块包裹的 JSON"""
        response = '```json\n{"sql": "SELECT 1", "explanation": "test", "confidence": 0.8, "referenced_tables": []}\n```'
        result = sql_generator._parse_llm_response(response)
        assert result["sql"] == "SELECT 1"

    def test_parse_invalid_json_raises_error(self, sql_generator):
        """解析无效 JSON 时抛出异常"""
        response = "This is not valid JSON at all"
        with pytest.raises(SQLGeneratorError):
            sql_generator._parse_llm_response(response)


# ============================================================
# generate_sql 方法测试（Mock LLM）
# ============================================================

class TestGenerateSQL:
    """SQL 生成方法测试"""

    def test_generate_sql_success(self, sql_generator, sample_ddl_context):
        """成功生成 SQL"""
        # Mock LLM 响应
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "sql": "SELECT order_id, amount FROM orders WHERE status = 'paid'",
            "explanation": "查询已支付的订单",
            "confidence": 0.95,
            "referenced_tables": ["orders"],
            "clarification_needed": False,
        })
        sql_generator.client.chat.completions.create = MagicMock(
            return_value=mock_response
        )

        params = SQLGenParams(
            user_query="查询所有已支付的订单",
            ddl_context=sample_ddl_context,
            conversation_history=[],
        )

        result = sql_generator.generate_sql(params)
        assert isinstance(result, SQLGenResult)
        assert "orders" in result.sql
        assert result.confidence == 0.95
        assert "orders" in result.referenced_tables

    def test_generate_sql_clarification_needed(self, sql_generator, sample_ddl_context):
        """意图不明确时返回澄清请求"""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "sql": "",
            "explanation": "",
            "confidence": 0.0,
            "referenced_tables": [],
            "clarification_needed": True,
            "clarification_message": "请问您想查询哪个时间段的数据？",
        })
        sql_generator.client.chat.completions.create = MagicMock(
            return_value=mock_response
        )

        params = SQLGenParams(
            user_query="查一下数据",
            ddl_context=sample_ddl_context,
            conversation_history=[],
        )

        result = sql_generator.generate_sql(params)
        assert result.sql == ""
        assert result.confidence == 0.0
        assert "时间段" in result.explanation

    def test_generate_sql_with_conversation_history(
        self, sql_generator, sample_ddl_context
    ):
        """带对话历史的 SQL 生成"""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "sql": "SELECT user_id, SUM(amount) FROM orders WHERE status = 'paid' GROUP BY user_id",
            "explanation": "按用户统计已支付订单金额",
            "confidence": 0.9,
            "referenced_tables": ["orders"],
        })
        sql_generator.client.chat.completions.create = MagicMock(
            return_value=mock_response
        )

        params = SQLGenParams(
            user_query="按用户分组统计金额",
            ddl_context=sample_ddl_context,
            conversation_history=[
                {"role": "user", "content": "查询已支付的订单"},
                {"role": "agent", "content": "已生成SQL", "sql": "SELECT * FROM orders WHERE status = 'paid'"},
            ],
        )

        result = sql_generator.generate_sql(params)
        assert result.sql != ""
        assert result.confidence > 0

    def test_generate_sql_llm_failure(self, sql_generator, sample_ddl_context):
        """LLM 调用失败时抛出异常"""
        sql_generator.client.chat.completions.create = MagicMock(
            side_effect=Exception("Connection timeout")
        )

        params = SQLGenParams(
            user_query="查询订单",
            ddl_context=sample_ddl_context,
            conversation_history=[],
        )

        with pytest.raises(LLMCallError):
            sql_generator.generate_sql(params)


# ============================================================
# refine_sql_with_feedback 方法测试
# ============================================================

class TestRefineSqlWithFeedback:
    """SQL 反馈修正测试"""

    def test_refine_sql_success(self, sql_generator, sample_ddl_context):
        """成功根据反馈修正 SQL"""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "sql": "SELECT order_id, amount FROM orders WHERE status = 'paid' AND amount > 100",
            "explanation": "添加了金额大于100的筛选条件",
            "confidence": 0.9,
            "referenced_tables": ["orders"],
        })
        sql_generator.client.chat.completions.create = MagicMock(
            return_value=mock_response
        )

        result = sql_generator.refine_sql_with_feedback(
            original_sql="SELECT order_id, amount FROM orders WHERE status = 'paid'",
            feedback="请加上金额大于100的条件",
            context={"ddl_context": sample_ddl_context, "conversation_history": []},
        )

        assert isinstance(result, SQLGenResult)
        assert "amount > 100" in result.sql


# ============================================================
# generate_reference_sql 方法测试
# ============================================================

class TestGenerateReferenceSQL:
    """参考 SQL 生成测试"""

    def test_generate_reference_sql_success(self, sql_generator, sample_ddl_context):
        """成功生成参考 SQL"""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            "SELECT DATE(created_at) as order_date, SUM(amount) as total_amount "
            "FROM orders WHERE created_at >= '${start_date}' GROUP BY DATE(created_at)"
        )
        sql_generator.client.chat.completions.create = MagicMock(
            return_value=mock_response
        )

        result = sql_generator.generate_reference_sql(
            metric_name="日订单金额",
            description="统计每日的订单总金额",
            ddl_context=sample_ddl_context,
        )

        assert isinstance(result, str)
        assert len(result) > 0
        assert "SELECT" in result

    def test_generate_reference_sql_strips_markdown(self, sql_generator, sample_ddl_context):
        """去除 markdown 代码块标记"""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            "```sql\nSELECT COUNT(*) FROM orders\n```"
        )
        sql_generator.client.chat.completions.create = MagicMock(
            return_value=mock_response
        )

        result = sql_generator.generate_reference_sql(
            metric_name="订单总数",
            description="统计订单总数量",
            ddl_context=sample_ddl_context,
        )

        assert "```" not in result
        assert "SELECT COUNT(*) FROM orders" in result


# ============================================================
# DDL 上下文构建测试
# ============================================================

class TestBuildDDLContext:
    """DDL 上下文构建测试"""

    def test_empty_ddl_context(self, sql_generator):
        """空 DDL 上下文返回提示文本"""
        result = sql_generator._build_ddl_context_text([])
        assert "无可用的表结构信息" in result

    def test_ddl_context_includes_table_info(self, sql_generator, sample_ddl_context):
        """DDL 上下文包含表名信息"""
        result = sql_generator._build_ddl_context_text(sample_ddl_context)
        assert "orders" in result
        assert "users" in result
        assert "products" in result


# ============================================================
# 对话历史构建测试
# ============================================================

class TestBuildConversationHistory:
    """对话历史构建测试"""

    def test_empty_history(self, sql_generator):
        """空对话历史返回空字符串"""
        result = sql_generator._build_conversation_history_text([])
        assert result == ""

    def test_history_with_messages(self, sql_generator):
        """对话历史包含用户和助手消息"""
        history = [
            {"role": "user", "content": "查询订单"},
            {"role": "agent", "content": "已生成SQL", "sql": "SELECT * FROM orders"},
        ]
        result = sql_generator._build_conversation_history_text(history)
        assert "用户: 查询订单" in result
        assert "助手: 已生成SQL" in result
        assert "SELECT * FROM orders" in result
