/**
 * 全局类型定义
 * 定义前端使用的核心接口和类型，与后端 Pydantic 模型保持一致。
 */

// ============================================================
// 基础枚举类型
// ============================================================

/** 图表类型枚举 */
export type ChartType = 'table' | 'bar' | 'line' | 'pie'

/** 消息角色 */
export type MessageRole = 'user' | 'agent'

/** SSE 流事件类型 */
export type StreamEventType =
  | 'thinking'
  | 'tool_call'
  | 'sql_preview'
  | 'executing'
  | 'result'
  | 'chart_recommendation'
  | 'error'
  | 'clarification'

/** 指标参数类型 */
export type MetricParameterType = 'string' | 'number' | 'date' | 'enum'

// ============================================================
// Agent 编排器相关接口
// ============================================================

/** SSE 流事件 */
export interface StreamEvent {
  type: StreamEventType
  data: unknown
}

/** 查询请求 */
export interface QueryRequest {
  sessionId: string
  message: string
  conversationId?: string
  /** 是否自动执行SQL（跳过确认），默认true */
  autoExecute?: boolean
}

// ============================================================
// SQL 生成相关接口
// ============================================================

/** SQL 生成结果 */
export interface SQLGenResult {
  sql: string
  explanation: string
  confidence: number
  referencedTables: string[]
}

// ============================================================
// 指标引擎相关接口
// ============================================================

/** 指标参数定义 */
export interface MetricParameter {
  name: string
  type: MetricParameterType
  required: boolean
  defaultValue?: unknown
  enumValues?: string[]
}

/** 指标创建输入 */
export interface MetricCreateInput {
  /** 指标名称，最长64字符 */
  name: string
  /** 用途说明，最长512字符 */
  description: string
  /** SQL模板 */
  sqlTemplate: string
  /** 参数定义列表，最多20个 */
  parameters: MetricParameter[]
}

/** 指标更新输入 */
export interface MetricUpdateInput {
  name?: string
  description?: string
  sqlTemplate?: string
  parameters?: MetricParameter[]
}

/** 指标完整信息 */
export interface Metric {
  id: string
  name: string
  description: string
  sqlTemplate: string
  parameters: MetricParameter[]
  createdAt: string
  updatedAt: string
}

/** 指标匹配结果 */
export interface MetricMatchResult {
  metric: Metric
  similarity: number
  candidates: Array<{ metric: Metric; similarity: number }>
}

// ============================================================
// 查询执行相关接口
// ============================================================

/** 列信息 */
export interface ColumnInfo {
  name: string
  type: string
  isNumeric: boolean
  isDateTime: boolean
}

/** 查询结果 */
export interface QueryResult {
  columns: ColumnInfo[]
  rows: unknown[][]
  rowCount: number
  executionTime: number
  truncated: boolean
}

/** 图表推荐 */
export interface ChartRecommendation {
  recommended: ChartType
  reason: string
  alternatives: ChartType[]
}

/** 图表兼容性验证结果 */
export interface CompatibilityResult {
  compatible: boolean
  warnings: string[]
}

/** 查询执行选项 */
export interface ExecuteOptions {
  /** 超时时间(ms)，默认30000 */
  timeout: number
  /** 最大返回行数，默认1000 */
  maxRows: number
  /** 查询标识，用于取消查询 */
  queryId?: string
}

// ============================================================
// 对话管理相关接口
// ============================================================

/** 对话完整信息 */
export interface Conversation {
  id: string
  title: string
  createdAt: string
  updatedAt: string
  contextSummary?: string
  messageCount: number
}

/** 对话摘要信息（列表展示用） */
export interface ConversationSummary {
  id: string
  title: string
  updatedAt: string
  messageCount: number
}

/** 消息完整信息 */
export interface Message {
  id: string
  conversationId: string
  role: MessageRole
  content: string
  sql?: string
  queryResult?: QueryResult
  createdAt: string
}

/** 消息输入 */
export interface MessageInput {
  role: MessageRole
  content: string
  sql?: string
  queryResult?: unknown
}

// ============================================================
// 技能管理相关接口
// ============================================================

/** 技能参数定义 */
export interface SkillParameter {
  id: string
  skillId: string
  name: string
  type: string
  required: boolean
  constraintDesc?: string
  sortOrder: number
}

/** 技能完整信息 */
export interface Skill {
  id: string
  name: string
  description?: string
  content: string
  fileSize: number
  parameters: SkillParameter[]
  createdAt: string
  updatedAt: string
}

/** 技能列表项（不含完整内容和参数） */
export interface SkillListItem {
  id: string
  name: string
  description?: string
  fileSize: number
  createdAt: string
  updatedAt: string
}

/** 技能文件（导入用） */
export interface SkillFile {
  name: string
  /** 技能文件内容，最大1MB */
  content: string
  format: string
}

/** 技能执行结果 */
export interface SkillExecutionResult {
  success: boolean
  output: unknown
  executionTime: number
  hasData: boolean
  data?: QueryResult
}

// ============================================================
// DDL 管理相关接口
// ============================================================

/** 列定义 */
export interface ColumnDefinition {
  name: string
  type: string
  nullable: boolean
  comment?: string
  isPrimaryKey: boolean
}

/** DDL 信息 */
export interface DDLInfo {
  id: string
  database: string
  tableName: string
  ddlContent: string
  columns: ColumnDefinition[]
  fieldCount: number
  loadedAt: string
}

/** DDL 加载参数 */
export interface DDLLoadParams {
  database: string
  /** 表名列表，为空则加载整个数据库 */
  tables?: string[]
}

// ============================================================
// 通用分页接口
// ============================================================

/** 通用分页参数 */
export interface PaginationParams {
  page: number
  pageSize: number
}

/** 通用分页结果 */
export interface PaginatedResult<T = unknown> {
  items: T[]
  total: number
  page: number
  pageSize: number
}
