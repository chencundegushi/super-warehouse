"""
Dashboard 服务

管理 Dashboard 的 CRUD 操作、面板管理和布局更新。
提供 Dashboard 创建/获取/更新/删除/列表查询，
Panel 添加/更新/删除，以及批量布局更新功能。

核心约束：
- Dashboard 名称≤64字符且系统内唯一
- 单个 Dashboard 面板数量≤12
- 面板布局约束：pos_x+pos_w≤12, pos_w≥3, pos_h≥2
- 列表按 last_accessed_at 降序排列
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.database import Dashboard, Panel, async_session_factory

logger = logging.getLogger(__name__)


# ============================================================
# 常量定义
# ============================================================

MAX_DASHBOARD_NAME_LENGTH = 64
MAX_PANEL_COUNT = 12
GRID_COLUMNS = 12
MIN_PANEL_WIDTH = 3
MIN_PANEL_HEIGHT = 2


# ============================================================
# 异常定义
# ============================================================


class DashboardError(Exception):
    """Dashboard 服务基础异常"""
    pass


class DashboardNotFoundError(DashboardError):
    """Dashboard 不存在"""
    pass


class DashboardNameConflictError(DashboardError):
    """Dashboard 名称冲突"""
    pass


class DashboardNameTooLongError(DashboardError):
    """Dashboard 名称超长"""
    pass


class PanelLimitExceededError(DashboardError):
    """面板数量超出上限"""
    pass


class PanelNotFoundError(DashboardError):
    """面板不存在"""
    pass


class LayoutConstraintError(DashboardError):
    """布局约束违反"""
    pass



# ============================================================
# 辅助函数
# ============================================================


def _iso_now() -> str:
    """生成当前时间的 ISO 8601 格式字符串（UTC）

    Returns:
        ISO 8601 格式的时间字符串
    """
    return datetime.now(timezone.utc).isoformat()


def _generate_id() -> str:
    """生成 UUID 字符串

    Returns:
        UUID4 字符串
    """
    return str(uuid.uuid4())


def _validate_dashboard_name(name: str) -> None:
    """校验 Dashboard 名称长度

    Args:
        name: Dashboard 名称

    Raises:
        DashboardNameTooLongError: 名称超过64字符
    """
    if not name or not name.strip():
        raise DashboardError("Dashboard name cannot be empty")
    if len(name) > MAX_DASHBOARD_NAME_LENGTH:
        raise DashboardNameTooLongError(
            f"Dashboard name exceeds {MAX_DASHBOARD_NAME_LENGTH} characters"
        )



def _validate_layout_position(pos_x: int, pos_y: int, pos_w: int, pos_h: int) -> None:
    """校验面板布局约束

    约束规则：
    - pos_x + pos_w ≤ 12（不超出网格宽度）
    - pos_w ≥ 3（最小宽度）
    - pos_h ≥ 2（最小高度）

    Args:
        pos_x: 网格X位置
        pos_y: 网格Y位置
        pos_w: 宽度列数
        pos_h: 高度行数

    Raises:
        LayoutConstraintError: 布局约束违反
    """
    if pos_w < MIN_PANEL_WIDTH:
        raise LayoutConstraintError(
            f"Panel width must be >= {MIN_PANEL_WIDTH}, got {pos_w}"
        )
    if pos_h < MIN_PANEL_HEIGHT:
        raise LayoutConstraintError(
            f"Panel height must be >= {MIN_PANEL_HEIGHT}, got {pos_h}"
        )
    if pos_x + pos_w > GRID_COLUMNS:
        raise LayoutConstraintError(
            f"Panel exceeds grid boundary: pos_x({pos_x}) + pos_w({pos_w}) = {pos_x + pos_w} > {GRID_COLUMNS}"
        )
    if pos_x < 0:
        raise LayoutConstraintError(
            f"pos_x must be >= 0, got {pos_x}"
        )
    if pos_y < 0:
        raise LayoutConstraintError(
            f"pos_y must be >= 0, got {pos_y}"
        )



# ============================================================
# Dashboard Service 类
# ============================================================


class DashboardService:
    """Dashboard 服务

    负责 Dashboard 生命周期管理、面板 CRUD 和布局更新。
    所有操作通过异步 SQLAlchemy 会话执行。
    """

    def __init__(self) -> None:
        """初始化 Dashboard 服务"""
        logger.info("DashboardService initialized")

    # ============================================================
    # Dashboard CRUD
    # ============================================================

    async def create_dashboard(
        self, name: str, panels: Optional[list[dict]] = None
    ) -> Dashboard:
        """创建新 Dashboard

        Args:
            name: Dashboard 名称（≤64字符，系统内唯一）
            panels: 可选的初始面板列表

        Returns:
            创建的 Dashboard 对象

        Raises:
            DashboardNameTooLongError: 名称超过64字符
            DashboardNameConflictError: 名称已存在
            PanelLimitExceededError: 初始面板数量超过12
            LayoutConstraintError: 面板布局约束违反
        """
        logger.info("Creating dashboard, name=%s", name)

        # 1.校验名称
        _validate_dashboard_name(name)

        # 2.校验初始面板数量
        if panels and len(panels) > MAX_PANEL_COUNT:
            raise PanelLimitExceededError(
                f"Panel count exceeds limit: {len(panels)} > {MAX_PANEL_COUNT}"
            )

        # 3.校验面板布局约束
        if panels:
            for p in panels:
                _validate_layout_position(
                    p["pos_x"], p["pos_y"], p["pos_w"], p["pos_h"]
                )

        dashboard_id = _generate_id()
        now = _iso_now()

        async with async_session_factory() as session:
            # 4.检查名称唯一性
            existing = await session.execute(
                select(Dashboard).where(Dashboard.name == name)
            )
            if existing.scalar_one_or_none() is not None:
                raise DashboardNameConflictError(
                    f"Dashboard name already exists: {name}"
                )

            # 5.创建 Dashboard 记录
            dashboard = Dashboard(
                id=dashboard_id,
                name=name,
                created_at=now,
                updated_at=now,
                last_accessed_at=now,
                panel_count=len(panels) if panels else 0,
            )
            session.add(dashboard)

            # 6.创建初始面板
            if panels:
                for idx, p in enumerate(panels):
                    panel = Panel(
                        id=_generate_id(),
                        dashboard_id=dashboard_id,
                        title=p["title"],
                        sql=p["sql"],
                        chart_type=p["chart_type"],
                        pos_x=p["pos_x"],
                        pos_y=p["pos_y"],
                        pos_w=p["pos_w"],
                        pos_h=p["pos_h"],
                        sort_order=idx,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(panel)

            await session.commit()
            await session.refresh(dashboard)

        logger.info("Dashboard created successfully, id=%s, name=%s", dashboard_id, name)
        return dashboard

    async def get_dashboard(self, dashboard_id: str) -> Dashboard:
        """获取 Dashboard 详情（含所有面板）

        获取时自动更新 last_accessed_at 时间戳。

        Args:
            dashboard_id: Dashboard ID

        Returns:
            Dashboard 对象（含关联的 panels）

        Raises:
            DashboardNotFoundError: Dashboard 不存在
        """
        logger.info("Getting dashboard, id=%s", dashboard_id)

        async with async_session_factory() as session:
            result = await session.execute(
                select(Dashboard)
                .where(Dashboard.id == dashboard_id)
                .options(selectinload(Dashboard.panels))
            )
            dashboard = result.scalar_one_or_none()

            if dashboard is None:
                raise DashboardNotFoundError(
                    f"Dashboard not found: {dashboard_id}"
                )

            # 更新最近访问时间
            dashboard.last_accessed_at = _iso_now()
            await session.commit()
            await session.refresh(dashboard)

            # 重新加载面板（按 sort_order 排序）
            panels_result = await session.execute(
                select(Panel)
                .where(Panel.dashboard_id == dashboard_id)
                .order_by(Panel.sort_order.asc())
            )
            panels = panels_result.scalars().all()

        # 在 session 外通过 orm 内部 API 设置面板列表，避免触发 lazy load
        from sqlalchemy.orm.attributes import set_committed_value
        set_committed_value(dashboard, "panels", list(panels))

        logger.info("Dashboard retrieved, id=%s, panel_count=%d", dashboard_id, len(panels))
        return dashboard

    async def get_dashboard_readonly(self, dashboard_id: str) -> Dashboard:
        """获取 Dashboard 详情（只读，不更新 last_accessed_at）

        用于面板 SQL 执行等不需要更新访问时间的场景，避免 SQLite 并发写入冲突。

        Args:
            dashboard_id: Dashboard ID

        Returns:
            Dashboard 对象（含关联的 panels）

        Raises:
            DashboardNotFoundError: Dashboard 不存在
        """
        logger.info("Getting dashboard (readonly), id=%s", dashboard_id)

        async with async_session_factory() as session:
            result = await session.execute(
                select(Dashboard)
                .where(Dashboard.id == dashboard_id)
                .options(selectinload(Dashboard.panels))
            )
            dashboard = result.scalar_one_or_none()

            if dashboard is None:
                raise DashboardNotFoundError(
                    f"Dashboard not found: {dashboard_id}"
                )

            # 加载面板（按 sort_order 排序）
            panels_result = await session.execute(
                select(Panel)
                .where(Panel.dashboard_id == dashboard_id)
                .order_by(Panel.sort_order.asc())
            )
            panels = panels_result.scalars().all()

        from sqlalchemy.orm.attributes import set_committed_value
        set_committed_value(dashboard, "panels", list(panels))

        logger.info("Dashboard retrieved (readonly), id=%s, panel_count=%d", dashboard_id, len(panels))
        return dashboard

    async def update_dashboard(
        self, dashboard_id: str, name: Optional[str] = None
    ) -> Dashboard:
        """更新 Dashboard 基本信息（名称）

        Args:
            dashboard_id: Dashboard ID
            name: 新名称（可选）

        Returns:
            更新后的 Dashboard 对象

        Raises:
            DashboardNotFoundError: Dashboard 不存在
            DashboardNameTooLongError: 名称超过64字符
            DashboardNameConflictError: 名称已被其他 Dashboard 使用
        """
        logger.info("Updating dashboard, id=%s, new_name=%s", dashboard_id, name)

        async with async_session_factory() as session:
            result = await session.execute(
                select(Dashboard).where(Dashboard.id == dashboard_id)
            )
            dashboard = result.scalar_one_or_none()

            if dashboard is None:
                raise DashboardNotFoundError(
                    f"Dashboard not found: {dashboard_id}"
                )

            if name is not None:
                # 校验名称
                _validate_dashboard_name(name)

                # 检查名称唯一性（排除自身）
                conflict = await session.execute(
                    select(Dashboard).where(
                        Dashboard.name == name,
                        Dashboard.id != dashboard_id,
                    )
                )
                if conflict.scalar_one_or_none() is not None:
                    raise DashboardNameConflictError(
                        f"Dashboard name already exists: {name}"
                    )

                dashboard.name = name

            dashboard.updated_at = _iso_now()
            await session.commit()
            await session.refresh(dashboard)

        logger.info("Dashboard updated successfully, id=%s", dashboard_id)
        return dashboard

    async def delete_dashboard(self, dashboard_id: str) -> None:
        """删除 Dashboard 及其所有面板

        Args:
            dashboard_id: Dashboard ID

        Raises:
            DashboardNotFoundError: Dashboard 不存在
        """
        logger.info("Deleting dashboard, id=%s", dashboard_id)

        async with async_session_factory() as session:
            result = await session.execute(
                select(Dashboard).where(Dashboard.id == dashboard_id)
            )
            dashboard = result.scalar_one_or_none()

            if dashboard is None:
                raise DashboardNotFoundError(
                    f"Dashboard not found: {dashboard_id}"
                )

            # 删除关联面板（CASCADE 会自动处理，但显式删除更清晰）
            await session.execute(
                delete(Panel).where(Panel.dashboard_id == dashboard_id)
            )
            # 删除 Dashboard
            await session.execute(
                delete(Dashboard).where(Dashboard.id == dashboard_id)
            )
            await session.commit()

        logger.info("Dashboard deleted successfully, id=%s", dashboard_id)

    async def list_dashboards(
        self, page: int = 1, page_size: int = 20
    ) -> dict:
        """分页查询 Dashboard 列表，按 last_accessed_at 降序排列

        Args:
            page: 页码（从1开始）
            page_size: 每页条数

        Returns:
            分页结果字典，包含 items、total、page、page_size
        """
        offset = (page - 1) * page_size
        logger.info("Listing dashboards, page=%d, page_size=%d", page, page_size)

        async with async_session_factory() as session:
            # 1.查询总数
            count_stmt = select(func.count(Dashboard.id))
            total_result = await session.execute(count_stmt)
            total = total_result.scalar() or 0

            # 2.分页查询，按 last_accessed_at 降序
            query_stmt = (
                select(Dashboard)
                .order_by(Dashboard.last_accessed_at.desc())
                .offset(offset)
                .limit(page_size)
            )
            result = await session.execute(query_stmt)
            dashboards = result.scalars().all()

        # 3.构建摘要列表
        items = [
            {
                "id": d.id,
                "name": d.name,
                "created_at": d.created_at,
                "updated_at": d.updated_at,
                "last_accessed_at": d.last_accessed_at,
                "panel_count": d.panel_count,
            }
            for d in dashboards
        ]

        logger.info("Listed dashboards, total=%d, returned=%d", total, len(items))
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # ============================================================
    # Panel 管理
    # ============================================================

    async def add_panel(
        self,
        dashboard_id: str,
        title: str,
        sql: str,
        chart_type: str,
        pos_x: int,
        pos_y: int,
        pos_w: int,
        pos_h: int,
    ) -> Panel:
        """向 Dashboard 添加面板

        Args:
            dashboard_id: Dashboard ID
            title: 面板标题
            sql: 查询 SQL
            chart_type: 图表类型（table/bar/line/pie）
            pos_x: 网格X位置（0-11）
            pos_y: 网格Y位置
            pos_w: 宽度列数（≥3）
            pos_h: 高度行数（≥2）

        Returns:
            创建的 Panel 对象

        Raises:
            DashboardNotFoundError: Dashboard 不存在
            PanelLimitExceededError: 面板数量已达上限
            LayoutConstraintError: 布局约束违反
        """
        logger.info(
            "Adding panel to dashboard, dashboard_id=%s, title=%s",
            dashboard_id, title,
        )

        # 1.校验布局约束
        _validate_layout_position(pos_x, pos_y, pos_w, pos_h)

        async with async_session_factory() as session:
            # 2.获取 Dashboard 并检查面板数量
            result = await session.execute(
                select(Dashboard).where(Dashboard.id == dashboard_id)
            )
            dashboard = result.scalar_one_or_none()

            if dashboard is None:
                raise DashboardNotFoundError(
                    f"Dashboard not found: {dashboard_id}"
                )

            if dashboard.panel_count >= MAX_PANEL_COUNT:
                raise PanelLimitExceededError(
                    f"Dashboard panel limit reached: {dashboard.panel_count} >= {MAX_PANEL_COUNT}"
                )

            # 3.确定排序序号
            max_order_result = await session.execute(
                select(func.max(Panel.sort_order))
                .where(Panel.dashboard_id == dashboard_id)
            )
            max_order = max_order_result.scalar() or 0
            new_sort_order = max_order + 1

            # 4.创建面板
            now = _iso_now()
            panel_id = _generate_id()
            panel = Panel(
                id=panel_id,
                dashboard_id=dashboard_id,
                title=title,
                sql=sql,
                chart_type=chart_type,
                pos_x=pos_x,
                pos_y=pos_y,
                pos_w=pos_w,
                pos_h=pos_h,
                sort_order=new_sort_order,
                created_at=now,
                updated_at=now,
            )
            session.add(panel)

            # 5.更新 Dashboard 面板计数和修改时间
            dashboard.panel_count = dashboard.panel_count + 1
            dashboard.updated_at = now
            await session.commit()
            await session.refresh(panel)

        logger.info("Panel added successfully, panel_id=%s, dashboard_id=%s", panel_id, dashboard_id)
        return panel

    async def update_panel(
        self,
        dashboard_id: str,
        panel_id: str,
        title: Optional[str] = None,
        sql: Optional[str] = None,
        chart_type: Optional[str] = None,
        pos_x: Optional[int] = None,
        pos_y: Optional[int] = None,
        pos_w: Optional[int] = None,
        pos_h: Optional[int] = None,
    ) -> Panel:
        """更新面板配置

        Args:
            dashboard_id: Dashboard ID
            panel_id: Panel ID
            title: 新标题（可选）
            sql: 新 SQL（可选）
            chart_type: 新图表类型（可选）
            pos_x: 新X位置（可选）
            pos_y: 新Y位置（可选）
            pos_w: 新宽度（可选）
            pos_h: 新高度（可选）

        Returns:
            更新后的 Panel 对象

        Raises:
            DashboardNotFoundError: Dashboard 不存在
            PanelNotFoundError: Panel 不存在
            LayoutConstraintError: 布局约束违反
        """
        logger.info(
            "Updating panel, dashboard_id=%s, panel_id=%s",
            dashboard_id, panel_id,
        )

        async with async_session_factory() as session:
            # 1.验证 Dashboard 存在
            dash_result = await session.execute(
                select(Dashboard).where(Dashboard.id == dashboard_id)
            )
            if dash_result.scalar_one_or_none() is None:
                raise DashboardNotFoundError(
                    f"Dashboard not found: {dashboard_id}"
                )

            # 2.获取面板
            panel_result = await session.execute(
                select(Panel).where(
                    Panel.id == panel_id,
                    Panel.dashboard_id == dashboard_id,
                )
            )
            panel = panel_result.scalar_one_or_none()

            if panel is None:
                raise PanelNotFoundError(
                    f"Panel not found: {panel_id} in dashboard {dashboard_id}"
                )

            # 3.计算最终布局值并校验约束
            final_pos_x = pos_x if pos_x is not None else panel.pos_x
            final_pos_y = pos_y if pos_y is not None else panel.pos_y
            final_pos_w = pos_w if pos_w is not None else panel.pos_w
            final_pos_h = pos_h if pos_h is not None else panel.pos_h

            # 仅当布局参数有变更时校验
            if any(v is not None for v in [pos_x, pos_y, pos_w, pos_h]):
                _validate_layout_position(
                    final_pos_x, final_pos_y, final_pos_w, final_pos_h
                )

            # 4.更新字段
            if title is not None:
                panel.title = title
            if sql is not None:
                panel.sql = sql
            if chart_type is not None:
                panel.chart_type = chart_type
            if pos_x is not None:
                panel.pos_x = pos_x
            if pos_y is not None:
                panel.pos_y = pos_y
            if pos_w is not None:
                panel.pos_w = pos_w
            if pos_h is not None:
                panel.pos_h = pos_h

            panel.updated_at = _iso_now()
            await session.commit()
            await session.refresh(panel)

        logger.info("Panel updated successfully, panel_id=%s", panel_id)
        return panel

    async def remove_panel(self, dashboard_id: str, panel_id: str) -> None:
        """从 Dashboard 中删除面板

        Args:
            dashboard_id: Dashboard ID
            panel_id: Panel ID

        Raises:
            DashboardNotFoundError: Dashboard 不存在
            PanelNotFoundError: Panel 不存在
        """
        logger.info(
            "Removing panel, dashboard_id=%s, panel_id=%s",
            dashboard_id, panel_id,
        )

        async with async_session_factory() as session:
            # 1.验证 Dashboard 存在
            dash_result = await session.execute(
                select(Dashboard).where(Dashboard.id == dashboard_id)
            )
            dashboard = dash_result.scalar_one_or_none()

            if dashboard is None:
                raise DashboardNotFoundError(
                    f"Dashboard not found: {dashboard_id}"
                )

            # 2.验证面板存在
            panel_result = await session.execute(
                select(Panel).where(
                    Panel.id == panel_id,
                    Panel.dashboard_id == dashboard_id,
                )
            )
            panel = panel_result.scalar_one_or_none()

            if panel is None:
                raise PanelNotFoundError(
                    f"Panel not found: {panel_id} in dashboard {dashboard_id}"
                )

            # 3.删除面板
            await session.execute(
                delete(Panel).where(Panel.id == panel_id)
            )

            # 4.更新 Dashboard 面板计数和修改时间
            dashboard.panel_count = max(0, dashboard.panel_count - 1)
            dashboard.updated_at = _iso_now()
            await session.commit()

        logger.info("Panel removed successfully, panel_id=%s", panel_id)

    # ============================================================
    # 布局更新
    # ============================================================

    async def update_layout(
        self, dashboard_id: str, layout: list[dict]
    ) -> None:
        """批量更新面板布局位置

        Args:
            dashboard_id: Dashboard ID
            layout: 布局列表，每项包含 panel_id, pos_x, pos_y, pos_w, pos_h

        Raises:
            DashboardNotFoundError: Dashboard 不存在
            PanelNotFoundError: 布局中引用的面板不存在
            LayoutConstraintError: 布局约束违反
        """
        logger.info(
            "Updating layout, dashboard_id=%s, panel_count=%d",
            dashboard_id, len(layout),
        )

        # 1.校验所有布局项的约束
        for item in layout:
            _validate_layout_position(
                item["pos_x"], item["pos_y"], item["pos_w"], item["pos_h"]
            )

        async with async_session_factory() as session:
            # 2.验证 Dashboard 存在
            dash_result = await session.execute(
                select(Dashboard).where(Dashboard.id == dashboard_id)
            )
            dashboard = dash_result.scalar_one_or_none()

            if dashboard is None:
                raise DashboardNotFoundError(
                    f"Dashboard not found: {dashboard_id}"
                )

            # 3.逐个更新面板布局
            for item in layout:
                panel_result = await session.execute(
                    select(Panel).where(
                        Panel.id == item["panel_id"],
                        Panel.dashboard_id == dashboard_id,
                    )
                )
                panel = panel_result.scalar_one_or_none()

                if panel is None:
                    raise PanelNotFoundError(
                        f"Panel not found: {item['panel_id']} in dashboard {dashboard_id}"
                    )

                panel.pos_x = item["pos_x"]
                panel.pos_y = item["pos_y"]
                panel.pos_w = item["pos_w"]
                panel.pos_h = item["pos_h"]
                panel.updated_at = _iso_now()

            # 4.更新 Dashboard 修改时间
            dashboard.updated_at = _iso_now()
            await session.commit()

        logger.info("Layout updated successfully, dashboard_id=%s", dashboard_id)


# 全局单例
dashboard_service = DashboardService()
