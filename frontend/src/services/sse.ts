/**
 * SSE（Server-Sent Events）流式连接封装
 * 用于处理 Agent 查询的流式响应，支持逐步接收事件、错误处理和取消操作。
 */

import type { StreamEvent } from '@/types'

/** SSE 连接回调配置 */
export interface SSECallbacks {
  /** 收到流事件时触发 */
  onMessage: (event: StreamEvent) => void
  /** 连接或解析错误时触发 */
  onError: (error: Error) => void
  /** 流结束时触发 */
  onComplete: () => void
}

/** SSE 连接控制器，用于取消连接 */
export interface SSEConnection {
  /** 中止当前 SSE 连接 */
  abort: () => void
}

/**
 * 创建 SSE 流式连接
 * 通过 fetch + ReadableStream 实现 SSE 解析，支持 AbortController 取消。
 *
 * @param url - SSE 端点完整路径（相对于 /api）
 * @param body - POST 请求体
 * @param callbacks - 事件回调函数集合
 * @returns SSEConnection 控制器
 */
export function createSSEConnection(
  url: string,
  body: unknown,
  callbacks: SSECallbacks
): SSEConnection {
  const abortController = new AbortController()
  const fullUrl = `/api${url}`

  console.log('[SSE] Connecting to', fullUrl)

  // 1.发起 SSE 请求
  fetch(fullUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(body),
    signal: abortController.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        const errorText = await response.text().catch(() => 'Unknown error')
        throw new Error(`SSE connection failed: HTTP ${response.status} - ${errorText}`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('SSE response body is not readable')
      }

      const decoder = new TextDecoder()
      let buffer = ''

      // 2.逐块读取流数据
      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          // 3.流结束前处理缓冲区中剩余的事件数据
          if (buffer.trim()) {
            console.log('[SSE] Processing remaining buffer before complete')
            parseSSEEvent(buffer, callbacks)
          }
          console.log('[SSE] Stream completed')
          callbacks.onComplete()
          break
        }

        buffer += decoder.decode(value, { stream: true })

        // 4.按 SSE 协议解析事件（以双换行分隔）
        const events = buffer.split('\n\n')
        buffer = events.pop() || ''

        for (const eventStr of events) {
          if (!eventStr.trim()) continue
          parseSSEEvent(eventStr, callbacks)
        }
      }
    })
    .catch((error: Error) => {
      // 4.忽略主动取消的错误
      if (error.name === 'AbortError') {
        console.log('[SSE] Connection aborted by user')
        return
      }
      console.error('[SSE] Connection error:', error.message)
      callbacks.onError(error)
    })

  return {
    abort: () => {
      console.log('[SSE] Aborting connection')
      abortController.abort()
    },
  }
}

/**
 * 解析单个 SSE 事件字符串
 * SSE 格式: "event: type\ndata: json_payload"
 *
 * @param eventStr - 原始事件字符串
 * @param callbacks - 回调函数集合
 */
function parseSSEEvent(eventStr: string, callbacks: SSECallbacks): void {
  const lines = eventStr.split('\n')
  let eventType = ''
  let dataStr = ''

  for (const line of lines) {
    if (line.startsWith('event:')) {
      eventType = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataStr = line.slice(5).trim()
    }
  }

  // 1.跳过无数据的事件
  if (!dataStr) return

  try {
    const data = JSON.parse(dataStr)
    const streamEvent: StreamEvent = {
      type: (eventType || data.type) as StreamEvent['type'],
      data: data.data !== undefined ? data.data : data,
    }
    callbacks.onMessage(streamEvent)
  } catch (parseError) {
    console.warn('[SSE] Failed to parse event data:', dataStr, parseError)
    callbacks.onError(new Error(`Failed to parse SSE event: ${dataStr}`))
  }
}
