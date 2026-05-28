"""
Dashboard Service 单元测试

验证 Dashboard CRUD、面板管理、布局更新和约束校验功能。
使用内存数据库隔离测试环境。
"""

import pytest
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.database import Base
from app.services.dashboard_service import (
    DashboardService,
    DashboardError,
    DashboardNameConflictError,
    DashboardNameTooLongError,
    DashboardNotFoundError,
    LayoutConstraintError,
    PanelLimitExceededError,
    PanelNotFoundError,
    _validate_layout_position,
)


@pytest.fixture
async def test_engine():
    """创建内存数据库引擎用于测试"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def test_session_factory(test_engine):
    """创建测试用会话工厂"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    return factory


@pytest.fixture
async def service(test_session_factory):
    """创建使用测试数据库的 DashboardService 实例"""
    svc = DashboardService()
    with patch(
        "app.services.dashboard_service.async_session_factory",
        test_session_factory,
    ):
        yield svc


def _make_panel(
    title="测试面板",
    sql="SELECT COUNT(*) FROM orders",
    chart_type="bar",
    pos_x=0,
    pos_y=0,
    pos_w=4,
    pos_h=3,
):
    """构造面板字典的辅助函数"""
    return {
        "title": title,
        "sql": sql,
        "chart_type": chart_type,
        "pos_x": pos_x,
        "pos_y": pos_y,
        "pos_w": pos_w,
        "pos_h": pos_h,
    }


class TestDashboardCRUD:
    """验证 Dashboard CRUD 操作"""

    async def test_create_dashboard(self, service, test_session_factory):
        """测试创建 Dashboard"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            dashboard = await service.create_dashboard(name="月度报表")
            assert dashboard.name == "月度报表"
            assert dashboard.panel_count == 0
            assert dashboard.id is not None
            assert dashboard.created_at is not None

    async def test_create_dashboard_with_panels(self, service, test_session_factory):
        """测试创建带初始面板的 Dashboard"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            panels = [
                _make_panel(title="面板1", pos_x=0),
                _make_panel(title="面板2", pos_x=4),
            ]
            dashboard = await service.create_dashboard(
                name="带面板大屏", panels=panels
            )
            assert dashboard.panel_count == 2

    async def test_create_dashboard_name_too_long(self, service, test_session_factory):
        """测试名称超过64字符时抛出异常"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            long_name = "a" * 65
            with pytest.raises(DashboardNameTooLongError):
                await service.create_dashboard(name=long_name)

    async def test_create_dashboard_name_conflict(self, service, test_session_factory):
        """测试名称冲突时抛出异常"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            await service.create_dashboard(name="唯一名称")
            with pytest.raises(DashboardNameConflictError):
                await service.create_dashboard(name="唯一名称")

    async def test_create_dashboard_empty_name(self, service, test_session_factory):
        """测试空名称时抛出异常"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            with pytest.raises(DashboardError):
                await service.create_dashboard(name="")

    async def test_get_dashboard(self, service, test_session_factory):
        """测试获取 Dashboard 详情"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            created = await service.create_dashboard(name="获取测试")
            fetched = await service.get_dashboard(created.id)
            assert fetched.id == created.id
            assert fetched.name == "获取测试"

    async def test_get_dashboard_not_found(self, service, test_session_factory):
        """测试获取不存在的 Dashboard 抛出异常"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            with pytest.raises(DashboardNotFoundError):
                await service.get_dashboard("non-existent-id")

    async def test_get_dashboard_updates_last_accessed(
        self, service, test_session_factory
    ):
        """测试获取 Dashboard 时更新 last_accessed_at"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            created = await service.create_dashboard(name="访问时间测试")
            original_accessed = created.last_accessed_at

            import asyncio
            await asyncio.sleep(0.01)

            fetched = await service.get_dashboard(created.id)
            assert fetched.last_accessed_at >= original_accessed

    async def test_update_dashboard_name(self, service, test_session_factory):
        """测试更新 Dashboard 名称"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            created = await service.create_dashboard(name="旧名称")
            updated = await service.update_dashboard(created.id, name="新名称")
            assert updated.name == "新名称"

    async def test_update_dashboard_name_conflict(self, service, test_session_factory):
        """测试更新名称冲突时抛出异常"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            await service.create_dashboard(name="已存在")
            d2 = await service.create_dashboard(name="待改名")
            with pytest.raises(DashboardNameConflictError):
                await service.update_dashboard(d2.id, name="已存在")

    async def test_delete_dashboard(self, service, test_session_factory):
        """测试删除 Dashboard"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            created = await service.create_dashboard(name="待删除")
            await service.delete_dashboard(created.id)
            with pytest.raises(DashboardNotFoundError):
                await service.get_dashboard(created.id)

    async def test_delete_dashboard_not_found(self, service, test_session_factory):
        """测试删除不存在的 Dashboard 抛出异常"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            with pytest.raises(DashboardNotFoundError):
                await service.delete_dashboard("non-existent-id")


class TestListDashboards:
    """验证 Dashboard 列表查询"""

    async def test_list_dashboards_empty(self, service, test_session_factory):
        """测试空列表"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            result = await service.list_dashboards()
            assert result["total"] == 0
            assert result["items"] == []

    async def test_list_dashboards_pagination(self, service, test_session_factory):
        """测试分页查询"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            for i in range(5):
                await service.create_dashboard(name=f"大屏{i}")

            result = await service.list_dashboards(page=1, page_size=3)
            assert result["total"] == 5
            assert len(result["items"]) == 3
            assert result["page"] == 1

    async def test_list_dashboards_ordered_by_last_accessed(
        self, service, test_session_factory
    ):
        """测试按 last_accessed_at 降序排列"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            d1 = await service.create_dashboard(name="旧大屏")
            d2 = await service.create_dashboard(name="新大屏")

            import asyncio
            await asyncio.sleep(0.01)

            # 访问 d1 使其 last_accessed_at 更新
            await service.get_dashboard(d1.id)

            result = await service.list_dashboards()
            assert result["items"][0]["name"] == "旧大屏"


class TestPanelManagement:
    """验证面板管理功能"""

    async def test_add_panel(self, service, test_session_factory):
        """测试添加面板"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            dashboard = await service.create_dashboard(name="面板测试")
            panel = await service.add_panel(
                dashboard_id=dashboard.id,
                title="充值趋势",
                sql="SELECT date, SUM(amount) FROM recharge GROUP BY date",
                chart_type="line",
                pos_x=0,
                pos_y=0,
                pos_w=6,
                pos_h=3,
            )
            assert panel.title == "充值趋势"
            assert panel.chart_type == "line"
            assert panel.pos_w == 6

    async def test_add_panel_updates_count(self, service, test_session_factory):
        """测试添加面板后更新 panel_count"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            dashboard = await service.create_dashboard(name="计数测试")
            await service.add_panel(
                dashboard_id=dashboard.id,
                title="面板1",
                sql="SELECT 1",
                chart_type="table",
                pos_x=0, pos_y=0, pos_w=4, pos_h=2,
            )
            # 重新获取验证计数
            fetched = await service.get_dashboard(dashboard.id)
            assert fetched.panel_count == 1

    async def test_add_panel_exceeds_limit(self, service, test_session_factory):
        """测试面板数量超过12时抛出异常"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            dashboard = await service.create_dashboard(name="上限测试")
            # 添加12个面板
            for i in range(12):
                await service.add_panel(
                    dashboard_id=dashboard.id,
                    title=f"面板{i}",
                    sql="SELECT 1",
                    chart_type="table",
                    pos_x=(i % 3) * 4,
                    pos_y=(i // 3) * 2,
                    pos_w=4,
                    pos_h=2,
                )
            # 第13个应该失败
            with pytest.raises(PanelLimitExceededError):
                await service.add_panel(
                    dashboard_id=dashboard.id,
                    title="超限面板",
                    sql="SELECT 1",
                    chart_type="table",
                    pos_x=0, pos_y=10, pos_w=4, pos_h=2,
                )

    async def test_add_panel_invalid_layout(self, service, test_session_factory):
        """测试布局约束违反时抛出异常"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            dashboard = await service.create_dashboard(name="布局测试")
            # pos_x + pos_w > 12
            with pytest.raises(LayoutConstraintError):
                await service.add_panel(
                    dashboard_id=dashboard.id,
                    title="超宽面板",
                    sql="SELECT 1",
                    chart_type="table",
                    pos_x=10, pos_y=0, pos_w=4, pos_h=2,
                )

    async def test_update_panel(self, service, test_session_factory):
        """测试更新面板"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            dashboard = await service.create_dashboard(name="更新面板测试")
            panel = await service.add_panel(
                dashboard_id=dashboard.id,
                title="原标题",
                sql="SELECT 1",
                chart_type="bar",
                pos_x=0, pos_y=0, pos_w=4, pos_h=3,
            )
            updated = await service.update_panel(
                dashboard_id=dashboard.id,
                panel_id=panel.id,
                title="新标题",
                chart_type="line",
            )
            assert updated.title == "新标题"
            assert updated.chart_type == "line"
            # 未修改的字段保持不变
            assert updated.pos_w == 4

    async def test_update_panel_layout_constraint(self, service, test_session_factory):
        """测试更新面板时布局约束校验"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            dashboard = await service.create_dashboard(name="约束测试")
            panel = await service.add_panel(
                dashboard_id=dashboard.id,
                title="面板",
                sql="SELECT 1",
                chart_type="bar",
                pos_x=0, pos_y=0, pos_w=4, pos_h=3,
            )
            # pos_w < 3 应该失败
            with pytest.raises(LayoutConstraintError):
                await service.update_panel(
                    dashboard_id=dashboard.id,
                    panel_id=panel.id,
                    pos_w=2,
                )

    async def test_remove_panel(self, service, test_session_factory):
        """测试删除面板"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            dashboard = await service.create_dashboard(name="删除面板测试")
            panel = await service.add_panel(
                dashboard_id=dashboard.id,
                title="待删除面板",
                sql="SELECT 1",
                chart_type="table",
                pos_x=0, pos_y=0, pos_w=4, pos_h=2,
            )
            await service.remove_panel(dashboard.id, panel.id)

            # 验证面板已删除
            fetched = await service.get_dashboard(dashboard.id)
            assert fetched.panel_count == 0
            assert len(fetched.panels) == 0

    async def test_remove_panel_not_found(self, service, test_session_factory):
        """测试删除不存在的面板抛出异常"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            dashboard = await service.create_dashboard(name="面板不存在测试")
            with pytest.raises(PanelNotFoundError):
                await service.remove_panel(dashboard.id, "non-existent-panel")


class TestLayoutUpdate:
    """验证布局更新功能"""

    async def test_update_layout(self, service, test_session_factory):
        """测试批量更新布局"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            dashboard = await service.create_dashboard(name="布局更新测试")
            p1 = await service.add_panel(
                dashboard_id=dashboard.id,
                title="面板1",
                sql="SELECT 1",
                chart_type="bar",
                pos_x=0, pos_y=0, pos_w=4, pos_h=3,
            )
            p2 = await service.add_panel(
                dashboard_id=dashboard.id,
                title="面板2",
                sql="SELECT 2",
                chart_type="line",
                pos_x=4, pos_y=0, pos_w=4, pos_h=3,
            )

            # 更新布局
            layout = [
                {"panel_id": p1.id, "pos_x": 0, "pos_y": 0, "pos_w": 6, "pos_h": 4},
                {"panel_id": p2.id, "pos_x": 6, "pos_y": 0, "pos_w": 6, "pos_h": 4},
            ]
            await service.update_layout(dashboard.id, layout)

            # 验证布局已更新
            fetched = await service.get_dashboard(dashboard.id)
            panel_map = {p.id: p for p in fetched.panels}
            assert panel_map[p1.id].pos_w == 6
            assert panel_map[p1.id].pos_h == 4
            assert panel_map[p2.id].pos_x == 6

    async def test_update_layout_constraint_violation(
        self, service, test_session_factory
    ):
        """测试布局更新时约束违反"""
        with patch(
            "app.services.dashboard_service.async_session_factory",
            test_session_factory,
        ):
            dashboard = await service.create_dashboard(name="约束违反测试")
            p1 = await service.add_panel(
                dashboard_id=dashboard.id,
                title="面板1",
                sql="SELECT 1",
                chart_type="bar",
                pos_x=0, pos_y=0, pos_w=4, pos_h=3,
            )
            # pos_x + pos_w > 12
            layout = [
                {"panel_id": p1.id, "pos_x": 10, "pos_y": 0, "pos_w": 4, "pos_h": 3},
            ]
            with pytest.raises(LayoutConstraintError):
                await service.update_layout(dashboard.id, layout)


class TestLayoutValidation:
    """验证布局约束校验函数"""

    def test_valid_layout(self):
        """测试合法布局不抛出异常"""
        _validate_layout_position(0, 0, 4, 3)
        _validate_layout_position(8, 0, 4, 2)
        _validate_layout_position(0, 5, 12, 2)

    def test_pos_w_too_small(self):
        """测试宽度小于3时抛出异常"""
        with pytest.raises(LayoutConstraintError):
            _validate_layout_position(0, 0, 2, 3)

    def test_pos_h_too_small(self):
        """测试高度小于2时抛出异常"""
        with pytest.raises(LayoutConstraintError):
            _validate_layout_position(0, 0, 4, 1)

    def test_exceeds_grid_width(self):
        """测试超出网格宽度时抛出异常"""
        with pytest.raises(LayoutConstraintError):
            _validate_layout_position(10, 0, 4, 3)

    def test_negative_pos_x(self):
        """测试负数 pos_x 时抛出异常"""
        with pytest.raises(LayoutConstraintError):
            _validate_layout_position(-1, 0, 4, 3)
