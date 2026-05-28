"""
表血缘关系分析服务

通过查询 Doris 的 jobs 列表，利用 LLM 分析表之间的层级关系和 ETL 调度周期。
分析结果缓存到本地 JSON 文件，供前端展示。
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

import aiomysql
from langchain_openai import ChatOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

# 缓存目录
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "lineage"


class LineageService:
    """表血缘关系分析服务

    负责从 Doris 查询 ETL Job 列表，调用 LLM 分析表层级关系，
    并将结果缓存到本地 JSON 文件。

    Attributes:
        _llm: ChatOpenAI 实例
        _cache_file: 缓存文件路径
    """

    def __init__(self) -> None:
        """初始化血缘分析服务"""
        self._llm = ChatOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            temperature=0.0,
            max_tokens=settings.llm_max_tokens,
        )
        self._cache_file = CACHE_DIR / "table_lineage.json"
        logger.info(
            "LineageService initialized, cache_file=%s", self._cache_file
        )

    async def _query_jobs(self) -> list[dict]:
        """从 Doris 查询 ETL Job 列表

        执行 select * from jobs("type"="insert") 获取所有 insert 类型的 job。

        Returns:
            Job 列表，每个 job 为字典

        Raises:
            ConnectionError: 连接 Doris 失败
            RuntimeError: 查询执行失败
        """
        logger.info("Querying Doris jobs list, host=%s, port=%d", settings.doris_host, settings.doris_port)
        conn: Optional[aiomysql.Connection] = None
        try:
            conn = await aiomysql.connect(
                host=settings.doris_host,
                port=settings.doris_port,
                user=settings.doris_user,
                password=settings.doris_password,
                db=settings.doris_database,
                autocommit=True,
            )
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                sql = 'select * from jobs("type"="insert")'
                logger.info("Executing jobs query, sql=%s", sql)
                await cursor.execute(sql)
                rows = await cursor.fetchall()
                logger.info("Jobs query completed, row_count=%d", len(rows))
                return rows
        except Exception as e:
            logger.error("Failed to query jobs from Doris, error=%s", str(e))
            raise RuntimeError(f"Failed to query jobs: {str(e)}") from e
        finally:
            if conn:
                conn.close()

    async def _analyze_with_llm(self, jobs: list[dict]) -> dict:
        """调用 LLM 分析 Job 列表中的表层级关系

        将 Job 列表发送给 LLM，分析出表之间的血缘关系、所属层级和调度周期。

        Args:
            jobs: Doris Job 列表

        Returns:
            LLM 分析结果，包含层级关系树结构

        Raises:
            RuntimeError: LLM 调用失败
        """
        logger.info("Analyzing table lineage with LLM, jobs_count=%d", len(jobs))

        # 1.序列化 job 数据（处理不可序列化的字段）
        jobs_text = self._serialize_jobs(jobs)

        # 2.构建 prompt
        prompt = f"""你是一个数据仓库专家。请分析以下 Doris 数据库的 ETL Job 列表，识别出表之间的层级关系（血缘关系）和调度周期。

## Job 列表数据：
{jobs_text}

## 分析要求：
1. 从每个 Job 的 SQL 语句中识别出源表（FROM/JOIN 中的表）和目标表（INSERT INTO 的表）
2. 根据表名前缀判断所属层级：
   - ODS层：ods_ 前缀，原始数据层
   - DWD层：dwd_ 前缀，明细数据层
   - DWS层：dws_ 前缀，汇总数据层
   - ADS层：ads_ 前缀，应用数据层
   - DIM层：dim_ 前缀，维度表
   - 其他：无法识别前缀的表
3. 识别每个 Job 的调度周期（从 Job 名称或配置中推断）

## 输出格式要求：
请严格按照以下 JSON 格式输出，不要输出其他内容：
```json
{{
  "layers": [
    {{
      "name": "ODS",
      "level": 0,
      "description": "原始数据层",
      "tables": ["ods_table1", "ods_table2"]
    }},
    {{
      "name": "DWD",
      "level": 1,
      "description": "明细数据层",
      "tables": ["dwd_table1"]
    }},
    {{
      "name": "DWS",
      "level": 2,
      "description": "汇总数据层",
      "tables": ["dws_table1"]
    }},
    {{
      "name": "ADS",
      "level": 3,
      "description": "应用数据层",
      "tables": ["ads_table1"]
    }}
  ],
  "edges": [
    {{
      "source": "ods_table1",
      "target": "dwd_table1",
      "job_name": "job名称",
      "schedule": "调度周期描述，如：每天/每小时/每周等"
    }}
  ],
  "tables": [
    {{
      "name": "表名",
      "layer": "所属层级(ODS/DWD/DWS/ADS/DIM/OTHER)",
      "description": "表用途描述"
    }}
  ]
}}
```
"""

        try:
            # 3.调用 LLM
            response = await self._llm.ainvoke(prompt)
            content = response.content
            logger.info("LLM analysis completed, response_length=%d", len(content))

            # 4.解析 JSON 结果
            result = self._parse_llm_response(content)
            return result
        except Exception as e:
            logger.error("LLM analysis failed, error=%s", str(e))
            raise RuntimeError(f"LLM analysis failed: {str(e)}") from e

    def _serialize_jobs(self, jobs: list[dict]) -> str:
        """序列化 Job 列表为文本格式

        处理不可 JSON 序列化的字段（如 datetime），转为字符串。

        Args:
            jobs: Job 列表

        Returns:
            格式化的 Job 文本
        """
        serializable_jobs = []
        for job in jobs:
            clean_job = {}
            for key, value in job.items():
                try:
                    json.dumps(value)
                    clean_job[key] = value
                except (TypeError, ValueError):
                    clean_job[key] = str(value)
            serializable_jobs.append(clean_job)
        return json.dumps(serializable_jobs, ensure_ascii=False, indent=2)

    def _parse_llm_response(self, content: str) -> dict:
        """解析 LLM 返回的 JSON 内容

        从 LLM 响应中提取 JSON 数据，支持 markdown 代码块格式。

        Args:
            content: LLM 响应文本

        Returns:
            解析后的字典

        Raises:
            ValueError: JSON 解析失败
        """
        # 1.尝试提取 markdown 代码块中的 JSON
        if "```json" in content:
            start = content.index("```json") + 7
            end = content.index("```", start)
            json_str = content[start:end].strip()
        elif "```" in content:
            start = content.index("```") + 3
            end = content.index("```", start)
            json_str = content[start:end].strip()
        else:
            json_str = content.strip()

        try:
            result = json.loads(json_str)
            logger.info("LLM response parsed successfully")
            return result
        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM response as JSON, error=%s", str(e))
            raise ValueError(f"Failed to parse LLM response: {str(e)}") from e

    def _save_cache(self, data: dict) -> None:
        """保存分析结果到缓存文件

        Args:
            data: 分析结果数据
        """
        # 1.确保缓存目录存在
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # 2.写入 JSON 文件
        with open(self._cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("Lineage cache saved, file=%s", self._cache_file)

    def _load_cache(self) -> Optional[dict]:
        """从缓存文件加载分析结果

        Returns:
            缓存数据，文件不存在时返回 None
        """
        if not self._cache_file.exists():
            logger.info("No lineage cache found")
            return None
        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info("Lineage cache loaded, file=%s", self._cache_file)
            return data
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Failed to load lineage cache, error=%s", str(e))
            return None

    async def analyze_lineage(self, force_refresh: bool = False) -> dict:
        """分析表血缘关系（主入口）

        如果缓存存在且不强制刷新，直接返回缓存数据。
        否则查询 Doris Job 列表并调用 LLM 分析。

        Args:
            force_refresh: 是否强制刷新（忽略缓存）

        Returns:
            表血缘关系分析结果
        """
        logger.info("Analyzing lineage, force_refresh=%s", force_refresh)

        # 1.检查缓存
        if not force_refresh:
            cached = self._load_cache()
            if cached:
                return cached

        # 2.查询 Doris Job 列表
        jobs = await self._query_jobs()

        # 3.调用 LLM 分析
        result = await self._analyze_with_llm(jobs)

        # 4.保存缓存
        self._save_cache(result)

        return result

    async def get_jobs_raw(self) -> list[dict]:
        """获取原始 Job 列表数据

        Returns:
            Doris Job 列表
        """
        return await self._query_jobs()
