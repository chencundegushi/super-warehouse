/**
 * 对话查询 API 服务
 * 封装与 Agent 编排器交互的接口，包括发送消息（SSE流式）、确认SQL和取消查询。
 */

import type { QueryRequest } from '@/types'
import { post } from './api'
import { createSSEConnection, type SSECallbacks, type SSEConnection } from './sse'

/**
 * 发送查询消息，建立 SSE 流式连接
 * Agent 会通过 SSE 逐步返回 thinking、sql_preview、result 等事件。
 *
 * @param request - 查询请求参数
 * @param callbacks - SSE 事件回调
 * @returns SSE 连接控制器，可用于中止连接
 */
export function sendMessage(request: QueryRequest, callbacks: SSECallbacks): SSEConnection {
  console.log('[ChatApi] Sending message, sessionId:', request.sessionId)
  return createSSEConnection('/chat', request, callbacks)
}

/**
 * 确认或拒绝 Agent 生成的 SQL（SSE 流式响应）
 * 用户确认时后端执行 SQL 并通过 SSE 返回 executing、result、chart_recommendation 事件；
 * 用户拒绝时后端根据反馈重新生成 SQL 并返回新的 sql_preview 事件。
 *
 * @param sessionId - 会话标识
 * @param confirmed - 是否确认执行
 * @param callbacks - SSE 事件回调
 * @param feedback - 拒绝时的修改意见（可选）
 * @returns SSE 连接控制器
 */
export function confirmSQL(
  sessionId: string,
  confirmed: boolean,
  callbacks: SSECallbacks,
  feedback?: string
): SSEConnection {
  console.log('[ChatApi] Confirm SQL, sessionId:', sessionId, 'confirmed:', confirmed)
  return createSSEConnection('/chat/confirm', { sessionId, confirmed, feedback }, callbacks)
}

/**
 * 取消正在执行的查询
 * 当查询执行时间过长时，用户可主动取消。
 *
 * @param sessionId - 会话标识
 * @returns 操作结果
 */
export async function cancelQuery(sessionId: string): Promise<void> {
  console.log('[ChatApi] Cancel query, sessionId:', sessionId)
  await post('/chat/cancel', { sessionId })
}
