/**
 * 文件型技能 API 服务
 * 管理 backend/skills/ 目录下的文件型技能。
 */

import { get, del } from './api'

/** 文件型技能信息 */
export interface SkillFileInfo {
  name: string
  displayName: string
  description: string
  hasScript: boolean
  files: string[]
}

/** 文件型技能详情 */
export interface SkillFileDetail {
  name: string
  displayName: string
  description: string
  skillMdContent: string
  hasScript: boolean
  files: Array<{ name: string; size: number; content?: string }>
}

/**
 * 获取文件型技能列表
 */
export async function listSkillFiles(): Promise<SkillFileInfo[]> {
  return get<SkillFileInfo[]>('/skill-files')
}

/**
 * 获取技能详情
 */
export async function getSkillFileDetail(name: string): Promise<SkillFileDetail> {
  return get<SkillFileDetail>(`/skill-files/${name}`)
}

/**
 * 导入技能目录（通过 FormData 上传多文件）
 */
export async function importSkillDirectory(files: FileList): Promise<SkillFileInfo> {
  const formData = new FormData()
  for (let i = 0; i < files.length; i++) {
    const file = files[i]
    // webkitRelativePath 包含相对路径如 "business-analysis/SKILL.md"
    const relativePath = (file as any).webkitRelativePath || file.name
    formData.append('files', file, relativePath)
  }

  const response = await fetch('/api/skill-files/import', {
    method: 'POST',
    body: formData,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: '导入失败' }))
    throw new Error(error.detail || '导入失败')
  }

  return response.json()
}

/**
 * 删除文件型技能
 */
export async function deleteSkillFile(name: string): Promise<void> {
  return del(`/skill-files/${name}`)
}
