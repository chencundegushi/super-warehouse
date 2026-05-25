"""
DDL 管理器服务

负责管理数据库表结构信息的加载、文件缓存和更新。
通过 PyMySQL 连接 Apache Doris（MySQL 协议兼容），获取表的 DDL 信息，
并以 JSON 文件形式缓存到本地文件系统。

主要功能：
- 连接 Doris 获取指定表的 DDL
- 解析 DDL 提取列定义（名称、类型、是否可空、注释、主键）
- 文件缓存机制（JSON 格式存储）
- 支持选择性加载、刷新、查询和清除缓存
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pymysql

from app.core.config import settings
from app.models.schemas import (
    ColumnDefinition,
    DDLFilterParams,
    DDLInfo,
    DDLLoadParams,
)

logger = logging.getLogger(__name__)


class DDLManagerError(Exception):
    """DDL 管理器异常基类"""
    pass


class DorisConnectionError(DDLManagerError):
    """Doris 连接异常"""
    pass


class DDLManager:
    """DDL 管理器

    负责从 Apache Doris 获取表的 DDL 信息，解析列定义，
    并以 JSON 文件形式缓存到本地文件系统。

    Attributes:
        cache_dir: DDL 缓存文件根目录
        host: Doris 主机地址
        port: Doris 端口号
        user: Doris 用户名
        password: Doris 密码
        database: 默认数据库名
    """

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ):
        """初始化 DDL 管理器

        Args:
            cache_dir: 缓存目录路径，默认使用配置中的 ddl_cache_dir
            host: Doris 主机地址
            port: Doris 端口号
            user: Doris 用户名
            password: Doris 密码
            database: 默认数据库名
        """
        self.cache_dir = cache_dir or settings.ddl_cache_dir
        self.host = host or settings.doris_host
        self.port = port or settings.doris_port
        self.user = user or settings.doris_user
        self.password = password or settings.doris_password
        self.database = database or settings.doris_database

        logger.info(
            "DDL Manager initialized, cache_dir=%s, host=%s, port=%d",
            self.cache_dir, self.host, self.port,
        )

    def _get_connection(self, database: str) -> pymysql.Connection:
        """获取 Doris 数据库连接

        Args:
            database: 目标数据库名

        Returns:
            PyMySQL 连接对象

        Raises:
            DorisConnectionError: 连接失败时抛出
        """
        try:
            conn = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=database,
                charset="utf8mb4",
                connect_timeout=10,
            )
            logger.info("Connected to Doris, database=%s", database)
            return conn
        except pymysql.Error as e:
            logger.error("Failed to connect to Doris, database=%s, error=%s", database, str(e))
            raise DorisConnectionError(f"Failed to connect to Doris: {e}") from e

    def _get_cache_path(self, database: str, table: str) -> Path:
        """获取缓存文件路径

        Args:
            database: 数据库名
            table: 表名

        Returns:
            缓存文件的 Path 对象
        """
        return Path(self.cache_dir) / database / f"{table}.json"

    def _save_to_cache(self, ddl_info: DDLInfo) -> None:
        """将 DDL 信息保存到缓存文件

        Args:
            ddl_info: DDL 信息对象
        """
        cache_path = self._get_cache_path(ddl_info.database, ddl_info.table_name)
        # 1.确保目录存在
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        # 2.构建 JSON 数据结构
        cache_data = {
            "database_name": ddl_info.database,
            "table_name": ddl_info.table_name,
            "ddl_content": ddl_info.ddl_content,
            "field_count": ddl_info.field_count,
            "loaded_at": ddl_info.loaded_at.isoformat(),
            "columns": [
                {
                    "name": col.name,
                    "type": col.type,
                    "nullable": col.nullable,
                    "comment": col.comment,
                    "is_primary_key": col.is_primary_key,
                }
                for col in ddl_info.columns
            ],
        }

        # 3.写入 JSON 文件
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)

        logger.info(
            "Saved DDL cache, database=%s, table=%s, path=%s",
            ddl_info.database, ddl_info.table_name, str(cache_path),
        )

    def _load_from_cache(self, database: str, table: str) -> Optional[DDLInfo]:
        """从缓存文件加载 DDL 信息

        Args:
            database: 数据库名
            table: 表名

        Returns:
            DDL 信息对象，缓存不存在时返回 None
        """
        cache_path = self._get_cache_path(database, table)
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)

            columns = [
                ColumnDefinition(
                    name=col["name"],
                    type=col["type"],
                    nullable=col.get("nullable", True),
                    comment=col.get("comment"),
                    is_primary_key=col.get("is_primary_key", False),
                )
                for col in cache_data.get("columns", [])
            ]

            return DDLInfo(
                id=f"{database}.{table}",
                database=cache_data["database_name"],
                table_name=cache_data["table_name"],
                ddl_content=cache_data["ddl_content"],
                columns=columns,
                field_count=cache_data.get("field_count", len(columns)),
                loaded_at=datetime.fromisoformat(cache_data["loaded_at"]),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(
                "Failed to load DDL cache, database=%s, table=%s, error=%s",
                database, table, str(e),
            )
            return None

    def _parse_ddl(self, ddl_content: str) -> list[ColumnDefinition]:
        """解析 DDL 语句，提取列定义

        从 CREATE TABLE 语句中解析出每个列的名称、类型、是否可空、注释和主键信息。

        Args:
            ddl_content: 完整的 CREATE TABLE DDL 语句

        Returns:
            列定义列表
        """
        columns: list[ColumnDefinition] = []
        primary_keys: set[str] = set()

        # 1.提取 PRIMARY KEY / UNIQUE KEY 定义中的列名
        # Doris 中 UNIQUE KEY 等同于主键约束
        pk_pattern = re.compile(
            r'(?:PRIMARY|UNIQUE)\s+KEY\s*\(([^)]+)\)', re.IGNORECASE
        )
        for pk_match in pk_pattern.finditer(ddl_content):
            pk_cols = pk_match.group(1)
            for col_name in pk_cols.split(","):
                cleaned = col_name.strip().strip("`\"'")
                if cleaned:
                    primary_keys.add(cleaned.lower())

        # 2.逐行解析列定义
        col_pattern = re.compile(
            r'^\s*`?(\w+)`?\s+'        # 列名
            r'([A-Za-z]+[^,]*?)'        # 列类型及修饰
            r'\s*,?\s*$',               # 行尾
            re.IGNORECASE,
        )

        # 3.更精确的列定义正则：匹配反引号包裹的列名和类型
        detailed_col_pattern = re.compile(
            r'^\s*`([^`]+)`\s+'                  # 列名（反引号包裹）
            r'(\w+(?:\([^)]*\))?)'               # 列类型（含括号参数）
            r'(.*?)$',                           # 剩余修饰部分
            re.IGNORECASE,
        )

        lines = ddl_content.split("\n")
        for line in lines:
            line_stripped = line.strip().rstrip(",")
            # 4.跳过非列定义行
            if not line_stripped or line_stripped.startswith("("):
                continue
            if any(kw in line_stripped.upper() for kw in [
                "CREATE TABLE", "PRIMARY KEY", "ENGINE=",
                "DISTRIBUTED BY", "PROPERTIES", "PARTITION BY",
                "AGGREGATE KEY", "UNIQUE KEY", "DUPLICATE KEY",
                "COMMENT ON", "INDEX ", "ROLLUP",
            ]):
                continue
            if line_stripped.startswith(")"):
                continue

            # 5.尝试匹配列定义
            match = detailed_col_pattern.match(line_stripped)
            if match:
                col_name = match.group(1)
                col_type = match.group(2)
                modifiers = match.group(3).strip() if match.group(3) else ""

                # 6.判断是否可空
                nullable = True
                if "NOT NULL" in modifiers.upper():
                    nullable = False

                # 7.提取注释
                comment = None
                comment_match = re.search(
                    r"COMMENT\s+['\"]([^'\"]*)['\"]", modifiers, re.IGNORECASE
                )
                if comment_match:
                    comment = comment_match.group(1)

                # 8.判断是否为主键
                is_primary_key = col_name.lower() in primary_keys

                columns.append(ColumnDefinition(
                    name=col_name,
                    type=col_type,
                    nullable=nullable,
                    comment=comment,
                    is_primary_key=is_primary_key,
                ))

        return columns

    def _fetch_table_ddl(
        self, conn: pymysql.Connection, database: str, table: str
    ) -> Optional[DDLInfo]:
        """从 Doris 获取单张表的 DDL 信息

        Args:
            conn: 数据库连接
            database: 数据库名
            table: 表名

        Returns:
            DDL 信息对象，获取失败时返回 None
        """
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"SHOW CREATE TABLE `{database}`.`{table}`")
                result = cursor.fetchone()
                if not result or len(result) < 2:
                    logger.warning(
                        "No DDL returned for table, database=%s, table=%s",
                        database, table,
                    )
                    return None

                ddl_content = result[1]
                # 1.解析列定义
                columns = self._parse_ddl(ddl_content)
                now = datetime.now(timezone.utc)

                ddl_info = DDLInfo(
                    id=f"{database}.{table}",
                    database=database,
                    table_name=table,
                    ddl_content=ddl_content,
                    columns=columns,
                    field_count=len(columns),
                    loaded_at=now,
                )

                logger.info(
                    "Fetched DDL, database=%s, table=%s, field_count=%d",
                    database, table, len(columns),
                )
                return ddl_info

        except pymysql.Error as e:
            logger.error(
                "Failed to fetch DDL, database=%s, table=%s, error=%s",
                database, table, str(e),
            )
            return None

    def _list_tables(self, conn: pymysql.Connection, database: str) -> list[str]:
        """获取数据库中所有表名

        Args:
            conn: 数据库连接
            database: 数据库名

        Returns:
            表名列表
        """
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"SHOW TABLES FROM `{database}`")
                tables = [row[0] for row in cursor.fetchall()]
                logger.info(
                    "Listed tables, database=%s, count=%d", database, len(tables)
                )
                return tables
        except pymysql.Error as e:
            logger.error(
                "Failed to list tables, database=%s, error=%s", database, str(e)
            )
            return []

    def load_ddl(self, params: DDLLoadParams) -> list[DDLInfo]:
        """加载 DDL 信息

        连接 Doris 数据库，获取指定表（或整个数据库所有表）的 DDL，
        解析列定义并保存到文件缓存。

        Args:
            params: 加载参数，包含数据库名和可选的表名列表

        Returns:
            成功加载的 DDL 信息列表

        Raises:
            DorisConnectionError: Doris 连接失败时抛出
        """
        logger.info(
            "Loading DDL, database=%s, tables=%s",
            params.database, params.tables,
        )

        # 1.建立连接（连接失败时直接抛出异常，不修改缓存）
        conn = self._get_connection(params.database)

        try:
            # 2.确定要加载的表列表
            if params.tables:
                tables = params.tables
            else:
                tables = self._list_tables(conn, params.database)

            # 3.逐表获取 DDL 并缓存
            results: list[DDLInfo] = []
            for table in tables:
                ddl_info = self._fetch_table_ddl(conn, params.database, table)
                if ddl_info:
                    self._save_to_cache(ddl_info)
                    results.append(ddl_info)

            logger.info(
                "DDL loading completed, database=%s, loaded=%d/%d",
                params.database, len(results), len(tables),
            )
            return results

        finally:
            conn.close()
            logger.info("Doris connection closed, database=%s", params.database)

    def refresh_ddl(self, table_ids: Optional[list[str]] = None) -> list[DDLInfo]:
        """刷新已加载表的 DDL

        重新从 Doris 获取已缓存表的最新 DDL 并更新缓存文件。
        如果指定了 table_ids，则只刷新指定的表；否则刷新所有已缓存的表。

        Args:
            table_ids: 要刷新的表标识列表（格式：database.table），
                      为 None 时刷新所有已缓存的表

        Returns:
            成功刷新的 DDL 信息列表

        Raises:
            DorisConnectionError: Doris 连接失败时抛出
        """
        logger.info("Refreshing DDL, table_ids=%s", table_ids)

        # 1.确定要刷新的表
        if table_ids:
            tables_to_refresh = []
            for tid in table_ids:
                parts = tid.split(".", 1)
                if len(parts) == 2:
                    tables_to_refresh.append((parts[0], parts[1]))
        else:
            # 2.扫描缓存目录获取所有已缓存的表
            tables_to_refresh = self._get_all_cached_tables()

        if not tables_to_refresh:
            logger.info("No tables to refresh")
            return []

        # 3.按数据库分组
        db_tables: dict[str, list[str]] = {}
        for database, table in tables_to_refresh:
            db_tables.setdefault(database, []).append(table)

        # 4.逐数据库连接并刷新
        results: list[DDLInfo] = []
        for database, tables in db_tables.items():
            conn = self._get_connection(database)
            try:
                for table in tables:
                    ddl_info = self._fetch_table_ddl(conn, database, table)
                    if ddl_info:
                        self._save_to_cache(ddl_info)
                        results.append(ddl_info)
            finally:
                conn.close()

        logger.info("DDL refresh completed, refreshed=%d", len(results))
        return results

    def _get_all_cached_tables(self) -> list[tuple[str, str]]:
        """扫描缓存目录获取所有已缓存的表

        Returns:
            (database, table) 元组列表
        """
        cache_root = Path(self.cache_dir)
        tables: list[tuple[str, str]] = []

        if not cache_root.exists():
            return tables

        for db_dir in cache_root.iterdir():
            if db_dir.is_dir():
                for json_file in db_dir.glob("*.json"):
                    table_name = json_file.stem
                    tables.append((db_dir.name, table_name))

        return tables

    def list_loaded_ddl(
        self, params: Optional[DDLFilterParams] = None
    ) -> list[DDLInfo]:
        """列出已加载的 DDL 信息

        从文件缓存中读取所有已缓存的 DDL，支持按数据库名和表名过滤。

        Args:
            params: 过滤参数，可选

        Returns:
            匹配过滤条件的 DDL 信息列表
        """
        logger.info("Listing loaded DDL, params=%s", params)

        cache_root = Path(self.cache_dir)
        results: list[DDLInfo] = []

        if not cache_root.exists():
            return results

        for db_dir in cache_root.iterdir():
            if not db_dir.is_dir():
                continue

            # 1.按数据库名过滤
            if params and params.database and db_dir.name != params.database:
                continue

            for json_file in db_dir.glob("*.json"):
                table_name = json_file.stem

                # 2.按表名过滤（支持模糊匹配）
                if params and params.table_name:
                    if params.table_name.lower() not in table_name.lower():
                        continue

                # 3.从缓存文件加载
                ddl_info = self._load_from_cache(db_dir.name, table_name)
                if ddl_info:
                    results.append(ddl_info)

        logger.info("Listed loaded DDL, count=%d", len(results))
        return results

    def get_ddl_by_table(
        self, database: str, table: str
    ) -> Optional[DDLInfo]:
        """获取指定表的 DDL 信息

        从文件缓存中读取指定数据库和表的 DDL 信息。

        Args:
            database: 数据库名
            table: 表名

        Returns:
            DDL 信息对象，缓存不存在时返回 None
        """
        logger.info("Getting DDL by table, database=%s, table=%s", database, table)
        return self._load_from_cache(database, table)

    def is_table_loaded(self, database: str, table: str) -> bool:
        """检查表是否已加载

        检查指定表的缓存文件是否存在。

        Args:
            database: 数据库名
            table: 表名

        Returns:
            缓存文件存在返回 True，否则返回 False
        """
        cache_path = self._get_cache_path(database, table)
        loaded = cache_path.exists()
        logger.info(
            "Checking table loaded, database=%s, table=%s, loaded=%s",
            database, table, loaded,
        )
        return loaded

    def clear_cache(
        self, database: Optional[str] = None, table: Optional[str] = None
    ) -> None:
        """清除缓存文件

        根据参数清除指定范围的缓存文件：
        - 指定 database 和 table：删除单个表的缓存文件
        - 仅指定 database：删除该数据库目录下所有缓存文件
        - 都不指定：删除所有缓存文件

        Args:
            database: 数据库名，可选
            table: 表名，可选
        """
        logger.info(
            "Clearing cache, database=%s, table=%s", database, table
        )

        cache_root = Path(self.cache_dir)

        if database and table:
            # 1.删除单个表的缓存文件
            cache_path = self._get_cache_path(database, table)
            if cache_path.exists():
                cache_path.unlink()
                logger.info("Removed cache file, path=%s", str(cache_path))
            # 2.如果目录为空则删除目录
            db_dir = cache_path.parent
            if db_dir.exists() and not any(db_dir.iterdir()):
                db_dir.rmdir()
        elif database:
            # 3.删除整个数据库目录
            db_dir = cache_root / database
            if db_dir.exists():
                for json_file in db_dir.glob("*.json"):
                    json_file.unlink()
                db_dir.rmdir()
                logger.info("Removed database cache dir, path=%s", str(db_dir))
        else:
            # 4.删除所有缓存
            if cache_root.exists():
                for db_dir in cache_root.iterdir():
                    if db_dir.is_dir():
                        for json_file in db_dir.glob("*.json"):
                            json_file.unlink()
                        db_dir.rmdir()
                logger.info("Cleared all DDL cache")

    def detect_unloaded_tables(
        self, referenced_tables: list[str], database: str
    ) -> list[str]:
        """检测未加载的表

        给定一组引用的表名，检查哪些表尚未加载到缓存中。
        自动去除表名中的数据库前缀（如 'dt.ods_t_user' → 'ods_t_user'）。

        Args:
            referenced_tables: 引用的表名列表
            database: 数据库名

        Returns:
            未加载的表名列表
        """
        logger.info(
            "Detecting unloaded tables, database=%s, referenced=%s",
            database, referenced_tables,
        )

        unloaded = []
        for table in referenced_tables:
            # 去除数据库前缀（如 'dt.ods_t_user' → 'ods_t_user'）
            table_name = table.split(".")[-1] if "." in table else table
            if not self.is_table_loaded(database, table_name):
                logger.info(
                    "Checking table loaded, database=%s, table=%s, loaded=False",
                    database, table_name,
                )
                unloaded.append(table)
            else:
                logger.info(
                    "Checking table loaded, database=%s, table=%s, loaded=True",
                    database, table_name,
                )

        logger.info(
            "Unloaded tables detected, database=%s, unloaded=%s",
            database, unloaded,
        )
        return unloaded
