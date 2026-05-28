/**
 * 表血缘关系 API 服务
 * 提供血缘分析、缓存查询和原始 Job 数据查询接口。
 */

import { get, post } from './api'

/** 层级信息 */
export interface LayerInfo {
  name: string
  level: number
  description: string
  tables: string[]
}

/** 血缘边（表之间的依赖关系） */
export interface LineageEdge {
  source: string
  target: string
  job_name: string
  schedule: string
}

/** 表信息 */
export interface TableInfo {
  name: string
  layer: string
  description: string
}

/** 血缘分析结果 */
export interface LineageData {
  layers: LayerInfo[]
  edges: LineageEdge[]
  tables: TableInfo[]
}

/** Job 列表响应 */
export interface JobsResponse {
  jobs: Record<string, unknown>[]
  count: number
}

/**
 * 分析表血缘关系
 * @param forceRefresh - 是否强制刷新（忽略缓存）
 * @returns 血缘分析结果
 */
export async function analyzeLineage(forceRefresh = false): Promise<LineageData> {
  console.log('[LineageApi] Analyzing lineage, forceRefresh:', forceRefresh)
  return post<LineageData>('/lineage/analyze', { forceRefresh })
}

/**
 * 获取缓存的血缘关系数据
 * @returns 缓存的血缘数据
 */
export async function getCachedLineage(): Promise<LineageData> {
  console.log('[LineageApi] Getting cached lineage')
  return get<LineageData>('/lineage/cache')
}

/**
 * 获取原始 Job 列表
 * @returns Job 列表数据
 */
export async function getJobs(): Promise<JobsResponse> {
  console.log('[LineageApi] Getting jobs list')
  return get<JobsResponse>('/lineage/jobs')
}
