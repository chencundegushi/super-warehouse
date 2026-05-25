"""
DDL Manager 单元测试

验证 DDL 管理器的缓存读写、DDL 解析和核心方法逻辑。
使用临时目录模拟缓存，Mock PyMySQL 连接模拟 Doris 交互。
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.schemas import DDLFilterParams, DDLInfo, DDLLoadParams
from app.services.ddl_manager import DDLManager, DorisConnectionError


@pytest.fixture
def tmp_cache_dir(tmp_path):
    """创建临时缓存目录"""
    return str(tmp_path / "cache" / "ddl")


@pytest.fixture
def ddl_manager(tmp_cache_dir):
    """创建使用临时缓存目录的 DDL Manager 实例"""
    return DDLManager(
        cache_dir=tmp_cache_dir,
        host="localhost",
        port=9030,
        user="root",
        password="",
        database="test_db",
    )


# 测试用 DDL 样本
SAMPLE_DDL = """CREATE TABLE `test_db`.`orders` (
  `order_id` BIGINT NOT NULL COMMENT '订单ID',
  `user_id` INT NOT NULL COMMENT '用户ID',
  `amount` DECIMAL(10,2) NULL COMMENT '订单金额',
  `status` VARCHAR(32) NOT NULL COMMENT '订单状态',
  `created_at` DATETIME NULL COMMENT '创建时间'
) ENGINE=OLAP
UNIQUE KEY(`order_id`)
DISTRIBUTED BY HASH(`order_id`) BUCKETS 16
PROPERTIES ("replication_num" = "1");"""


class TestParseDDL:
    """DDL 解析测试"""

    def test_parse_basic_columns(self, ddl_manager):
        """测试解析基本列定义"""
        columns = ddl_manager._parse_ddl(SAMPLE_DDL)
        assert len(columns) == 5

        # 验证第一列
        assert columns[0].name == "order_id"
        assert columns[0].type == "BIGINT"
        assert columns[0].nullable is False
        assert columns[0].comment == "订单ID"
        assert columns[0].is_primary_key is True

    def test_parse_nullable_column(self, ddl_manager):
        """测试解析可空列"""
        columns = ddl_manager._parse_ddl(SAMPLE_DDL)
        # amount 列是 NULL
        amount_col = next(c for c in columns if c.name == "amount")
        assert amount_col.nullable is True
        assert amount_col.type == "DECIMAL(10,2)"

    def test_parse_primary_key(self, ddl_manager):
        """测试解析主键标识"""
        ddl_with_pk = """CREATE TABLE `db`.`t` (
  `id` INT NOT NULL COMMENT 'ID',
  `name` VARCHAR(64) NULL COMMENT '名称',
  PRIMARY KEY (`id`)
) ENGINE=OLAP;"""
        columns = ddl_manager._parse_ddl(ddl_with_pk)
        id_col = next(c for c in columns if c.name == "id")
        name_col = next(c for c in columns if c.name == "name")
        assert id_col.is_primary_key is True
        assert name_col.is_primary_key is False


class TestCacheOperations:
    """缓存读写测试"""

    def test_save_and_load_cache(self, ddl_manager):
        """测试缓存文件写入和读取"""
        from app.models.schemas import ColumnDefinition

        now = datetime.now(timezone.utc)
        ddl_info = DDLInfo(
            id="test_db.orders",
            database="test_db",
            table_name="orders",
            ddl_content=SAMPLE_DDL,
            columns=[
                ColumnDefinition(
                    name="order_id", type="BIGINT",
                    nullable=False, comment="订单ID", is_primary_key=True,
                ),
            ],
            field_count=1,
            loaded_at=now,
        )

        # 写入缓存
        ddl_manager._save_to_cache(ddl_info)

        # 验证文件存在
        cache_path = ddl_manager._get_cache_path("test_db", "orders")
        assert cache_path.exists()

        # 读取缓存
        loaded = ddl_manager._load_from_cache("test_db", "orders")
        assert loaded is not None
        assert loaded.database == "test_db"
        assert loaded.table_name == "orders"
        assert loaded.ddl_content == SAMPLE_DDL
        assert len(loaded.columns) == 1
        assert loaded.columns[0].name == "order_id"

    def test_load_nonexistent_cache(self, ddl_manager):
        """测试加载不存在的缓存返回 None"""
        result = ddl_manager._load_from_cache("no_db", "no_table")
        assert result is None

    def test_is_table_loaded(self, ddl_manager):
        """测试检查表是否已加载"""
        assert ddl_manager.is_table_loaded("test_db", "orders") is False

        # 创建缓存文件
        from app.models.schemas import ColumnDefinition
        ddl_info = DDLInfo(
            id="test_db.orders",
            database="test_db",
            table_name="orders",
            ddl_content="CREATE TABLE ...",
            columns=[],
            field_count=0,
            loaded_at=datetime.now(timezone.utc),
        )
        ddl_manager._save_to_cache(ddl_info)

        assert ddl_manager.is_table_loaded("test_db", "orders") is True


class TestClearCache:
    """缓存清除测试"""

    def _create_cache_files(self, ddl_manager):
        """辅助方法：创建多个缓存文件"""
        from app.models.schemas import ColumnDefinition

        for db, table in [("db1", "t1"), ("db1", "t2"), ("db2", "t3")]:
            ddl_info = DDLInfo(
                id=f"{db}.{table}",
                database=db,
                table_name=table,
                ddl_content=f"CREATE TABLE {table} ...",
                columns=[],
                field_count=0,
                loaded_at=datetime.now(timezone.utc),
            )
            ddl_manager._save_to_cache(ddl_info)

    def test_clear_single_table(self, ddl_manager):
        """测试清除单个表的缓存"""
        self._create_cache_files(ddl_manager)
        ddl_manager.clear_cache(database="db1", table="t1")

        assert not ddl_manager.is_table_loaded("db1", "t1")
        assert ddl_manager.is_table_loaded("db1", "t2")
        assert ddl_manager.is_table_loaded("db2", "t3")

    def test_clear_database(self, ddl_manager):
        """测试清除整个数据库的缓存"""
        self._create_cache_files(ddl_manager)
        ddl_manager.clear_cache(database="db1")

        assert not ddl_manager.is_table_loaded("db1", "t1")
        assert not ddl_manager.is_table_loaded("db1", "t2")
        assert ddl_manager.is_table_loaded("db2", "t3")

    def test_clear_all(self, ddl_manager):
        """测试清除所有缓存"""
        self._create_cache_files(ddl_manager)
        ddl_manager.clear_cache()

        assert not ddl_manager.is_table_loaded("db1", "t1")
        assert not ddl_manager.is_table_loaded("db1", "t2")
        assert not ddl_manager.is_table_loaded("db2", "t3")


class TestListLoadedDDL:
    """列表查询测试"""

    def _create_cache_files(self, ddl_manager):
        """辅助方法：创建多个缓存文件"""
        for db, table in [("db1", "orders"), ("db1", "users"), ("db2", "products")]:
            ddl_info = DDLInfo(
                id=f"{db}.{table}",
                database=db,
                table_name=table,
                ddl_content=f"CREATE TABLE {table} ...",
                columns=[],
                field_count=0,
                loaded_at=datetime.now(timezone.utc),
            )
            ddl_manager._save_to_cache(ddl_info)

    def test_list_all(self, ddl_manager):
        """测试列出所有已加载的 DDL"""
        self._create_cache_files(ddl_manager)
        results = ddl_manager.list_loaded_ddl()
        assert len(results) == 3

    def test_filter_by_database(self, ddl_manager):
        """测试按数据库名过滤"""
        self._create_cache_files(ddl_manager)
        params = DDLFilterParams(database="db1")
        results = ddl_manager.list_loaded_ddl(params)
        assert len(results) == 2
        assert all(r.database == "db1" for r in results)

    def test_filter_by_table_name(self, ddl_manager):
        """测试按表名过滤（模糊匹配）"""
        self._create_cache_files(ddl_manager)
        params = DDLFilterParams(table_name="order")
        results = ddl_manager.list_loaded_ddl(params)
        assert len(results) == 1
        assert results[0].table_name == "orders"

    def test_list_empty_cache(self, ddl_manager):
        """测试空缓存返回空列表"""
        results = ddl_manager.list_loaded_ddl()
        assert results == []


class TestDetectUnloadedTables:
    """未加载表检测测试"""

    def test_all_loaded(self, ddl_manager):
        """测试所有表都已加载时返回空列表"""
        ddl_info = DDLInfo(
            id="db1.orders",
            database="db1",
            table_name="orders",
            ddl_content="CREATE TABLE ...",
            columns=[],
            field_count=0,
            loaded_at=datetime.now(timezone.utc),
        )
        ddl_manager._save_to_cache(ddl_info)

        unloaded = ddl_manager.detect_unloaded_tables(["orders"], "db1")
        assert unloaded == []

    def test_some_unloaded(self, ddl_manager):
        """测试部分表未加载时返回未加载列表"""
        ddl_info = DDLInfo(
            id="db1.orders",
            database="db1",
            table_name="orders",
            ddl_content="CREATE TABLE ...",
            columns=[],
            field_count=0,
            loaded_at=datetime.now(timezone.utc),
        )
        ddl_manager._save_to_cache(ddl_info)

        unloaded = ddl_manager.detect_unloaded_tables(
            ["orders", "users", "products"], "db1"
        )
        assert set(unloaded) == {"users", "products"}

    def test_all_unloaded(self, ddl_manager):
        """测试所有表都未加载时返回全部"""
        unloaded = ddl_manager.detect_unloaded_tables(
            ["orders", "users"], "db1"
        )
        assert set(unloaded) == {"orders", "users"}


class TestLoadDDL:
    """DDL 加载测试（Mock Doris 连接）"""

    @patch("app.services.ddl_manager.pymysql.connect")
    def test_load_specified_tables(self, mock_connect, ddl_manager):
        """测试加载指定表的 DDL"""
        # 模拟连接和游标
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        mock_cursor.fetchone.return_value = ("orders", SAMPLE_DDL)

        params = DDLLoadParams(database="test_db", tables=["orders"])
        results = ddl_manager.load_ddl(params)

        assert len(results) == 1
        assert results[0].table_name == "orders"
        assert results[0].database == "test_db"
        assert ddl_manager.is_table_loaded("test_db", "orders")
        mock_conn.close.assert_called_once()

    @patch("app.services.ddl_manager.pymysql.connect")
    def test_load_all_tables(self, mock_connect, ddl_manager):
        """测试加载整个数据库所有表"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # 第一次调用 SHOW TABLES
        # 第二次调用 SHOW CREATE TABLE
        mock_cursor.fetchall.return_value = [("orders",), ("users",)]
        mock_cursor.fetchone.return_value = ("orders", SAMPLE_DDL)

        params = DDLLoadParams(database="test_db")
        results = ddl_manager.load_ddl(params)

        assert len(results) == 2
        mock_conn.close.assert_called_once()

    @patch("app.services.ddl_manager.pymysql.connect")
    def test_connection_failure_raises_error(self, mock_connect, ddl_manager):
        """测试连接失败时抛出异常且不修改缓存"""
        import pymysql
        mock_connect.side_effect = pymysql.Error("Connection refused")

        # 预先创建缓存
        ddl_info = DDLInfo(
            id="test_db.existing",
            database="test_db",
            table_name="existing",
            ddl_content="CREATE TABLE ...",
            columns=[],
            field_count=0,
            loaded_at=datetime.now(timezone.utc),
        )
        ddl_manager._save_to_cache(ddl_info)

        params = DDLLoadParams(database="test_db", tables=["new_table"])
        with pytest.raises(DorisConnectionError):
            ddl_manager.load_ddl(params)

        # 验证现有缓存未被修改
        assert ddl_manager.is_table_loaded("test_db", "existing")


class TestRefreshDDL:
    """DDL 刷新测试（Mock Doris 连接）"""

    @patch("app.services.ddl_manager.pymysql.connect")
    def test_refresh_specific_tables(self, mock_connect, ddl_manager):
        """测试刷新指定表"""
        # 预先创建缓存
        ddl_info = DDLInfo(
            id="test_db.orders",
            database="test_db",
            table_name="orders",
            ddl_content="OLD DDL",
            columns=[],
            field_count=0,
            loaded_at=datetime.now(timezone.utc),
        )
        ddl_manager._save_to_cache(ddl_info)

        # 模拟连接
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.return_value = ("orders", SAMPLE_DDL)

        results = ddl_manager.refresh_ddl(table_ids=["test_db.orders"])

        assert len(results) == 1
        assert results[0].ddl_content == SAMPLE_DDL
        mock_conn.close.assert_called_once()

    @patch("app.services.ddl_manager.pymysql.connect")
    def test_refresh_connection_failure(self, mock_connect, ddl_manager):
        """测试刷新时连接失败保留现有缓存"""
        import pymysql

        # 预先创建缓存
        ddl_info = DDLInfo(
            id="test_db.orders",
            database="test_db",
            table_name="orders",
            ddl_content="EXISTING DDL",
            columns=[],
            field_count=0,
            loaded_at=datetime.now(timezone.utc),
        )
        ddl_manager._save_to_cache(ddl_info)

        mock_connect.side_effect = pymysql.Error("Connection refused")

        with pytest.raises(DorisConnectionError):
            ddl_manager.refresh_ddl(table_ids=["test_db.orders"])

        # 验证缓存未被修改
        cached = ddl_manager.get_ddl_by_table("test_db", "orders")
        assert cached is not None
        assert cached.ddl_content == "EXISTING DDL"
