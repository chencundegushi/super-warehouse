/**
 * 系统设置 API 服务
 * 提供系统配置查询和快捷标签管理接口
 */

import { get, put } from './api'

/** 快捷标签数据结构 */
export interface SuggestionItem {
  icon: string
  label: string
  text: string
}

/** 系统配置信息 */
export interface SystemSettings {
  app_name: string
  app_version: string
  debug: boolean
  llm_model: string
  llm_base_url: string
  llm_temperature: number
  llm_max_tokens: number
  doris_host: string
  doris_port: number
  doris_database: string
  query_timeout_seconds: number
  query_max_rows: number
  query_max_retries: number
  conversation_max_turns: number
  metric_match_threshold: number
}

/**
 * 获取系统配置信息
 * @returns 系统配置
 */
export function getSystemSettings(): Promise<SystemSettings> {
  return get<SystemSettings>('/settings/system')
}

/**
 * 获取快捷问题标签列表
 * @returns 标签列表
 */
export function getSuggestions(): Promise<SuggestionItem[]> {
  return get<SuggestionItem[]>('/settings/suggestions')
}

/**
 * 更新快捷问题标签列表
 * @param suggestions - 新的标签列表
 * @returns 更新结果
 */
export function updateSuggestions(suggestions: SuggestionItem[]): Promise<{ success: boolean; count: number }> {
  return put<{ success: boolean; count: number }>('/settings/suggestions', { suggestions })
}
