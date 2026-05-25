# Implementation Plan: Doris Data Agent

## Overview

基于设计文档的架构，将系统实现拆分为后端核心模块（Python FastAPI）和前端界面（React + TypeScript）两大部分。后端按模块逐步实现数据层、业务逻辑层和API层；前端按页面和组件逐步构建。每个模块实现后紧跟属性测试和单元测试，确保增量验证。

## Tasks

- [x] 1. 项目初始化与基础设施搭建
  - [x] 1.1 初始化后端项目结构（Python FastAPI）
    - 创建项目目录结构：`backend/app/`，包含 `models/`、`services/`、`api/`、`core/`、`tests/` 子目录
    - 配置 FastAPI 应用入口 `main.py`，包含 CORS 中间件和 SSE 支持
    - 创建 `requirements.txt` 或 `pyproject.toml`，包含 fastapi、uvicorn、sqlalchemy、openai、pymysql、hypothesis、pytest 等依赖
    - 创建 `core/config.py` 配置模块，管理 LLM API Key、Doris 连接信息、超时设置等
    - _Requirements: 1.1, 6.3_

  - [x] 1.2 初始化前端项目结构（React + TypeScript）
    - 使用 Vite 创建 React + TypeScript 项目
    - 安装 Ant Design 5、ECharts 5、Monaco Editor、fast-check 等依赖
    - 配置深色主题（Ant Design ConfigProvider + 自定义 CSS 变量）
    - 创建目录结构：`src/components/`、`src/pages/`、`src/services/`、`src/hooks/`、`src/types/`
    - _Requirements: 6.1, 6.2_

  - [x] 1.3 搭建 SQLite 数据库层
    - 创建 `backend/app/models/database.py`，配置 SQLAlchemy 异步引擎和会话工厂
    - 定义 ORM 模型：Conversation、Message、Metric、MetricParameter、Skill、SkillParameter
    - 创建数据库初始化脚本，自动建表
    - _Requirements: 4.1, 2.1_

  - [x] 1.4 创建共享类型定义和接口
    - 后端：创建 `backend/app/models/schemas.py`，定义 Pydantic 模型（QueryRequest、StreamEvent、SQLGenResult 等）
    - 前端：创建 `src/types/index.ts`，定义 TypeScript 接口（QueryRequest、StreamEvent、ChartType、Metric 等）
    - 确保前后端类型定义一致
    - _Requirements: 1.1, 5.2_

- [x] 2. DDL管理模块实现
  - [x] 2.1 实现 DDL Manager 服务（后端）
    - 创建 `backend/app/services/ddl_manager.py`
    - 实现 Doris 数据库连接（PyMySQL，MySQL协议兼容）
    - 实现 `load_ddl()` 方法：连接 Doris，执行 SHOW CREATE TABLE 获取 DDL
    - 实现 `refresh_ddl()` 方法：重新获取已加载表的最新 DDL
    - 实现文件缓存机制：DDL 以 JSON 文件存储在 `cache/ddl/{database}/{table}.json`
    - 实现 `list_loaded_ddl()`、`get_ddl_by_table()`、`is_table_loaded()`、`clear_cache()` 方法
    - 错误处理：连接失败时保留现有缓存不变
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [ ]* 2.2 编写 DDL 选择性加载过滤属性测试
    - **Property 15: DDL选择性加载过滤**
    - 使用 Hypothesis 生成随机 DDL 集合和过滤条件，验证加载结果匹配过滤条件
    - **Validates: Requirements 8.4**

  - [ ]* 2.3 编写未加载表检测属性测试
    - **Property 16: 未加载表检测**
    - 使用 Hypothesis 生成随机表引用集合和缓存状态，验证检测函数返回所有未加载表名
    - **Validates: Requirements 8.5**

  - [ ]* 2.4 编写 DDL 缓存错误保护属性测试
    - **Property 17: DDL缓存文件错误保护**
    - 使用 Hypothesis 生成随机缓存文件状态并模拟加载错误，验证操作后缓存状态不变
    - **Validates: Requirements 8.6**

  - [x] 2.5 实现 DDL 管理 API 路由
    - 创建 `backend/app/api/ddl.py`
    - 实现 `POST /api/ddl/load` 加载 DDL 接口
    - 实现 `POST /api/ddl/refresh` 刷新 DDL 接口
    - 实现 `GET /api/ddl/list` 列表查询接口
    - 实现 `DELETE /api/ddl/cache` 清除缓存接口
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [ ]* 2.6 编写 DDL Manager 单元测试
    - 测试文件缓存读写正确性
    - 测试连接失败时的错误处理
    - 测试选择性加载指定数据库/表
    - _Requirements: 8.1, 8.4, 8.6_

- [x] 3. 对话管理模块实现
  - [x] 3.1 实现 Conversation Manager 服务（后端）
    - 创建 `backend/app/services/conversation_manager.py`
    - 实现会话 CRUD：`create_conversation()`、`get_conversation()`、`delete_conversation()`
    - 实现消息管理：`add_message()`、`get_messages()`
    - 实现会话列表分页查询（按 updated_at 降序，每页最多20条）
    - 实现关键词和时间范围搜索（结果按时间降序，最多50条）
    - 实现上下文管理：`get_context()`、`summarize_context()`
    - 实现消息轮次上限控制（50轮），超出时自动摘要压缩最早消息
    - 摘要压缩须保留表名、指标名称、筛选条件和关键数值
    - _Requirements: 3.1, 3.2, 3.5, 3.7, 4.1, 4.2, 4.4, 4.5, 4.6_

  - [ ]* 3.2 编写上下文摘要信息保留属性测试
    - **Property 7: 上下文摘要信息保留**
    - 使用 Hypothesis 生成含随机表名、指标、筛选条件的对话，验证摘要保留所有关键信息
    - **Validates: Requirements 3.5**

  - [ ]* 3.3 编写会话消息轮次上限属性测试
    - **Property 8: 会话消息轮次上限**
    - 使用 Hypothesis 生成随机长度消息序列，验证活跃消息不超过50轮且第51轮触发压缩
    - **Validates: Requirements 3.7**

  - [ ]* 3.4 编写会话列表分页排序属性测试
    - **Property 9: 会话列表分页排序**
    - 使用 Hypothesis 生成随机时间戳的会话集合，验证返回结果按时间降序且单页不超过20条
    - **Validates: Requirements 4.2**

  - [ ]* 3.5 编写会话搜索结果限制属性测试
    - **Property 10: 会话搜索结果限制**
    - 使用 Hypothesis 生成随机会话数据和搜索条件，验证结果匹配条件、按时间降序、不超过50条
    - **Validates: Requirements 4.4**

  - [x] 3.6 实现对话管理 API 路由
    - 创建 `backend/app/api/conversations.py`
    - 实现 `POST /api/conversations` 创建会话
    - 实现 `GET /api/conversations` 列表查询（分页）
    - 实现 `GET /api/conversations/{id}` 获取会话详情
    - 实现 `GET /api/conversations/{id}/messages` 获取消息列表
    - 实现 `DELETE /api/conversations/{id}` 删除会话
    - 实现 `GET /api/conversations/search` 搜索接口
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6_

  - [ ]* 3.7 编写 Conversation Manager 单元测试
    - 测试会话 CRUD 操作
    - 测试删除后数据完全清除
    - 测试分页和搜索边界条件
    - _Requirements: 4.1, 4.6_

- [x] 4. Checkpoint - 确保基础模块测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. 指标引擎模块实现
  - [x] 5.1 实现 Metric Engine 服务（后端）
    - 创建 `backend/app/services/metric_engine.py`
    - 实现指标 CRUD：`create_metric()`、`update_metric()`、`delete_metric()`、`list_metrics()`、`get_metric()`
    - 实现创建验证：名称≤64字符且唯一、说明≤512字符、参数≤20个
    - 实现语义匹配：`match_metric()` 基于 LLM embedding 或文本相似度计算
    - 实现参数提取：`extract_parameters()` 从用户查询中提取指标参数值
    - 实现缺失参数检测：必填参数未提取且无默认值时返回缺失列表
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.9_

  - [ ]* 5.2 编写指标创建验证属性测试
    - **Property 4: 指标创建验证**
    - 使用 Hypothesis 生成随机长度字符串和参数列表，验证超限时拒绝创建并返回对应错误
    - **Validates: Requirements 2.2, 2.6**

  - [ ]* 5.3 编写指标语义匹配属性测试
    - **Property 5: 指标语义匹配**
    - 使用 Hypothesis 生成随机相似度分数集合，验证返回最高且超阈值的指标或 null
    - **Validates: Requirements 2.3, 2.4**

  - [ ]* 5.4 编写缺失指标参数检测属性测试
    - **Property 6: 缺失指标参数检测**
    - 使用 Hypothesis 生成随机参数定义和提取结果，验证返回所有缺失必填参数名称
    - **Validates: Requirements 2.9**

  - [x] 5.5 实现指标管理 API 路由
    - 创建 `backend/app/api/metrics.py`
    - 实现 `POST /api/metrics` 创建指标
    - 实现 `GET /api/metrics` 列表查询（分页）
    - 实现 `GET /api/metrics/{id}` 获取指标详情
    - 实现 `PUT /api/metrics/{id}` 更新指标
    - 实现 `DELETE /api/metrics/{id}` 删除指标
    - 实现 `POST /api/metrics/generate-sql` 根据指标名称和用途自动生成参考 SQL
    - _Requirements: 2.1, 2.7, 2.8_

  - [ ]* 5.6 编写 Metric Engine 单元测试
    - 测试 CRUD 操作正确性
    - 测试名称唯一性约束
    - 测试参数类型校验
    - _Requirements: 2.1, 2.2_

- [x] 6. SQL生成与查询执行模块实现
  - [x] 6.1 实现 SQL Generator 服务（后端）
    - 创建 `backend/app/services/sql_generator.py`
    - 实现 `generate_sql()` 方法：构建 LLM prompt（含 DDL 上下文和对话历史），调用 LLM 生成 SQL
    - 实现 `refine_sql_with_feedback()` 方法：根据用户反馈修正 SQL
    - 实现 `generate_reference_sql()` 方法：根据指标名称和用途生成参考 SQL
    - 实现 SQL 引用验证：检查生成的 SQL 中引用的表名和列名是否存在于 DDL 上下文
    - 支持多表 JOIN 语句生成
    - _Requirements: 1.1, 1.3, 1.5, 1.6, 1.8, 2.7_

  - [ ]* 6.2 编写 SQL 引用验证属性测试
    - **Property 1: SQL引用验证**
    - 使用 Hypothesis 生成随机 DDL Schema 和 SQL 语句，验证引用的表名和列名均存在于 DDL 中
    - **Validates: Requirements 1.1**

  - [x] 6.3 实现 Query Executor 服务（后端）
    - 创建 `backend/app/services/query_executor.py`
    - 实现 `execute_sql()` 方法：连接 Doris 执行 SQL，支持超时控制（默认30秒）
    - 实现结果行数限制（最多1000行），超出时设置 truncated=true
    - 实现 `cancel_query()` 方法：取消正在执行的查询
    - 实现重试机制：执行失败时自动修正 SQL 并重试，最多3次
    - 超时处理：超过30秒终止查询并返回超时错误
    - _Requirements: 1.2, 1.4, 1.7_

  - [ ]* 6.4 编写查询结果行数限制属性测试
    - **Property 2: 查询结果行数限制**
    - 使用 Hypothesis 生成随机行数(0-10000)的结果集，验证返回不超过1000行且超出时 truncated=true
    - **Validates: Requirements 1.2, 5.1**

  - [ ]* 6.5 编写 SQL 重试机制上限属性测试
    - **Property 3: SQL重试机制上限**
    - 使用 Hypothesis 生成随机成功/失败序列，验证重试不超过3次且成功时立即返回
    - **Validates: Requirements 1.4**

  - [x] 6.6 实现查询相关 API 路由
    - 创建 `backend/app/api/query.py`
    - 实现 `POST /api/query/execute` 执行 SQL 接口
    - 实现 `POST /api/query/cancel` 取消查询接口
    - _Requirements: 1.2, 1.7_

  - [ ]* 6.7 编写 SQL Generator 和 Query Executor 单元测试
    - 测试 SQL 确认/拒绝流程
    - 测试30秒超时触发取消
    - 测试重试3次后终止
    - Mock LLM 和 Doris 连接
    - _Requirements: 1.4, 1.5, 1.6, 1.7_

- [x] 7. 可视化引擎模块实现
  - [x] 7.1 实现 Visualization Engine 服务（后端）
    - 创建 `backend/app/services/visualization_engine.py`
    - 实现 `recommend_chart_type()` 方法：根据列类型推荐图表（时间序列→折线图，分类+数值→柱状图）
    - 实现 `generate_chart_config()` 方法：生成 ECharts 配置对象
    - 实现 `validate_compatibility()` 方法：验证数据与图表类型兼容性
    - 兼容性规则：饼图需分类维度+数值度量、折线图需有序维度+数值度量、柱状图需分类维度+数值度量
    - _Requirements: 5.2, 5.4, 5.5, 5.8_

  - [ ]* 7.2 编写图表类型推荐规则属性测试
    - **Property 11: 图表类型推荐规则**
    - 使用 Hypothesis 生成随机列类型组合的结果集，验证推荐结果与数据维度类型一致
    - **Validates: Requirements 5.4, 5.5**

  - [ ]* 7.3 编写图表数据兼容性验证属性测试
    - **Property 12: 图表数据兼容性验证**
    - 使用 Hypothesis 生成随机图表类型+数据结构组合，验证不兼容时返回 compatible=false 并附带说明
    - **Validates: Requirements 5.8**

  - [ ]* 7.4 编写 Visualization Engine 单元测试
    - 测试四种图表类型均可生成配置
    - 测试空数据集处理
    - 测试用户指定图表类型覆盖推荐
    - _Requirements: 5.2, 5.7, 5.9_

- [x] 8. Checkpoint - 确保核心业务模块测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. 技能管理模块实现
  - [x] 9.1 实现 Skill Manager 服务（后端）
    - 创建 `backend/app/services/skill_manager.py`
    - 实现技能 CRUD：`import_skill()`、`export_skill()`、`update_skill()`、`delete_skill()`、`list_skills()`、`get_skill()`
    - 实现导入验证：文件大小≤1MB、格式符合 Claude Code skill 规范
    - 实现参数校验：`validate_params()` 验证用户参数符合技能定义的类型约束
    - 实现技能执行：`execute_skill()` 将技能内容和参数注入 Agent 上下文
    - 实现 Python 脚本沙箱执行：Docker 容器 + RestrictedPython，禁止网络访问和文件写入，内存≤512MB
    - 实现执行超时控制（30秒）和运行时异常捕获
    - _Requirements: 7.1, 7.2, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9_

  - [ ]* 9.2 编写技能导入验证属性测试
    - **Property 13: 技能导入验证**
    - 使用 Hypothesis 生成随机大小和格式的文件内容，验证超1MB拒绝、格式不合规拒绝并返回错误描述
    - **Validates: Requirements 7.1, 7.6**

  - [ ]* 9.3 编写技能参数类型校验属性测试
    - **Property 14: 技能参数类型校验**
    - 使用 Hypothesis 生成随机类型定义和参数值，验证不符合约束时返回具体校验错误
    - **Validates: Requirements 7.9**

  - [x] 9.4 实现技能管理 API 路由
    - 创建 `backend/app/api/skills.py`
    - 实现 `POST /api/skills/import` 导入技能
    - 实现 `GET /api/skills` 列表查询
    - 实现 `GET /api/skills/{id}` 获取技能详情
    - 实现 `PUT /api/skills/{id}` 更新技能
    - 实现 `DELETE /api/skills/{id}` 删除技能
    - 实现 `GET /api/skills/{id}/export` 导出技能
    - 实现 `POST /api/skills/{id}/execute` 执行技能
    - _Requirements: 7.1, 7.3, 7.4, 7.5_

  - [ ]* 9.5 编写 Skill Manager 单元测试
    - 测试导入文件大小限制
    - 测试格式校验错误提示
    - 测试执行超时终止
    - 测试运行时异常捕获
    - _Requirements: 7.1, 7.6, 7.7, 7.8_

- [x] 10. Agent Orchestrator 实现
  - [x] 10.1 实现 Agent Orchestrator 服务（后端）
    - 创建 `backend/app/services/agent_orchestrator.py`
    - 实现 `process_query()` 方法：协调指标匹配→SQL生成→确认→执行→可视化推荐的完整流程
    - 实现 SSE 流式输出：按 StreamEvent 类型逐步推送（thinking、sql_preview、executing、result、chart_recommendation、error、clarification）
    - 实现指标优先策略：先调用 Metric Engine 匹配，未命中时回退到 SQL Generator
    - 实现 SQL 确认机制：生成 SQL 后等待用户确认，拒绝时接收反馈重新生成
    - 实现意图识别失败处理：无法识别查询意图时返回 clarification 事件
    - 实现多轮对话上下文注入：追问时结合历史 SQL 和结果生成新 SQL
    - 实现质疑处理：展示 SQL 并解释逻辑，提供验证方式
    - _Requirements: 1.1, 1.4, 1.5, 1.6, 1.8, 2.3, 2.4, 2.5, 3.2, 3.3, 3.4, 3.6_

  - [x] 10.2 实现 Chat API 路由（SSE 流式接口）
    - 创建 `backend/app/api/chat.py`
    - 实现 `POST /api/chat` SSE 流式接口，返回 EventSource 格式的流式响应
    - 实现 `POST /api/chat/confirm` SQL 确认/拒绝接口
    - 实现 `POST /api/chat/cancel` 取消查询接口
    - 处理会话创建和消息持久化
    - _Requirements: 1.5, 1.6, 6.3, 6.7_

  - [ ]* 10.3 编写 Agent Orchestrator 单元测试
    - 测试指标匹配回退到 DDL 生成的流程
    - 测试 SQL 确认/拒绝流程
    - 测试重试3次后终止
    - 测试意图不明确时的澄清流程
    - Mock 所有子服务
    - _Requirements: 1.4, 1.5, 1.6, 1.8, 2.5_

- [x] 11. Checkpoint - 确保后端所有模块集成测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. 前端布局与导航实现
  - [x] 12.1 实现应用主布局和侧边栏导航
    - 创建 `src/layouts/MainLayout.tsx` 主布局组件
    - 实现侧边栏导航：对话、指标管理、技能管理、DDL管理、历史记录入口
    - 实现响应式布局：桌面端（≥1024px）侧边栏常驻，平板端（≥768px且<1024px）侧边栏可收起/展开
    - 配置路由（React Router）
    - 实现页面切换动效过渡（200ms-400ms）
    - _Requirements: 6.2, 6.4, 6.6_

  - [x] 12.2 实现前端 API 服务层
    - 创建 `src/services/api.ts` 统一 HTTP 请求封装（axios 或 fetch）
    - 创建 `src/services/sse.ts` SSE 流式连接封装
    - 创建各模块 API 服务：`chatApi.ts`、`metricApi.ts`、`skillApi.ts`、`ddlApi.ts`、`conversationApi.ts`
    - _Requirements: 6.3_

- [x] 13. 前端对话视图实现
  - [x] 13.1 实现对话主页面
    - 创建 `src/pages/Chat/index.tsx` 对话页面
    - 实现消息列表组件：展示用户消息和 Agent 回复
    - 实现输入框组件：支持多行输入和发送
    - 实现 SSE 流式接收：逐步展示 Agent 回复文本
    - 实现加载状态展示：显示当前执行阶段（"正在生成SQL"、"正在执行查询"、"正在处理结果"）
    - 实现超过10秒的长时间等待提示和取消操作入口
    - _Requirements: 6.3, 6.5, 6.7_

  - [x] 13.2 实现 SQL 预览与确认组件
    - 创建 `src/components/SQLPreview.tsx`
    - 使用 Monaco Editor 展示生成的 SQL（只读模式，SQL 语法高亮）
    - 实现确认/拒绝按钮
    - 拒绝时展示反馈输入框，允许用户提供修改意见
    - _Requirements: 1.5, 1.6_

  - [x] 13.3 实现对话历史侧边面板
    - 创建 `src/pages/History/index.tsx` 历史记录页面
    - 实现历史会话列表：按最近活跃时间降序，展示标题、时间、消息数，分页加载（每页20条）
    - 实现关键词和时间范围搜索
    - 实现点击历史会话恢复对话上下文
    - _Requirements: 4.2, 4.3, 4.4, 4.5_

- [x] 14. 前端可视化组件实现
  - [x] 14.1 实现数据表格组件
    - 创建 `src/components/DataTable.tsx`
    - 使用 Ant Design Table 组件展示查询结果
    - 实现分页浏览（单页≤1000行）
    - 实现空数据状态提示
    - _Requirements: 5.1, 5.9_

  - [x] 14.2 实现图表组件
    - 创建 `src/components/ChartView.tsx`
    - 集成 ECharts 5，支持柱状图、折线图、饼图三种图表类型
    - 实现图表类型切换（2秒内完成重新渲染）
    - 实现图表交互：缩放、悬停提示、数据筛选
    - 实现 Agent 推荐图表类型的默认选中
    - 实现数据不兼容时的适配建议展示
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9_

  - [ ]* 14.3 编写图表推荐规则前端属性测试（fast-check）
    - **Property 11: 图表类型推荐规则（前端验证）**
    - 使用 fast-check 生成随机列类型组合，验证前端推荐逻辑与后端一致
    - **Validates: Requirements 5.4, 5.5**

  - [ ]* 14.4 编写图表兼容性验证前端属性测试（fast-check）
    - **Property 12: 图表数据兼容性验证（前端验证）**
    - 使用 fast-check 生成随机图表类型+数据结构组合，验证前端兼容性检查逻辑
    - **Validates: Requirements 5.8**

- [x] 15. 前端指标管理页面实现
  - [x] 15.1 实现指标列表与 CRUD 页面
    - 创建 `src/pages/Metrics/index.tsx` 指标管理页面
    - 实现指标列表展示（分页）
    - 实现创建/编辑指标表单：名称（≤64字符）、用途说明（≤512字符）、参数配置（≤20个）
    - 实现删除确认对话框
    - _Requirements: 2.1, 2.2, 2.6_

  - [x] 15.2 实现指标 SQL 编辑器组件
    - 创建 `src/components/MetricSQLEditor.tsx`
    - 集成 Monaco Editor，支持 SQL 语法高亮和编辑
    - 实现"自动生成参考SQL"按钮，调用后端接口获取 Agent 生成的 SQL
    - 支持用户手动修改后保存
    - _Requirements: 2.7, 2.8_

- [x] 16. 前端技能管理页面实现
  - [x] 16.1 实现技能列表与管理页面
    - 创建 `src/pages/Skills/index.tsx` 技能管理页面
    - 实现技能列表展示（名称、描述）
    - 实现技能导入（文件上传，≤1MB限制）
    - 实现技能编辑、导出、删除操作
    - _Requirements: 7.1, 7.2, 7.5_

  - [x] 16.2 实现技能执行面板
    - 创建 `src/components/SkillExecutionPanel.tsx`
    - 展示技能详细说明和所需参数
    - 实现参数输入表单（根据参数类型动态渲染）
    - 实现参数校验提示
    - 实现执行按钮和结果展示（表格/图表形式）
    - _Requirements: 7.3, 7.4, 7.9, 7.10_

- [x] 17. 前端 DDL 管理页面实现
  - [x] 17.1 实现 DDL 管理页面
    - 创建 `src/pages/DDL/index.tsx` DDL 管理页面
    - 实现已加载表结构列表：展示数据库名、表名、字段数量、最近加载时间
    - 实现加载操作：选择数据库和表名进行加载
    - 实现手动刷新按钮
    - 实现错误提示展示
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.6_

- [x] 18. Checkpoint - 确保前端页面基本功能可用
  - Ensure all tests pass, ask the user if questions arise.

- [x] 19. 端到端集成与联调
  - [x] 19.1 实现前后端联调和完整查询流程
    - 验证自然语言→指标匹配/SQL生成→确认→执行→可视化的完整链路
    - 验证 SSE 流式输出在前端正确渲染
    - 验证多轮对话上下文在追问时正确传递
    - 验证指标匹配失败时正确回退到 DDL 生成
    - 确保所有错误状态在前端正确展示
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 2.3, 2.5, 3.2, 5.4, 6.3_

  - [ ]* 19.2 编写后端集成测试
    - 测试端到端查询流程（Mock LLM 和 Doris）
    - 测试 SSE 事件按正确顺序推送
    - 测试 Doris 连接管理（超时、断连）
    - 测试沙箱安全隔离（网络禁止、文件写入禁止、内存限制）
    - _Requirements: 1.1, 1.2, 1.7, 7.7_

  - [ ]* 19.3 编写前端组件测试
    - 测试对话消息渲染
    - 测试图表类型切换
    - 测试响应式布局断点
    - 测试表单校验逻辑
    - _Requirements: 5.3, 6.2, 6.6_

- [x] 20. Final checkpoint - 确保所有测试通过
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties (Hypothesis for Python, fast-check for TypeScript)
- Unit tests validate specific examples and edge cases
- 后端使用 Python FastAPI + SQLAlchemy + Hypothesis
- 前端使用 React 18 + TypeScript + Ant Design 5 + ECharts 5 + Monaco Editor + fast-check
- 外部依赖（LLM、Doris）在单元测试和属性测试中使用 Mock
- 集成测试使用 Docker Compose 环境

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4"] },
    { "id": 2, "tasks": ["2.1", "3.1", "12.1", "12.2"] },
    { "id": 3, "tasks": ["2.2", "2.3", "2.4", "2.5", "2.6", "3.2", "3.3", "3.4", "3.5", "3.6", "3.7"] },
    { "id": 4, "tasks": ["5.1", "6.1", "6.3"] },
    { "id": 5, "tasks": ["5.2", "5.3", "5.4", "5.5", "5.6", "6.2", "6.4", "6.5", "6.6", "6.7"] },
    { "id": 6, "tasks": ["7.1", "9.1"] },
    { "id": 7, "tasks": ["7.2", "7.3", "7.4", "9.2", "9.3", "9.4", "9.5"] },
    { "id": 8, "tasks": ["10.1"] },
    { "id": 9, "tasks": ["10.2", "10.3"] },
    { "id": 10, "tasks": ["13.1", "13.2", "13.3", "15.1", "15.2", "16.1", "16.2", "17.1"] },
    { "id": 11, "tasks": ["14.1", "14.2"] },
    { "id": 12, "tasks": ["14.3", "14.4"] },
    { "id": 13, "tasks": ["19.1"] },
    { "id": 14, "tasks": ["19.2", "19.3"] }
  ]
}
```
