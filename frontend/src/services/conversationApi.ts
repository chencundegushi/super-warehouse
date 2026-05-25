/**
 * 对话历史管理 API 服务
 * 封装对话的列表查询、详情获取、消息获取、删除和搜索接口。
 */

import type {
  Conversation,
  ConversationSummary,
  Message,
  PaginatedResult,
  PaginationParams,
} from '@/types'
import { get, del } from './api'

/**
 * 分页获取对话列表
 * 按最近活跃时间降序排列，每页最多 20 条。
 *
 * @param params - 分页参数
 * @returns 分页结果
 */
export async function listConversations(
  params: PaginationParams
): Promise<PaginatedResult<ConversationSummary>> {
  console.log('[ConversationApi] Listing conversations, page:', params.page)
  return get<PaginatedResult<ConversationSummary>>('/conversations', {
    page: params.page,
    pageSize: params.pageSize,
  })
}

/**
 * 获取单个对话详情
 * @param id - 对话 ID
 * @returns 对话完整信息
 */
export async function getConversation(id: string): Promise<Conversation> {
  console.log('[ConversationApi] Getting conversation, id:', id)
  return get<Conversation>(`/conversations/${id}`)
}

/**
 * 获取对话的所有消息
 * @param conversationId - 对话 ID
 * @returns 消息数组
 */
export async function getMessages(conversationId: string): Promise<Message[]> {
  console.log('[ConversationApi] Getting messages, conversationId:', conversationId)
  return get<Message[]>(`/conversations/${conversationId}/messages`)
}

/**
 * 删除对话
 * 永久删除该会话的所有存储数据。
 *
 * @param id - 对话 ID
 */
export async function deleteConversation(id: string): Promise<void> {
  console.log('[ConversationApi] Deleting conversation, id:', id)
  return del(`/conversations/${id}`)
}

/**
 * 搜索对话历史
 * 支持按关键词和时间范围搜索，结果按时间降序排列，最多返回 50 条。
 *
 * @param keyword - 可选，搜索关键词（匹配标题和消息文本）
 * @param startTime - 可选，起始时间（ISO 8601 格式）
 * @param endTime - 可选，结束时间（ISO 8601 格式）
 * @returns 匹配的对话摘要数组
 */
export async function searchConversations(
  keyword?: string,
  startTime?: string,
  endTime?: string
): Promise<ConversationSummary[]> {
  console.log('[ConversationApi] Searching conversations, keyword:', keyword)
  return get<ConversationSummary[]>('/conversations/search', {
    keyword,
    startTime,
    endTime,
  })
}
