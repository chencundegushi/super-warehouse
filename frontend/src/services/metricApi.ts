/**
 * 指标管理 API 服务
 * 封装指标的 CRUD 操作和 SQL 生成接口。
 */

import type {
  Metric,
  MetricCreateInput,
  MetricUpdateInput,
  PaginatedResult,
  PaginationParams,
} from '@/types'
import { get, post, put, del } from './api'

/**
 * 创建指标
 * @param input - 指标创建参数（名称、描述、SQL模板、参数定义）
 * @returns 创建后的完整指标信息
 */
export async function createMetric(input: MetricCreateInput): Promise<Metric> {
  console.log('[MetricApi] Creating metric, name:', input.name)
  return post<Metric>('/metrics', input)
}

/**
 * 分页查询指标列表
 * @param params - 分页参数
 * @returns 分页结果
 */
export async function listMetrics(params: PaginationParams): Promise<PaginatedResult<Metric>> {
  console.log('[MetricApi] Listing metrics, page:', params.page, 'pageSize:', params.pageSize)
  return get<PaginatedResult<Metric>>('/metrics', {
    page: params.page,
    pageSize: params.pageSize,
  })
}

/**
 * 获取单个指标详情
 * @param id - 指标 ID
 * @returns 指标完整信息
 */
export async function getMetric(id: string): Promise<Metric> {
  console.log('[MetricApi] Getting metric, id:', id)
  return get<Metric>(`/metrics/${id}`)
}

/**
 * 更新指标
 * @param id - 指标 ID
 * @param input - 需要更新的字段
 * @returns 更新后的完整指标信息
 */
export async function updateMetric(id: string, input: MetricUpdateInput): Promise<Metric> {
  console.log('[MetricApi] Updating metric, id:', id)
  return put<Metric>(`/metrics/${id}`, input)
}

/**
 * 删除指标
 * @param id - 指标 ID
 */
export async function deleteMetric(id: string): Promise<void> {
  console.log('[MetricApi] Deleting metric, id:', id)
  return del(`/metrics/${id}`)
}

/**
 * 根据指标名称和描述自动生成参考 SQL
 * Agent 会结合 DDL 信息生成 SQL 供用户参考和修改。
 *
 * @param metricName - 指标名称
 * @param description - 指标用途说明
 * @returns 生成的参考 SQL 字符串
 */
export async function generateSQL(metricName: string, description: string): Promise<string> {
  console.log('[MetricApi] Generating SQL for metric:', metricName)
  const result = await post<{ sql: string }>('/metrics/generate-sql', {
    name: metricName,
    description,
  })
  return result.sql
}
