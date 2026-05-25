"""
应用配置模块

管理 LLM API Key、Doris 连接信息、超时设置等全局配置。
通过环境变量或 .env 文件加载配置项。
"""

import logging

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """全局配置类，通过环境变量或 .env 文件加载"""

    # 应用基础配置
    app_name: str = "Doris Data Agent"
    app_version: str = "0.1.0"
    debug: bool = False

    # CORS 配置
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # LLM 配置（OpenAI API Compatible）
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 4096

    # Apache Doris 连接配置（MySQL 协议兼容）
    doris_host: str = "localhost"
    doris_port: int = 9030
    doris_user: str = "root"
    doris_password: str = ""
    doris_database: str = "default"

    # 查询执行配置
    query_timeout_seconds: int = 30
    query_max_rows: int = 1000
    query_max_retries: int = 3

    # SQLite 数据库配置
    sqlite_url: str = "sqlite+aiosqlite:///./doris_agent.db"

    # DDL 缓存目录
    ddl_cache_dir: str = "./cache/ddl"

    # 指标匹配阈值
    metric_match_threshold: float = 0.7

    # 技能执行配置
    skill_execution_timeout: int = 30
    skill_max_file_size: int = 1048576  # 1MB
    skill_sandbox_memory_limit: str = "512m"

    # 对话配置
    conversation_max_turns: int = 50
    conversation_page_size: int = 20
    conversation_search_limit: int = 50

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


# 1.创建全局配置单例
settings = Settings()


def get_settings() -> Settings:
    """获取全局配置实例

    Returns:
        全局配置对象
    """
    return settings
