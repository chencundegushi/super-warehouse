"""
FastAPI 应用入口测试

验证应用启动、健康检查和 SSE 端点正常工作。
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    """创建异步测试客户端"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_check(client):
    """测试健康检查端点返回正确状态"""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app"] == "Doris Data Agent"
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_sse_endpoint(client):
    """测试 SSE 流式输出端点返回正确的 content-type"""
    response = await client.get("/api/sse/test")
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    # 验证 SSE 数据格式
    assert "data:" in response.text
