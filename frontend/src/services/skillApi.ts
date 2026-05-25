/**
 * 技能管理 API 服务
 * 封装技能的导入、导出、CRUD 和执行接口。
 */

import type { Skill, SkillListItem, SkillFile, SkillExecutionResult } from '@/types'
import { get, post, put, del } from './api'

/**
 * 导入技能文件
 * 支持 Claude Code skill 格式，单个文件不超过 1MB。
 *
 * @param file - 技能文件内容
 * @returns 导入后的技能信息
 */
export async function importSkill(file: SkillFile): Promise<Skill> {
  console.log('[SkillApi] Importing skill, name:', file.name)
  return post<Skill>('/skills/import', file)
}

/**
 * 获取所有技能列表
 * 返回技能摘要信息（不含完整内容和参数）。
 *
 * @returns 技能列表项数组
 */
export async function listSkills(): Promise<SkillListItem[]> {
  console.log('[SkillApi] Listing skills')
  return get<SkillListItem[]>('/skills')
}

/**
 * 获取单个技能详情
 * @param id - 技能 ID
 * @returns 技能完整信息
 */
export async function getSkill(id: string): Promise<Skill> {
  console.log('[SkillApi] Getting skill, id:', id)
  return get<Skill>(`/skills/${id}`)
}

/**
 * 更新技能信息
 * @param id - 技能 ID
 * @param updates - 需要更新的字段
 * @returns 更新后的技能信息
 */
export async function updateSkill(id: string, updates: Partial<Skill>): Promise<Skill> {
  console.log('[SkillApi] Updating skill, id:', id)
  return put<Skill>(`/skills/${id}`, updates)
}

/**
 * 删除技能
 * @param id - 技能 ID
 */
export async function deleteSkill(id: string): Promise<void> {
  console.log('[SkillApi] Deleting skill, id:', id)
  return del(`/skills/${id}`)
}

/**
 * 导出技能为文件格式
 * @param id - 技能 ID
 * @returns 技能文件内容
 */
export async function exportSkill(id: string): Promise<SkillFile> {
  console.log('[SkillApi] Exporting skill, id:', id)
  return get<SkillFile>(`/skills/${id}/export`)
}

/**
 * 执行技能
 * 将技能内容和用户参数注入 Agent 触发执行。
 *
 * @param id - 技能 ID
 * @param params - 用户填写的执行参数
 * @returns 技能执行结果
 */
export async function executeSkill(
  id: string,
  params: Record<string, unknown>
): Promise<SkillExecutionResult> {
  console.log('[SkillApi] Executing skill, id:', id)
  return post<SkillExecutionResult>(`/skills/${id}/execute`, { params })
}
