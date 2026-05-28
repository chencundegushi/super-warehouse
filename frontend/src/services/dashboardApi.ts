/**
 * Dashboard（智能大屏）API 服务
 * 封装 Dashboard 的 CRUD、面板管理和数据执行相关 HTTP 请求。
 */

import type { ChartType, PaginatedResult, QueryResult } from '@/types'
import { get, post, put, del } from './api'

// ============================================================
// Dashboard 相关类型定义
// ============================================================

/** 面板布局位置 */
export interface LayoutPosition {
  /** 网格列位置 (0-11) */
  x: number
  /** 网格行位置 */
  y: number
  /** 宽度（列数，最小3） */
  w: number
  /** 高度（行数，最小2） */
  h: number
}

/** 面板完整信息 */
export interface Panel {
  id: string
  dashboardId: string
  title: string
  sql: string
  chartType: ChartType
  position: LayoutPosition
  sortOrder: number
  createdAt: string
  updatedAt: string
}

/** Dashboard 完整信息（含面板列表） */
export interface Dashboard {
  id: string
  name: string
  panelCount: number
  panels: Panel[]
  createdAt: string
  updatedAt: string
  lastAccessedAt: string
}

/** Dashboard 摘要信息（列表展示用） */
export interface DashboardSummary {
  id: string
  name: string
  panelCount: number
  createdAt: string
  updatedAt: string
  lastAccessedAt: string
}

/** 单面板执行结果 */
export interface PanelExecutionResult {
  panelId: string
  success: boolean
  data?: QueryResult
  error?: string
}

// ============================================================
// Dashboard CRUD 接口
// ============================================================

/**
 * 创建 Dashboard
 * @param name - 大屏名称（≤64字符，系统内唯一）
 * @param panels - 可选的初始面板列表
 * @returns 创建后的 Dashboard 完整信息
 */
export async function createDashboard(
  name: string,
  panels?: Array<{
    title: string
    sql: string
    chartType: ChartType
    posX: number
    posY: number
    posW: number
    posH: number
  }>
): Promise<Dashboard> {
  console.log('[DashboardApi] Creating dashboard, name:', name)
  return post<Dashboard>('/dashboards', { name, panels })
}

/**
 * 获取 Dashboard 详情（含所有面板配置）
 * @param id - Dashboard ID
 * @returns Dashboard 完整信息
 */
export async function getDashboard(id: string): Promise<Dashboard> {
  console.log('[DashboardApi] Getting dashboard, id:', id)
  // 后端返回扁平字段 posX/posY/posW/posH，需转换为嵌套 position 对象
  const raw = await get<Record<string, unknown>>(`/dashboards/${id}`)
  const rawPanels = (raw.panels || []) as Array<Record<string, unknown>>
  const panels: Panel[] = rawPanels.map((p) => ({
    id: p.id as string,
    dashboardId: p.dashboardId as string,
    title: p.title as string,
    sql: p.sql as string,
    chartType: p.chartType as ChartType,
    position: {
      x: (p.posX ?? p.pos_x ?? 0) as number,
      y: (p.posY ?? p.pos_y ?? 0) as number,
      w: (p.posW ?? p.pos_w ?? 4) as number,
      h: (p.posH ?? p.pos_h ?? 3) as number,
    },
    sortOrder: (p.sortOrder ?? 0) as number,
    createdAt: p.createdAt as string,
    updatedAt: p.updatedAt as string,
  }))
  return {
    id: raw.id as string,
    name: raw.name as string,
    panelCount: (raw.panelCount ?? 0) as number,
    panels,
    createdAt: raw.createdAt as string,
    updatedAt: raw.updatedAt as string,
    lastAccessedAt: raw.lastAccessedAt as string,
  }
}

/**
 * 更新 Dashboard（名称、面板、布局等）
 * @param id - Dashboard ID
 * @param data - 更新数据
 * @returns 更新后的 Dashboard 完整信息
 */
export async function updateDashboard(
  id: string,
  data: {
    name?: string
    panels?: Array<{
      id?: string
      title: string
      sql: string
      chartType: ChartType
      position: LayoutPosition
    }>
  }
): Promise<Dashboard> {
  console.log('[DashboardApi] Updating dashboard, id:', id)
  // 将嵌套 position 转换为后端期望的扁平 posX/posY/posW/posH 格式
  const payload: Record<string, unknown> = {}
  if (data.name !== undefined) payload.name = data.name
  if (data.panels) {
    payload.panels = data.panels.map((p) => ({
      id: p.id,
      title: p.title,
      sql: p.sql,
      chartType: p.chartType,
      posX: p.position.x,
      posY: p.position.y,
      posW: p.position.w,
      posH: p.position.h,
    }))
  }
  return put<Dashboard>(`/dashboards/${id}`, payload)
}

/**
 * 删除 Dashboard
 * @param id - Dashboard ID
 */
export async function deleteDashboard(id: string): Promise<void> {
  console.log('[DashboardApi] Deleting dashboard, id:', id)
  return del(`/dashboards/${id}`)
}

/**
 * 分页获取 Dashboard 列表
 * 按最近访问时间降序排列。
 *
 * @param page - 页码，默认 1
 * @param pageSize - 每页数量，默认 20
 * @returns 分页结果
 */
export async function listDashboards(
  page: number = 1,
  pageSize: number = 20
): Promise<PaginatedResult<DashboardSummary>> {
  console.log('[DashboardApi] Listing dashboards, page:', page, 'pageSize:', pageSize)
  return get<PaginatedResult<DashboardSummary>>('/dashboards', {
    page,
    pageSize,
  })
}

// ============================================================
// 面板数据执行接口
// ============================================================

/**
 * 执行单个面板的 SQL 查询
 * 执行前会进行安全校验，仅允许 SELECT 语句。
 *
 * @param dashboardId - Dashboard ID
 * @param panelId - Panel ID
 * @returns 查询结果
 */
export async function executePanel(
  dashboardId: string,
  panelId: string
): Promise<QueryResult> {
  console.log('[DashboardApi] Executing panel, dashboardId:', dashboardId, 'panelId:', panelId)
  return post<QueryResult>(`/dashboards/${dashboardId}/panels/${panelId}/execute`)
}

/**
 * 执行 Dashboard 所有面板的 SQL 查询
 * 各面板独立执行，单面板失败不影响其他面板。
 *
 * @param dashboardId - Dashboard ID
 * @returns 所有面板的执行结果数组
 */
export async function executeAllPanels(
  dashboardId: string
): Promise<PanelExecutionResult[]> {
  console.log('[DashboardApi] Executing all panels, dashboardId:', dashboardId)
  // 后端返回 { dashboardId, results: [...] } 包装结构
  const raw = await post<Record<string, unknown>>(`/dashboards/${dashboardId}/execute-all`)
  const results = (raw.results || []) as Array<Record<string, unknown>>
  return results.map((r) => ({
    panelId: (r.panelId ?? r.panel_id) as string,
    success: !r.error,
    data: r.error ? undefined : {
      columns: (r.columns || []) as QueryResult['columns'],
      rows: (r.rows || []) as QueryResult['rows'],
      rowCount: (r.rowCount ?? r.row_count ?? 0) as number,
      executionTime: (r.executionTime ?? r.execution_time ?? 0) as number,
      truncated: (r.truncated ?? false) as boolean,
    },
    error: r.error as string | undefined,
  }))
}
