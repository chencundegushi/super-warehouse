"""
FastAPI 应用入口

配置 CORS 中间件、SSE 支持和路由注册。
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings

# 1.配置日志
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """应用生命周期管理

    Args:
        app: FastAPI 应用实例
    """
    # 启动时执行初始化
    logger.info("Application starting up, initializing resources")
    from app.models.database import init_db, close_db
    await init_db()
    yield
    # 关闭时执行清理
    logger.info("Application shutting down, cleaning up resources")
    await close_db()


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例

    Returns:
        配置完成的 FastAPI 应用
    """
    logger.info(
        "Creating FastAPI application, app_name=%s, version=%s",
        settings.app_name,
        settings.app_version,
    )

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="数仓智能体 - 基于大语言模型的智能数据查询与分析平台",
        lifespan=_lifespan,
    )

    # 2.配置 CORS 中间件，支持前端跨域请求
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 3.注册路由
    _register_routes(app)

    return app


def _register_routes(app: FastAPI) -> None:
    """注册 API 路由

    Args:
        app: FastAPI 应用实例
    """
    # 注册 DDL 管理路由
    from app.api.ddl import router as ddl_router
    app.include_router(ddl_router)

    # 注册对话管理路由
    from app.api.conversations import router as conversations_router
    app.include_router(conversations_router)

    # 注册指标管理路由
    from app.api.metrics import router as metrics_router
    app.include_router(metrics_router)

    # 注册技能管理路由
    from app.api.skills import router as skills_router
    app.include_router(skills_router)

    # 注册文件型技能管理路由
    from app.api.skill_files import router as skill_files_router
    app.include_router(skill_files_router)

    # 注册查询执行路由
    from app.api.query import router as query_router
    app.include_router(query_router)

    # 注册 Chat SSE 流式接口路由
    from app.api.chat import router as chat_router
    app.include_router(chat_router)

    # 注册表血缘关系路由
    from app.api.lineage import router as lineage_router
    app.include_router(lineage_router)

    # 注册系统设置路由
    from app.api.settings import router as settings_router
    app.include_router(settings_router)

    # 注册 Dashboard 智能大屏路由
    from app.api.dashboard import router as dashboard_router
    app.include_router(dashboard_router)

    # 健康检查端点
    @app.get("/health")
    async def health_check():
        """健康检查接口"""
        return JSONResponse(
            content={
                "status": "healthy",
                "app": settings.app_name,
                "version": settings.app_version,
            }
        )

    # SSE 流式输出示例端点（验证 SSE 支持）
    @app.get("/api/sse/test")
    async def sse_test():
        """SSE 流式输出测试接口，验证 Server-Sent Events 支持"""
        from fastapi.responses import StreamingResponse

        async def event_generator():
            """生成 SSE 事件流"""
            import asyncio
            import json

            # 发送测试事件
            event_data = json.dumps({"type": "test", "message": "SSE is working"})
            yield f"data: {event_data}\n\n"
            await asyncio.sleep(0.1)
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    logger.info("Routes registered successfully")


# 创建应用实例
app = create_app()
