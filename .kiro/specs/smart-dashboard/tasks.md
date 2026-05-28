# Implementation Plan: Smart Dashboard（智能大屏）

## Overview

基于设计文档的架构，将智能大屏功能拆分为后端服务层（Dashboard Service + Agent Tool）和前端展示层（列表页 + 查看页 + 构建器）。后端复用现有 SQL Generator、Query Executor、Visualization Engine 等模块；前端引入 react-grid-layout 实现拖拽布局。按模块逐步实现，确保增量可验证。

## Tasks

- [x] 1. 数据模型与基础服务
  - [x] 1.1 创建 Dashboard 数据库模型
    - 在 `backend/app/models/database.py` 中新增 Dashboard 和 Panel ORM 模型
    - Dashboard 表：id, name(UNIQUE), created_at, updated_at, last_accessed_at, panel_count
    - Panel 表：id, dashboard_id(FK), title, sql, chart_type, pos_x, pos_y, pos_w, pos_h, sort_order, created_at, updated_at
    - 确保应用启动时自动建表
    - _Requirements: 3.1, 3.2_

  - [x] 1.2 实现 Dashboard Service（后端）
    - 创建 `backend/app/services/dashboard_service.py`
    - 实现 Dashboard CRUD：create_dashboard(), get_dashboard(), update_dashboard(), delete_dashboard(), list_dashboards()
    - 实现 Panel 管理：add_panel(), update_panel(), remove_panel()
    - 实现布局更新：update_layout()
    - 创建验证：名称≤64字符且唯一、面板数量≤12、布局约束（pos_x+pos_w≤12, pos_w≥3, pos_h≥2）
    - 列表按 last_accessed_at 降序排列
    - _Requirements: 3.1, 3.2, 3.5, 3.6, 3.7, 3.8, 2.8_

  - [x] 1.3 实现 Dashboard API 路由
    - 创建 `backend/app/api/dashboard.py`
    - POST /api/dashboards - 创建 Dashboard
    - GET /api/dashboards - 列表查询（分页）
    - GET /api/dashboards/{id} - 获取详情（含所有 panel）
    - PUT /api/dashboards/{id} - 更新 Dashboard
    - DELETE /api/dashboards/{id} - 删除 Dashboard
    - POST /api/dashboards/{id}/panels/{panel_id}/execute - 执行单面板 SQL
    - POST /api/dashboards/{id}/execute-all - 执行所有面板 SQL
    - 面板 SQL 执行前进行安全校验（仅允许 SELECT）
    - _Requirements: 3.1, 3.3, 3.5, 3.6, 4.1, 4.3, 4.4, 4.7_

  - [x] 1.4 注册 Dashboard 路由到主应用
    - 在 `backend/app/main.py` 中注册 dashboard_router
    - _Requirements: 5.1_

- [x] 2. Agent Dashboard Tool 实现
  - [x] 2.1 实现 Dashboard Agent Tool
    - 创建 `backend/app/services/dashboard_tools.py`
    - 实现 create_panel tool：接收标题和描述，调用 SQL Generator 生成相对时间 SQL，调用 Visualization Engine 推荐图表类型，计算默认布局位置
    - 实现 update_panel tool：根据新描述重新生成 SQL 或更新图表类型/标题
    - 实现 remove_panel tool：删除指定面板
    - SQL 生成时在 prompt 中强调使用相对时间函数（CURDATE、DATE_SUB 等）
    - 自动计算面板默认位置：每行最多3个面板（每个宽4列），逐行排列
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.7_

  - [x] 2.2 集成 Dashboard Tool 到 Agent Orchestrator
    - 在 Agent Orchestrator 中注册 dashboard 相关 tools
    - 添加 dashboard builder 模式识别：当用户在大屏构建页面发送消息时，Agent 使用 dashboard tools
    - 支持 LLM 一次对话中多次调用 create_panel 生成多个面板
    - _Requirements: 1.1, 1.4, 1.6_

- [x] 3. 前端基础设施
  - [x] 3.1 安装前端依赖
    - 安装 react-grid-layout 及其类型定义
    - 确认 ECharts 和 ChartView 组件可复用
    - _Requirements: 2.1_

  - [x] 3.2 创建 Dashboard API 服务
    - 创建 `frontend/src/services/dashboardApi.ts`
    - 封装所有 Dashboard 相关 HTTP 请求
    - 包含类型定义：Dashboard, Panel, LayoutPosition, DashboardSummary
    - _Requirements: 3.3, 4.1_

  - [x] 3.3 更新路由和导航
    - 在 `App.tsx` 中添加 /dashboards 和 /dashboards/:id 路由
    - 在 `MainLayout.tsx` 侧边栏添加"智能大屏"菜单项（FundProjectionScreenOutlined 图标）
    - _Requirements: 5.1, 5.2_

- [x] 4. 前端 Dashboard 列表页
  - [x] 4.1 实现 Dashboard 列表页面
    - 创建 `frontend/src/pages/Dashboard/index.tsx`
    - 展示所有已保存的 Dashboard：名称、创建时间、面板数量、最近访问时间
    - 按最近访问时间降序排列
    - 提供"新建大屏"按钮
    - 支持删除（二次确认）和重命名操作
    - 点击 Dashboard 卡片跳转到查看页
    - _Requirements: 3.5, 3.6, 5.2, 5.3_

- [x] 5. 前端 Dashboard 查看页
  - [x] 5.1 实现 Dashboard 查看页面（只读模式）
    - 创建 `frontend/src/pages/Dashboard/DashboardView.tsx`
    - 使用 react-grid-layout 渲染网格布局
    - 加载 Dashboard 配置后并行执行所有面板 SQL
    - 每个面板独立展示加载状态/数据/错误
    - 展示骨架屏直到数据加载完成
    - 提供全局刷新按钮
    - _Requirements: 3.3, 3.4, 3.9, 4.1, 4.2, 4.3, 4.6_

  - [x] 5.2 实现 Panel 面板组件
    - 创建 `frontend/src/components/DashboardPanel.tsx`
    - 复用 ChartView 组件渲染图表
    - 面板操作栏：图表类型切换、刷新、编辑标题、删除
    - 展示最近刷新时间戳
    - 加载状态：Spin 动画
    - 错误状态：错误信息 + 重试按钮
    - 超时状态：超时提示 + 重试按钮
    - _Requirements: 2.4, 2.5, 2.6, 4.2, 4.4, 4.5, 4.6_

  - [x] 5.3 实现编辑模式
    - 在查看页添加"编辑模式"切换按钮
    - 编辑模式下：面板可拖拽移动和缩放、可删除面板、可切换图表类型
    - 拖拽时其他面板自动避让
    - 面板最小尺寸限制：宽≥3列，高≥2行
    - 退出编辑模式时提示保存/放弃
    - _Requirements: 2.1, 2.2, 2.3, 2.7, 2.8, 3.7, 5.4, 5.5_

- [x] 6. 前端 Dashboard 构建器
  - [x] 6.1 实现大屏构建器页面
    - 创建 `frontend/src/pages/Dashboard/DashboardBuilder.tsx`
    - 左侧：对话输入区（复用 Chat 组件的输入逻辑）
    - 右侧：实时预览区（网格布局，面板生成后即时渲染）
    - 对话消息通过 SSE 流式接收，面板配置通过特殊事件类型（panel_created/panel_updated/panel_removed）推送
    - 支持继续对话修改/添加/删除面板
    - 提供保存按钮：输入名称后保存 Dashboard
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 5.2_

  - [x] 6.2 实现构建器与 Agent 的交互协议
    - 定义新的 StreamEvent 类型：panel_created, panel_updated, panel_removed
    - 前端接收到 panel 事件后更新预览区的面板列表和布局
    - 支持 Agent 一次返回多个 panel 事件
    - _Requirements: 1.1, 1.3, 1.4_

- [x] 7. 集成与联调
  - [x] 7.1 端到端联调
    - 验证对话创建 Dashboard 完整流程
    - 验证保存后重新打开数据正确加载
    - 验证面板拖拽布局保存后一致
    - 验证单面板失败不影响其他面板
    - 验证 SQL 安全校验拦截写操作
    - _Requirements: 1.1, 3.3, 3.4, 3.7, 4.7_

  - [x] 7.2 样式与交互优化
    - 确保深色主题下所有组件样式一致
    - 验证响应式布局在不同屏幕尺寸下正常
    - 优化拖拽和缩放的动画流畅度
    - _Requirements: 2.2, 2.3, 2.7_

## Notes

- 复用现有模块：SQL Generator、Query Executor、Visualization Engine、ChartView 组件
- react-grid-layout 提供开箱即用的拖拽和响应式网格能力
- 面板 SQL 执行复用现有 /api/query/execute 接口的逻辑，增加安全校验层
- Agent Tool 的 prompt 设计是关键，需要明确指导 LLM 使用相对时间函数
- 前端构建器页面采用左右分栏布局：左侧对话、右侧预览

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "3.1"] },
    { "id": 2, "tasks": ["1.3", "1.4", "3.2", "3.3"] },
    { "id": 3, "tasks": ["2.1", "4.1"] },
    { "id": 4, "tasks": ["2.2", "5.1", "5.2"] },
    { "id": 5, "tasks": ["5.3", "6.1", "6.2"] },
    { "id": 6, "tasks": ["7.1", "7.2"] }
  ]
}
```
