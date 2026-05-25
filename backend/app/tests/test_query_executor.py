"""
Query Executor 单元测试

验证查询执行器的核心功能：SQL 执行、超时控制、结果截断、
查询取消和重试机制。使用 Mock 模拟 aiomysql 连接。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import ExecuteOptions, QueryResult
from app.services.query_executor import QueryExecutor


@pytest.fixture
def executor():
    """创建 QueryExecutor 实例"""
    return QueryExecutor()


def _make_cursor_description(columns: list[tuple[str, int]]) -> list[tuple]:
    """构造模拟的 cursor.description

    Args:
        columns: [(列名, type_code), ...] 列表

    Returns:
        模拟的 description 元组列表
    """
    # cursor.description 每列为 7 元素元组
    return [(name, tc, None, None, None, None, None) for name, tc in columns]


class TestExecuteSQL:
    """execute_sql 方法测试"""

    @pytest.mark.asyncio
    async def test_execute_simple_query(self, executor):
        """测试执行简单查询返回正确结果"""
        mock_cursor = AsyncMock()
        mock_cursor.description = _make_cursor_description([
            ("id", 3), ("name", 253)
        ])
        mock_cursor.fetchmany = AsyncMock(
            return_value=[(1, "Alice"), (2, "Bob")]
        )
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.closed = False
        mock_conn.close = MagicMock()

        with patch.object(executor, "_create_connection", return_value=mock_conn):
            result = await executor.execute_sql("SELECT id, name FROM users")

        assert result.row_count == 2
        assert len(result.columns) == 2
        assert result.columns[0].name == "id"
        assert result.columns[0].is_numeric is True
        assert result.columns[1].name == "name"
        assert result.columns[1].is_numeric is False
        assert result.truncated is False
        assert result.rows == [[1, "Alice"], [2, "Bob"]]

    @pytest.mark.asyncio
    async def test_execute_with_truncation(self, executor):
        """测试结果超过 max_rows 时截断并设置 truncated=true"""
        # 生成 1001 行数据（超过默认 1000 行限制）
        rows_data = [(i,) for i in range(1001)]

        mock_cursor = AsyncMock()
        mock_cursor.description = _make_cursor_description([("id", 3)])
        mock_cursor.fetchmany = AsyncMock(return_value=rows_data)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.closed = False
        mock_conn.close = MagicMock()

        with patch.object(executor, "_create_connection", return_value=mock_conn):
            result = await executor.execute_sql("SELECT id FROM big_table")

        assert result.row_count == 1000
        assert result.truncated is True
        assert len(result.rows) == 1000

    @pytest.mark.asyncio
    async def test_execute_no_truncation_at_boundary(self, executor):
        """测试结果恰好等于 max_rows 时不截断"""
        rows_data = [(i,) for i in range(1000)]

        mock_cursor = AsyncMock()
        mock_cursor.description = _make_cursor_description([("id", 3)])
        mock_cursor.fetchmany = AsyncMock(return_value=rows_data)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.closed = False
        mock_conn.close = MagicMock()

        with patch.object(executor, "_create_connection", return_value=mock_conn):
            result = await executor.execute_sql("SELECT id FROM table")

        assert result.row_count == 1000
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_execute_with_custom_options(self, executor):
        """测试使用自定义 ExecuteOptions"""
        rows_data = [(i,) for i in range(6)]

        mock_cursor = AsyncMock()
        mock_cursor.description = _make_cursor_description([("val", 3)])
        mock_cursor.fetchmany = AsyncMock(return_value=rows_data)
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.closed = False
        mock_conn.close = MagicMock()

        options = ExecuteOptions(timeout=5000, max_rows=5, query_id="test-q1")

        with patch.object(executor, "_create_connection", return_value=mock_conn):
            result = await executor.execute_sql("SELECT val FROM t", options)

        # fetchmany 应该请求 max_rows + 1 = 6 行
        mock_cursor.fetchmany.assert_called_once_with(6)
        assert result.row_count == 5
        assert result.truncated is True

    @pytest.mark.asyncio
    async def test_execute_timeout_raises_error(self, executor):
        """测试查询超时抛出 TimeoutError"""

        async def slow_query(*args, **kwargs):
            await asyncio.sleep(10)
            return []

        mock_cursor = AsyncMock()
        mock_cursor.description = _make_cursor_description([("id", 3)])
        mock_cursor.execute = slow_query
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.closed = False
        mock_conn.close = MagicMock()

        options = ExecuteOptions(timeout=100, max_rows=1000)  # 100ms 超时

        with patch.object(executor, "_create_connection", return_value=mock_conn):
            with pytest.raises(TimeoutError, match="timed out"):
                await executor.execute_sql("SELECT SLEEP(10)", options)

    @pytest.mark.asyncio
    async def test_execute_connection_error(self, executor):
        """测试连接失败抛出 ConnectionError"""
        with patch.object(
            executor,
            "_create_connection",
            side_effect=ConnectionError("Connection refused"),
        ):
            with pytest.raises(ConnectionError, match="Connection refused"):
                await executor.execute_sql("SELECT 1")

    @pytest.mark.asyncio
    async def test_execute_query_error(self, executor):
        """测试查询执行错误抛出 RuntimeError"""
        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock(
            side_effect=Exception("Unknown column 'x'")
        )
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.closed = False
        mock_conn.close = MagicMock()

        with patch.object(executor, "_create_connection", return_value=mock_conn):
            with pytest.raises(RuntimeError, match="Query execution failed"):
                await executor.execute_sql("SELECT x FROM t")

    @pytest.mark.asyncio
    async def test_execute_cleans_up_active_queries(self, executor):
        """测试执行完成后清理活跃查询记录"""
        mock_cursor = AsyncMock()
        mock_cursor.description = _make_cursor_description([("id", 3)])
        mock_cursor.fetchmany = AsyncMock(return_value=[(1,)])
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.cursor = MagicMock(return_value=mock_cursor)
        mock_conn.closed = False
        mock_conn.close = MagicMock()

        with patch.object(executor, "_create_connection", return_value=mock_conn):
            await executor.execute_sql("SELECT 1")

        # 执行完成后活跃查询应为空
        assert len(executor._active_queries) == 0


class TestCancelQuery:
    """cancel_query 方法测试"""

    @pytest.mark.asyncio
    async def test_cancel_existing_query(self, executor):
        """测试取消存在的活跃查询"""
        mock_conn = MagicMock()
        mock_conn.close = MagicMock()
        executor._active_queries["q-123"] = mock_conn

        await executor.cancel_query("q-123")

        mock_conn.close.assert_called_once()
        assert "q-123" not in executor._active_queries

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_query_raises(self, executor):
        """测试取消不存在的查询抛出 ValueError"""
        with pytest.raises(ValueError, match="not found"):
            await executor.cancel_query("nonexistent-id")


class TestExecuteWithRetry:
    """execute_with_retry 方法测试"""

    @pytest.mark.asyncio
    async def test_retry_success_on_first_attempt(self, executor):
        """测试第一次执行成功直接返回"""
        expected = QueryResult(
            columns=[], rows=[[1]], row_count=1,
            execution_time=10.0, truncated=False,
        )

        with patch.object(executor, "execute_sql", return_value=expected):
            result = await executor.execute_with_retry("SELECT 1")

        assert result == expected

    @pytest.mark.asyncio
    async def test_retry_success_on_second_attempt(self, executor):
        """测试第一次失败、第二次成功"""
        expected = QueryResult(
            columns=[], rows=[[1]], row_count=1,
            execution_time=10.0, truncated=False,
        )

        call_count = 0

        async def mock_execute(sql, options=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Syntax error")
            return expected

        fix_cb = AsyncMock(return_value="SELECT 1 -- fixed")

        with patch.object(executor, "execute_sql", side_effect=mock_execute):
            result = await executor.execute_with_retry(
                "SELECT bad", fix_callback=fix_cb
            )

        assert result == expected
        fix_cb.assert_called_once()
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises_error(self, executor):
        """测试重试次数耗尽后抛出 RuntimeError"""
        with patch.object(
            executor,
            "execute_sql",
            side_effect=RuntimeError("Persistent error"),
        ):
            with pytest.raises(RuntimeError, match="failed after 3 attempts"):
                await executor.execute_with_retry("SELECT bad")

    @pytest.mark.asyncio
    async def test_retry_timeout_not_retried(self, executor):
        """测试超时错误不重试，直接抛出"""
        with patch.object(
            executor,
            "execute_sql",
            side_effect=TimeoutError("Query timed out after 30 seconds"),
        ):
            with pytest.raises(TimeoutError):
                await executor.execute_with_retry("SELECT SLEEP(60)")

    @pytest.mark.asyncio
    async def test_retry_connection_error_not_retried(self, executor):
        """测试连接错误不重试，直接抛出"""
        with patch.object(
            executor,
            "execute_sql",
            side_effect=ConnectionError("Connection refused"),
        ):
            with pytest.raises(ConnectionError):
                await executor.execute_with_retry("SELECT 1")

    @pytest.mark.asyncio
    async def test_retry_without_fix_callback(self, executor):
        """测试无 fix_callback 时使用原 SQL 重试"""
        call_count = 0
        received_sqls = []

        async def mock_execute(sql, options=None):
            nonlocal call_count
            call_count += 1
            received_sqls.append(sql)
            if call_count < 3:
                raise RuntimeError("Error")
            return QueryResult(
                columns=[], rows=[], row_count=0,
                execution_time=5.0, truncated=False,
            )

        with patch.object(executor, "execute_sql", side_effect=mock_execute):
            result = await executor.execute_with_retry("SELECT 1")

        assert call_count == 3
        # 无 fix_callback 时每次使用相同 SQL
        assert all(s == "SELECT 1" for s in received_sqls)

    @pytest.mark.asyncio
    async def test_retry_fix_callback_updates_sql(self, executor):
        """测试 fix_callback 修正 SQL 后用新 SQL 重试"""
        call_count = 0
        received_sqls = []

        async def mock_execute(sql, options=None):
            nonlocal call_count
            call_count += 1
            received_sqls.append(sql)
            if call_count < 2:
                raise RuntimeError("Unknown column 'x'")
            return QueryResult(
                columns=[], rows=[[1]], row_count=1,
                execution_time=5.0, truncated=False,
            )

        async def fix_sql(original_sql: str, error: str) -> str:
            return "SELECT id FROM users"

        with patch.object(executor, "execute_sql", side_effect=mock_execute):
            result = await executor.execute_with_retry(
                "SELECT x FROM users", fix_callback=fix_sql
            )

        assert received_sqls[0] == "SELECT x FROM users"
        assert received_sqls[1] == "SELECT id FROM users"
        assert result.row_count == 1


class TestColumnClassification:
    """列类型分类测试"""

    def test_numeric_column(self, executor):
        """测试数值类型列识别"""
        col = executor._classify_column(("amount", 5, None, None, None, None, None))
        assert col.name == "amount"
        assert col.type == "DOUBLE"
        assert col.is_numeric is True
        assert col.is_date_time is False

    def test_datetime_column(self, executor):
        """测试日期时间类型列识别"""
        col = executor._classify_column(("created_at", 12, None, None, None, None, None))
        assert col.name == "created_at"
        assert col.type == "DATETIME"
        assert col.is_numeric is False
        assert col.is_date_time is True

    def test_varchar_column(self, executor):
        """测试字符串类型列识别"""
        col = executor._classify_column(("name", 253, None, None, None, None, None))
        assert col.name == "name"
        assert col.type == "VARCHAR"
        assert col.is_numeric is False
        assert col.is_date_time is False

    def test_unknown_type_defaults_to_varchar(self, executor):
        """测试未知类型默认为 VARCHAR"""
        col = executor._classify_column(("unknown", 999, None, None, None, None, None))
        assert col.type == "VARCHAR"
        assert col.is_numeric is False
        assert col.is_date_time is False
