# Requirements Document

## Introduction

智能大屏（Smart Dashboard）是数仓智能体平台的扩展功能模块。用户通过自然语言对话描述所需的数据指标和展示形式，系统基于 LLM 自动生成固定 SQL 查询并推荐图表类型，将多个数据面板组合为可视化大屏。用户可以通过拖拽调整面板布局、切换图表类型、继续对话修改面板内容，满意后保存为持久化 Dashboard。后续打开已保存的 Dashboard 时，系统自动执行保存的 SQL 获取最新数据并按保存的布局渲染，实现"一次配置，持续使用"的数据看板体验。

## Glossary

- **Dashboard**: 数据大屏，由多个 Panel 组成的可视化看板，支持持久化保存和重复打开
- **Panel**: 大屏中的单个数据面板，包含标题、SQL 查询、图表类型和布局位置
- **Dashboard Builder**: 大屏构建器，通过对话方式创建和编辑 Dashboard 的交互模式
- **Layout**: 面板布局配置，描述每个 Panel 在网格中的位置（x, y）和尺寸（w, h）
- **Relative Time SQL**: 使用相对时间函数（如 CURDATE()、DATE_SUB()）的 SQL，确保每次执行获取最新数据
- **Panel Refresh**: 面板数据刷新，执行面板关联的 SQL 获取当前最新数据

## Requirements

### Requirement 1: 对话式大屏构建

**User Story:** 作为数据分析师，我希望通过自然语言描述需要的指标和展示形式，系统自动生成多个数据面板组成大屏，以便快速搭建数据看板而无需逐个配置。

#### Acceptance Criteria

1. WHEN 用户在大屏构建模式下输入自然语言描述（如"我想看本月充值趋势、日活用户数、游戏消耗TOP5"）, THE Dashboard_Builder SHALL 调用 LLM 将描述拆解为多个独立的数据指标需求
2. FOR EACH 拆解出的指标需求, THE Dashboard_Builder SHALL 生成对应的 SQL 查询语句和推荐图表类型，SQL 中的时间条件必须使用相对时间函数（如 CURDATE()、DATE_SUB()、DATE_FORMAT()）而非硬编码日期
3. WHEN 所有面板的 SQL 生成完成, THE Dashboard_Builder SHALL 在前端即时渲染所有面板，默认采用自适应网格布局（每行最多放置3个面板）
4. WHEN 用户继续对话输入修改指令（如"把充值趋势改成按周汇总"、"再加一个新增用户面板"）, THE Dashboard_Builder SHALL 识别修改意图并更新对应面板的 SQL 或新增面板，已有面板的布局位置保持不变
5. WHEN 用户要求删除某个面板（如"去掉游戏消耗那个"）, THE Dashboard_Builder SHALL 移除对应面板并自动调整剩余面板的布局
6. IF LLM 无法从用户描述中识别出明确的指标需求, THEN THE Dashboard_Builder SHALL 向用户提示无法理解并请求补充说明
7. THE Dashboard_Builder SHALL 为每个生成的面板自动命名标题，标题应简洁描述该面板展示的数据内容

### Requirement 2: 面板布局与交互调整

**User Story:** 作为用户，我希望能通过拖拽和缩放调整面板的位置和大小，并切换图表类型，以便按照自己的偏好定制大屏布局。

#### Acceptance Criteria

1. THE Dashboard_UI SHALL 采用网格布局系统，支持面板的拖拽移动和缩放调整，网格列数为12列
2. WHEN 用户拖拽面板到新位置, THE Dashboard_UI SHALL 在200ms内完成布局更新，其他面板自动避让重新排列
3. WHEN 用户缩放面板尺寸, THE Dashboard_UI SHALL 实时更新面板内图表的渲染尺寸，图表在300ms内完成自适应重绘
4. THE Dashboard_UI SHALL 为每个面板提供图表类型切换控件，支持在表格、柱状图、折线图、饼图之间切换
5. WHEN 用户切换面板的图表类型, THE Dashboard_UI SHALL 在2秒内完成数据重新渲染并展示目标图表类型
6. THE Dashboard_UI SHALL 为每个面板提供以下操作入口：编辑标题、切换图表类型、刷新数据、删除面板
7. WHEN 面板数量超过单屏可展示范围, THE Dashboard_UI SHALL 支持垂直滚动浏览所有面板
8. THE Dashboard_UI SHALL 支持面板的最小尺寸限制（宽度不小于3列，高度不小于2行），防止面板过小导致图表无法正常展示

### Requirement 3: Dashboard 持久化与管理

**User Story:** 作为用户，我希望将满意的大屏配置保存下来，后续可以直接打开查看最新数据，以便持续跟踪关注的指标。

#### Acceptance Criteria

1. WHEN 用户点击保存按钮, THE System SHALL 将 Dashboard 配置持久化存储，包括：Dashboard 名称、所有面板的标题、SQL、图表类型和布局位置
2. THE System SHALL 要求用户为 Dashboard 提供名称，名称长度不超过64个字符且在系统内唯一
3. WHEN 用户打开已保存的 Dashboard, THE System SHALL 并行执行所有面板的 SQL 查询获取最新数据，并按保存的布局和图表类型渲染
4. IF 某个面板的 SQL 执行失败, THEN THE System SHALL 在该面板区域展示错误提示信息，其他面板正常渲染不受影响
5. THE System SHALL 提供 Dashboard 列表页面，展示所有已保存的 Dashboard 名称、创建时间、面板数量，按最近访问时间降序排列
6. THE System SHALL 支持 Dashboard 的重命名和删除操作，删除操作需二次确认
7. WHEN 用户打开 Dashboard 后修改了面板配置（调整布局、修改图表类型等）, THE System SHALL 支持将修改覆盖保存到原 Dashboard
8. THE System SHALL 限制单个 Dashboard 最多包含12个面板，超出时提示用户删除部分面板后再添加
9. WHEN 用户打开 Dashboard 时, THE System SHALL 在所有面板数据加载完成前展示加载骨架屏，每个面板独立展示加载状态

### Requirement 4: 面板数据刷新与执行

**User Story:** 作为用户，我希望打开 Dashboard 时能看到最新数据，并且可以手动刷新单个面板或整个大屏的数据。

#### Acceptance Criteria

1. WHEN Dashboard 被打开, THE System SHALL 自动执行所有面板的 SQL 查询，每个面板独立执行互不阻塞
2. THE System SHALL 为每个面板展示最近一次数据加载的时间戳
3. THE Dashboard_UI SHALL 提供全局刷新按钮，点击后重新执行所有面板的 SQL 查询
4. THE Dashboard_UI SHALL 为每个面板提供独立的刷新按钮，点击后仅重新执行该面板的 SQL
5. IF 面板 SQL 执行超过30秒未返回结果, THEN THE System SHALL 终止该面板的查询并展示超时提示，提供重试按钮
6. WHEN 面板数据正在加载时, THE Dashboard_UI SHALL 在该面板区域展示加载动画，面板的其他操作（如拖拽、缩放）不受影响
7. THE System SHALL 对面板 SQL 执行进行安全校验，仅允许 SELECT 语句，拒绝执行 INSERT、UPDATE、DELETE、DROP 等写操作

### Requirement 5: 导航与入口集成

**User Story:** 作为用户，我希望在侧边栏能快速访问大屏功能，包括创建新大屏和打开已保存的大屏。

#### Acceptance Criteria

1. THE UI SHALL 在侧边栏导航中添加"智能大屏"入口，点击后进入 Dashboard 列表页面
2. THE Dashboard 列表页面 SHALL 提供"新建大屏"按钮，点击后进入大屏构建模式（对话式创建）
3. WHEN 用户点击列表中的某个 Dashboard, THE System SHALL 直接打开该 Dashboard 并加载最新数据
4. THE Dashboard 查看页面 SHALL 提供"编辑模式"切换按钮，进入编辑模式后可调整布局和通过对话修改面板
5. WHEN 用户从编辑模式退出, THE System SHALL 提示用户是否保存修改，用户可选择保存、放弃修改或继续编辑
