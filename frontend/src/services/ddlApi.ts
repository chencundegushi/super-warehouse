/**
 * DDL 管理 API 服务
 * 封装数据库表结构（DDL）的加载、刷新、查询和缓存清理接口。
 */

import type { DDLInfo, DDLLoadParams } from '@/types'
import { get, post } from './api'

/**
 * 加载指定数据库或表的 DDL 信息
 * 连接 Doris 获取表结构并缓存到本地。
 *
 * @param params - 加载参数（数据库名、可选的表名列表）
 * @returns 加载成功的 DDL 信息数组
 */
export async function loadDDL(params: DDLLoadParams): Promise<DDLInfo[]> {
  console.log('[DDLApi] Loading DDL, database:', params.database, 'tables:', params.tables)
  return post<DDLInfo[]>('/ddl/load', params)
}

/**
 * 刷新已加载的 DDL 信息
 * 重新从 Doris 获取最新表结构并更新缓存。
 *
 * @param tableIds - 可选，指定要刷新的表 ID 列表；为空则刷新全部
 * @returns 刷新后的 DDL 信息数组
 */
export async function refreshDDL(tableIds?: string[]): Promise<DDLInfo[]> {
  console.log('[DDLApi] Refreshing DDL, tableIds:', tableIds)
  return post<DDLInfo[]>('/ddl/refresh', { tableIds })
}

/**
 * 获取所有已加载的 DDL 列表
 * @returns DDL 信息数组
 */
export async function listDDL(): Promise<DDLInfo[]> {
  console.log('[DDLApi] Listing DDL')
  return get<DDLInfo[]>('/ddl/list')
}

/**
 * 清除 DDL 缓存
 * 可按数据库或表粒度清除，不传参数则清除全部缓存。
 * 后端使用查询参数进行过滤。
 *
 * @param database - 可选，指定数据库名
 * @param table - 可选，指定表名
 */
export async function clearCache(database?: string, table?: string): Promise<void> {
  // 1.构建查询参数
  const params: Record<string, string> = {}
  if (database) params.database = database
  if (table) params.table = table

  // 2.构建带查询参数的URL
  const url = new URL('/api/ddl/cache', window.location.origin)
  Object.entries(params).forEach(([key, value]) => {
    url.searchParams.append(key, value)
  })

  console.log('[DDLApi] Clearing cache, url:', url.pathname + url.search)
  const response = await fetch(url.toString(), {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
  })

  if (!response.ok) {
    const detail = await response.text().catch(() => 'Unknown error')
    console.error('[DDLApi] Clear cache failed, status:', response.status, 'detail:', detail)
    throw new Error(`Clear cache failed: ${detail}`)
  }
}
