# Requirements Document

## Introduction

数仓智能体（Doris Data Agent）是一个基于大语言模型的智能数据查询与分析平台。用户通过自然语言与系统交互，系统结合数据库表的DDL信息和预定义的指标（Metrics），自动生成SQL并在Apache Doris上执行，最终以表格、图表等多种形式展示查询结果。系统支持多轮对话、对话历史管理、指标管理以及场景分析等功能。

## Glossary

- **Agent**: 核心智能体模块，负责理解用户意图、协调各子系统完成查询任务
- **SQL_Generator**: SQL生成器，根据自然语言和上下文生成可执行的SQL语句
- **Metric_Engine**: 指标引擎，管理预定义的指标模板并进行语义匹配
- **Query_Executor**: 查询执行器，负责将SQL提交到Doris执行并返回结果
- **Conversation_Manager**: 对话管理器，维护多轮对话上下文和历史记录
- **Visualization_Engine**: 可视化引擎，将查询结果渲染为表格或图表
- **Skill_Manager**: 场景技能管理器，管理和执行用户导入的分析技能
- **Metric**: 预定义的数据指标，包含说明、SQL模板和参数定义
- **Skill**: 场景分析技能，格式与Claude Code的skill一致
- **DDL**: 数据库表的定义语句，描述表结构、字段和约束
- **Doris**: Apache Doris，目标数据仓库引擎

## Requirements

### Requirement 1: 自然语言转SQL

**User Story:** 作为数据分析师，我希望通过自然语言描述查询需求，系统自动生成对应的SQL并执行，以便快速获取数据而无需手写SQL。

#### Acceptance Criteria

1. WHEN 用户提交自然语言查询请求, THE SQL_Generator SHALL 结合数据库DDL信息生成符合Doris SQL语法的SQL语句
2. WHEN SQL语句生成完成, THE Query_Executor SHALL 将SQL提交到Doris执行并返回查询结果，单次查询返回结果不超过1000行
3. WHEN 用户查询涉及多张表, THE SQL_Generator SHALL 根据DDL中的表关系生成正确的JOIN语句
4. IF 生成的SQL执行失败, THEN THE Agent SHALL 向用户展示错误原因并尝试修正SQL后重新执行，最多重试3次，若仍失败则终止并告知用户失败原因
5. THE SQL_Generator SHALL 在生成SQL前向用户展示生成的SQL语句以供确认
6. IF 用户拒绝确认生成的SQL, THEN THE Agent SHALL 允许用户提供修改意见并根据反馈重新生成SQL
7. IF Query_Executor执行SQL超过30秒未返回结果, THEN THE Query_Executor SHALL 终止该查询并向用户提示查询超时
8. IF SQL_Generator无法从用户的自然语言描述中识别出明确的查询意图, THEN THE Agent SHALL 向用户提示无法理解并请求用户补充或澄清查询需求

### Requirement 2: 指标管理与匹配

**User Story:** 作为业务运营人员，我希望预先录入常用的业务指标及其对应SQL，以便系统优先使用经过验证的指标SQL来回答查询。

#### Acceptance Criteria

1. THE Metric_Engine SHALL 提供指标的创建、编辑、删除和查询功能
2. WHEN 用户创建指标时, THE Metric_Engine SHALL 要求录入指标名称、用途说明、SQL模板和参数定义，其中指标名称不超过64个字符且在系统内唯一，用途说明不超过512个字符
3. WHEN 用户提交查询请求, THE Agent SHALL 先在已录入的指标中基于用户查询与指标名称及用途说明进行语义相似度匹配，将相似度最高且达到匹配阈值的指标作为命中结果
4. WHEN 匹配到指标且存在多个达到阈值的候选指标, THE Agent SHALL 选择相似度最高的指标，使用该指标的SQL模板并根据用户查询提取参数值进行填充后执行
5. IF 未匹配到达到阈值的指标, THEN THE Agent SHALL 回退到基于DDL生成SQL的方式处理查询
6. THE Metric_Engine SHALL 支持指标的参数化配置，包括参数名称、类型和默认值，每个指标最多支持20个参数
7. WHEN 用户录入指标名称和用途说明后, THE Agent SHALL 根据DDL信息自动生成参考SQL供用户参考
8. THE UI SHALL 在指标创建页面提供SQL编辑器，支持用户对Agent生成的参考SQL进行手动修改后保存
9. IF 指标SQL模板中的必填参数无法从用户查询中提取且未配置默认值, THEN THE Agent SHALL 向用户提示缺少的参数名称并请求用户补充

### Requirement 3: 多轮对话与上下文管理

**User Story:** 作为数据分析师，我希望系统能记住对话上下文，以便我可以基于前一次查询结果进行追问、质疑或深入分析。

#### Acceptance Criteria

1. THE Conversation_Manager SHALL 在同一会话中保持对话上下文，包括用户的每轮输入、Agent的回复、生成的SQL语句及查询结果摘要
2. WHEN 用户基于上一次查询结果提出追问, THE Agent SHALL 结合历史上下文中的SQL和查询结果，生成引用或扩展前次查询的新SQL语句
3. WHEN 用户要求对某个指标进行细分, THE Agent SHALL 在原查询SQL基础上添加GROUP BY字段或WHERE筛选条件，并保留原查询的度量计算逻辑
4. WHEN 用户质疑查询结果, THE Agent SHALL 展示当前查询的SQL语句并逐步解释其筛选条件、聚合逻辑和JOIN关系，同时提供至少一种可执行的验证方式（如拆分子查询单独执行、添加明细数据抽样查询）
5. IF 对话上下文超出模型上下文窗口限制, THEN THE Conversation_Manager SHALL 对早期对话进行摘要压缩，摘要中须保留每轮对话涉及的表名、指标名称、筛选条件和查询结果的关键数值
6. IF 用户的追问中包含指代不明确的引用且无法从上下文中唯一确定所指对象, THEN THE Agent SHALL 向用户提出澄清问题，列出可能的引用对象供用户选择
7. THE Conversation_Manager SHALL 支持单个会话最多保留50轮对话记录，超出时对最早的对话轮次执行摘要压缩

### Requirement 4: 对话历史持久化

**User Story:** 作为用户，我希望所有对话历史被保存，以便我可以随时查看和回顾之前的分析过程。

#### Acceptance Criteria

1. THE Conversation_Manager SHALL 将每次对话的完整内容持久化存储，包括每条消息的角色（用户/Agent）、消息文本、生成的SQL语句、查询结果、时间戳以及会话标题
2. THE UI SHALL 提供对话历史列表页面，按最近活跃时间降序展示所有历史会话，每条记录展示会话标题、最后一条消息的时间和消息总数，并支持分页加载（每页不超过20条）
3. WHEN 用户选择某条历史会话, THE UI SHALL 展示该会话的完整对话内容，包括所有消息、关联的SQL和查询结果
4. THE Conversation_Manager SHALL 支持按时间范围和关键词搜索历史对话，关键词搜索范围覆盖会话标题和消息文本，搜索结果按时间降序排列且单次返回不超过50条
5. WHEN 用户打开历史会话, THE Agent SHALL 恢复该会话的上下文以支持继续对话；IF 历史会话内容超出模型上下文窗口限制, THEN THE Conversation_Manager SHALL 对早期对话进行摘要压缩后加载以保留关键信息
6. WHEN 用户请求删除某条历史会话, THE Conversation_Manager SHALL 永久删除该会话的所有存储数据并从历史列表中移除

### Requirement 5: 数据可视化

**User Story:** 作为数据分析师，我希望查询结果能以表格、柱状图、折线图等多种形式展示，以便直观理解数据趋势和分布。

#### Acceptance Criteria

1. WHEN 查询返回结果数据, THE Visualization_Engine SHALL 默认以表格形式展示数据，表格单页展示不超过1000行，超出部分提供分页浏览
2. THE Visualization_Engine SHALL 支持表格、柱状图、折线图、饼图四种展示形式
3. WHEN 用户切换图表类型, THE Visualization_Engine SHALL 在2秒内完成数据重新渲染并展示目标图表类型
4. WHEN 查询结果返回后, THE Agent SHALL 根据数据的维度数量和类型推荐图表类型，并在界面上以默认选中状态展示推荐的图表类型
5. WHEN 数据包含时间序列维度, THE Visualization_Engine SHALL 将折线图作为默认推荐图表类型并自动以折线图展示
6. THE Visualization_Engine SHALL 支持图表的交互操作，包括缩放、悬停提示和数据筛选
7. WHEN 用户在查询中明确指定图表类型, THE Visualization_Engine SHALL 按照用户指定的图表类型展示数据
8. WHEN 用户指定的图表类型与数据结构不兼容（饼图要求至少一个分类维度和一个数值度量、折线图要求至少一个有序维度和一个数值度量、柱状图要求至少一个分类维度和一个数值度量）, THE Visualization_Engine SHALL 仍按用户指定的图表类型尽力渲染，同时展示数据适配建议说明当前数据结构与该图表类型的不匹配之处
9. IF 查询结果数据为空, THEN THE Visualization_Engine SHALL 展示空状态提示，告知用户当前查询无返回数据

### Requirement 6: 界面设计

**User Story:** 作为用户，我希望系统界面现代、美观且交互流畅，以获得良好的使用体验。

#### Acceptance Criteria

1. THE UI SHALL 采用深色主题作为默认配色方案
2. THE UI SHALL 支持响应式布局，适配桌面端（视口宽度≥1024px）和平板端（视口宽度≥768px且<1024px）屏幕，确保所有功能模块在两种尺寸下均可完整访问且无内容溢出或重叠
3. WHEN Agent生成回复内容时, THE UI SHALL 在对话区域使用流式输出逐步展示回复文本，使用户可在生成过程中实时阅读已输出的内容
4. THE UI SHALL 提供侧边栏导航，包含对话、指标管理、技能管理和历史记录入口；在平板端屏幕下侧边栏SHALL支持收起和展开切换
5. WHILE 查询正在执行, THE UI SHALL 展示加载动画并显示当前执行状态提示（如"正在生成SQL"、"正在执行查询"、"正在处理结果"）
6. THE UI SHALL 对页面切换和组件交互使用持续时间在200ms至400ms之间的动效过渡
7. IF 查询执行超过10秒未返回结果, THEN THE UI SHALL 向用户展示仍在处理中的提示信息并提供取消查询的操作入口

### Requirement 7: 场景分析与技能管理

**User Story:** 作为数据分析师，我希望能导入和管理分析技能（Skill），通过选择特定技能执行预定义的分析场景，以提高复杂分析的效率。

#### Acceptance Criteria

1. THE Skill_Manager SHALL 支持导入符合Claude Code skill格式的技能文件，单个技能文件大小不超过1MB
2. THE UI SHALL 提供技能列表页面，展示所有已导入的技能及其描述
3. WHEN 用户选择某个技能, THE UI SHALL 展示该技能的详细说明和所需参数，并提供参数输入表单供用户填写
4. WHEN 用户确认执行技能, THE Skill_Manager SHALL 将技能内容和用户填写的参数作为上下文注入Agent并触发执行
5. THE Skill_Manager SHALL 支持技能的导入、导出、编辑和删除操作
6. IF 技能文件格式不符合规范, THEN THE Skill_Manager SHALL 拒绝导入并提示具体的格式错误
7. WHEN 技能中包含Python脚本, THE Skill_Manager SHALL 在安全沙箱环境中执行该Python脚本，沙箱环境禁止网络访问和文件系统写入，内存限制不超过512MB，并将执行结果返回给用户
8. IF Python脚本执行时间超过30秒或发生运行时异常, THEN THE Skill_Manager SHALL 终止执行并向用户展示错误信息，包括超时或异常类型的说明
9. IF 用户填写的技能参数不符合该技能定义的参数类型或约束, THEN THE Skill_Manager SHALL 拒绝执行并提示具体的参数校验错误
10. WHEN 技能执行完成, THE UI SHALL 在对话区域展示执行结果，若结果包含数据则以表格或图表形式呈现

### Requirement 8: DDL管理

**User Story:** 作为系统管理员，我希望能管理系统使用的数据库DDL信息，以确保SQL生成基于最新的表结构。

#### Acceptance Criteria

1. WHEN 用户在DDL管理页面发起加载操作, THE Agent SHALL 连接Doris数据库并获取指定数据库或表的DDL信息，包括表名、字段名、字段类型和约束信息
2. THE UI SHALL 提供DDL管理页面，以列表形式展示当前已加载的所有表结构，每条记录包含数据库名、表名、字段数量和最近加载时间
3. WHEN 用户在DDL管理页面点击手动刷新, THE Agent SHALL 重新从Doris获取已加载表的最新DDL并更新本地缓存
4. THE Agent SHALL 支持选择性加载指定数据库或表的DDL，用户可通过数据库名和表名筛选要加载的目标表
5. WHEN 用户查询涉及未加载DDL的表, THE Agent SHALL 提示用户该表结构未加载并建议加载
6. IF Doris数据库连接失败或DDL获取过程中发生错误, THEN THE Agent SHALL 终止当前加载操作并向用户展示错误信息，已加载的DDL缓存保持不变
