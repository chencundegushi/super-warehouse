"""
查询执行器服务

负责将 SQL 提交到 Apache Doris 执行，支持超时控制、结果行数限制、
查询取消和自动重试机制。通过 aiomysql 异步连接 Doris（MySQL 协议兼容）。
"""

import asyncio
import logging
import time
import uuid
from typing import Any, Callable, Coroutine, Optional

import aiomysql

from app.core.config import settings
from app.models.schemas import (
    ColumnInfo,
    ExecuteOptions,
    QueryResult,
)

logger = logging.getLogger(__name__)


class QueryExecutor:
    """查询执行器

    负责连接 Doris 执行 SQL 查询，提供超时控制、结果截断、
    查询取消和失败重试等能力。

    Attributes:
        _active_queries: 活跃查询字典，key 为 query_id，value 为连接对象
    """

    def __init__(self) -> None:
        """初始化查询执行器"""
        # 1.活跃查询追踪，用于取消操作
        self._active_queries: dict[str, aiomysql.Connection] = {}

    async def _create_connection(self) -> aiomysql.Connection:
        """创建 Doris 数据库连接

        Returns:
            aiomysql 异步连接对象

        Raises:
            ConnectionError: 连接失败时抛出
        """
        logger.info(
            "Creating Doris connection, host=%s, port=%d, user=%s, database=%s",
            settings.doris_host,
            settings.doris_port,
            settings.doris_user,
            settings.doris_database,
        )
        try:
            conn = await aiomysql.connect(
                host=settings.doris_host,
                port=settings.doris_port,
                user=settings.doris_user,
                password=settings.doris_password,
                db=settings.doris_database,
                autocommit=True,
            )
            return conn
        except Exception as e:
            logger.error("Failed to connect to Doris, error=%s", str(e))
            raise ConnectionError(
                f"Failed to connect to Doris: {str(e)}"
            ) from e

    def _classify_column(self, column_desc: tuple) -> ColumnInfo:
        """根据游标 description 信息分类列类型

        Args:
            column_desc: 游标 description 中的单列元组

        Returns:
            列信息对象
        """
        name = column_desc[0]
        type_code = column_desc[1]

        # aiomysql type_code 常量映射
        # 数值类型: TINY, SHORT, LONG, FLOAT, DOUBLE, LONGLONG, INT24, DECIMAL, NEWDECIMAL
        numeric_type_codes = {0, 1, 2, 3, 4, 5, 8, 9, 246}
        # 日期时间类型: TIMESTAMP, DATE, TIME, DATETIME, YEAR, NEWDATE
        datetime_type_codes = {7, 10, 11, 12, 13, 14}

        is_numeric = type_code in numeric_type_codes
        is_date_time = type_code in datetime_type_codes

        # 根据 type_code 推断类型名称
        type_name = self._get_type_name(type_code)

        return ColumnInfo(
            name=name,
            type=type_name,
            is_numeric=is_numeric,
            is_date_time=is_date_time,
        )

    @staticmethod
    def _get_type_name(type_code: int) -> str:
        """根据 MySQL type_code 获取类型名称

        Args:
            type_code: MySQL 字段类型代码

        Returns:
            类型名称字符串
        """
        type_map = {
            0: "DECIMAL",
            1: "TINYINT",
            2: "SMALLINT",
            3: "INT",
            4: "FLOAT",
            5: "DOUBLE",
            7: "TIMESTAMP",
            8: "BIGINT",
            9: "MEDIUMINT",
            10: "DATE",
            11: "TIME",
            12: "DATETIME",
            13: "YEAR",
            14: "NEWDATE",
            15: "VARCHAR",
            246: "DECIMAL",
            252: "TEXT",
            253: "VARCHAR",
            254: "CHAR",
        }
        return type_map.get(type_code, "VARCHAR")

    async def execute_sql(
        self,
        sql: str,
        options: Optional[ExecuteOptions] = None,
    ) -> QueryResult:
        """执行 SQL 查询

        连接 Doris 执行 SQL，支持超时控制和结果行数限制。
        超过 max_rows 时截断结果并设置 truncated=true。

        Args:
            sql: 要执行的 SQL 语句
            options: 执行选项（超时、最大行数、查询ID）

        Returns:
            查询结果对象

        Raises:
            TimeoutError: 查询超时
            ConnectionError: 连接失败
            RuntimeError: 查询执行错误
        """
        # 1.解析执行选项
        timeout_seconds = settings.query_timeout_seconds
        max_rows = settings.query_max_rows
        query_id = None

        if options:
            timeout_seconds = options.timeout / 1000  # ms 转 s
            max_rows = options.max_rows
            query_id = options.query_id

        # 2.生成 query_id 用于追踪
        if not query_id:
            query_id = str(uuid.uuid4())

        logger.info(
            "Executing SQL, query_id=%s, timeout=%ds, max_rows=%d, sql=%s",
            query_id,
            timeout_seconds,
            max_rows,
            sql[:200],
        )

        start_time = time.time()
        conn: Optional[aiomysql.Connection] = None

        try:
            # 3.创建连接并注册到活跃查询
            conn = await self._create_connection()
            self._active_queries[query_id] = conn

            # 4.使用 asyncio.wait_for 实现超时控制
            result = await asyncio.wait_for(
                self._execute_query(conn, sql, max_rows),
                timeout=timeout_seconds,
            )

            execution_time = (time.time() - start_time) * 1000
            result.execution_time = execution_time

            logger.info(
                "SQL executed successfully, query_id=%s, rows=%d, "
                "truncated=%s, time=%.2fms",
                query_id,
                result.row_count,
                result.truncated,
                execution_time,
            )
            return result

        except asyncio.TimeoutError:
            execution_time = (time.time() - start_time) * 1000
            logger.error(
                "Query timed out, query_id=%s, timeout=%ds, time=%.2fms",
                query_id,
                timeout_seconds,
                execution_time,
            )
            # 超时时尝试关闭连接终止查询
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            raise TimeoutError(
                f"Query timed out after {timeout_seconds} seconds"
            )

        except ConnectionError:
            raise

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            logger.error(
                "Query execution failed, query_id=%s, error=%s, time=%.2fms",
                query_id,
                str(e),
                execution_time,
            )
            raise RuntimeError(f"Query execution failed: {str(e)}") from e

        finally:
            # 5.清理活跃查询记录并关闭连接
            self._active_queries.pop(query_id, None)
            if conn and not conn.closed:
                conn.close()

    async def _execute_query(
        self,
        conn: aiomysql.Connection,
        sql: str,
        max_rows: int,
    ) -> QueryResult:
        """内部方法：执行查询并处理结果

        Args:
            conn: 数据库连接
            sql: SQL 语句
            max_rows: 最大返回行数

        Returns:
            查询结果对象
        """
        async with conn.cursor() as cursor:
            await cursor.execute(sql)

            # 1.获取列信息
            columns: list[ColumnInfo] = []
            if cursor.description:
                columns = [
                    self._classify_column(col) for col in cursor.description
                ]

            # 2.获取结果行，多取一行用于判断是否截断
            rows_raw = await cursor.fetchmany(max_rows + 1)

            # 3.判断是否需要截断
            truncated = len(rows_raw) > max_rows
            if truncated:
                rows_raw = rows_raw[:max_rows]

            # 4.转换行数据为列表格式
            rows: list[list[Any]] = [list(row) for row in rows_raw]

            return QueryResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_time=0,  # 由调用方设置实际耗时
                truncated=truncated,
            )

    async def cancel_query(self, query_id: str) -> None:
        """取消正在执行的查询

        通过关闭对应的数据库连接来终止查询执行。

        Args:
            query_id: 要取消的查询标识

        Raises:
            ValueError: 查询ID不存在或已完成
        """
        logger.info("Cancelling query, query_id=%s", query_id)

        conn = self._active_queries.get(query_id)
        if conn is None:
            logger.warning(
                "Query not found or already completed, query_id=%s", query_id
            )
            raise ValueError(
                f"Query '{query_id}' not found or already completed"
            )

        try:
            # 关闭连接以终止正在执行的查询
            conn.close()
            logger.info("Query cancelled successfully, query_id=%s", query_id)
        except Exception as e:
            logger.error(
                "Error cancelling query, query_id=%s, error=%s",
                query_id,
                str(e),
            )
        finally:
            self._active_queries.pop(query_id, None)

    async def execute_with_retry(
        self,
        sql: str,
        fix_callback: Optional[
            Callable[[str, str], Coroutine[Any, Any, str]]
        ] = None,
        options: Optional[ExecuteOptions] = None,
    ) -> QueryResult:
        """带重试机制的 SQL 执行

        执行失败时调用 fix_callback 获取修正后的 SQL 并重试，
        最多重试 query_max_retries 次（默认3次）。

        Args:
            sql: 初始 SQL 语句
            fix_callback: 异步回调函数，接收 (原始SQL, 错误信息)，
                         返回修正后的 SQL。为 None 时不进行修正直接重试。
            options: 执行选项

        Returns:
            查询结果对象

        Raises:
            TimeoutError: 查询超时（不重试）
            ConnectionError: 连接失败（不重试）
            RuntimeError: 重试次数耗尽后仍失败
        """
        max_retries = settings.query_max_retries
        current_sql = sql
        last_error: Optional[Exception] = None

        logger.info(
            "Executing SQL with retry, max_retries=%d, sql=%s",
            max_retries,
            sql[:200],
        )

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    "Attempt %d/%d, sql=%s",
                    attempt,
                    max_retries,
                    current_sql[:200],
                )
                result = await self.execute_sql(current_sql, options)
                if attempt > 1:
                    logger.info(
                        "Query succeeded on attempt %d/%d",
                        attempt,
                        max_retries,
                    )
                return result

            except TimeoutError:
                # 超时错误不重试，直接抛出
                logger.warning(
                    "Query timed out on attempt %d, not retrying", attempt
                )
                raise

            except ConnectionError:
                # 连接错误不重试，直接抛出
                logger.warning(
                    "Connection failed on attempt %d, not retrying", attempt
                )
                raise

            except RuntimeError as e:
                last_error = e
                error_msg = str(e)
                logger.warning(
                    "Query failed on attempt %d/%d, error=%s",
                    attempt,
                    max_retries,
                    error_msg,
                )

                # 如果已达到最大重试次数，终止
                if attempt >= max_retries:
                    break

                # 调用 fix_callback 获取修正后的 SQL
                if fix_callback:
                    try:
                        current_sql = await fix_callback(
                            current_sql, error_msg
                        )
                        logger.info(
                            "SQL fixed by callback, new_sql=%s",
                            current_sql[:200],
                        )
                    except Exception as fix_err:
                        logger.error(
                            "Fix callback failed, error=%s", str(fix_err)
                        )
                        # fix_callback 失败时使用原 SQL 重试
                else:
                    logger.info(
                        "No fix_callback provided, retrying with same SQL"
                    )

        # 所有重试均失败
        logger.error(
            "All %d retry attempts exhausted, last_error=%s",
            max_retries,
            str(last_error),
        )
        raise RuntimeError(
            f"Query failed after {max_retries} attempts: {str(last_error)}"
        )
