/**
 * Dashboard 构建器 Hook
 *
 * 管理 Dashboard 构建过程中的面板状态，处理 SSE 流中的 panel 事件。
 * 支持 panel_created、panel_updated、panel_removed 三种事件类型，
 * Agent 可在一次 SSE 流中返回多个 panel 事件。
 *
 * 主要功能：
 * - 维护构建中的面板列表
 * - 处理 SSE panel 事件并更新状态
 * - 提供发送消息接口（dashboard_builder 模式）
 * - 提供面板列表重置能力
 */

import { useCallback, useRef, useState } from 'react'
import type { ChartType, StreamEvent } from '@/types'
import type { LayoutPosition } from '@/services/dashboardApi'
import { createSSEConnection, type SSEConnection } from '@/services/sse'

// ============================================================
// 面板事件相关类型定义
// ============================================================

/** panel_created 事件数据 */
export interface PanelCreatedEventData {
  panel_id: string
  title: string
  sql: string
  chart_type: ChartType
  position: {
    pos_x: number
    pos_y: number
    pos_w: number
    pos_h: number
  }
}

/** panel_updated 事件数据 */
export interface PanelUpdatedEventData {
  panel_id: string
  title?: string
  sql?: string
  chart_type?: ChartType
  position?: {
    pos_x: number
    pos_y: number
    pos_w: number
    pos_h: number
  }
}

/** panel_removed 事件数据 */
export interface PanelRemovedEventData {
  panel_id: string
  message?: string
}

/** 构建中的面板信息（前端状态） */
export interface BuilderPanel {
  /** 面板唯一标识 */
  id: string
  /** 面板标题 */
  title: string
  /** SQL 查询语句 */
  sql: string
  /** 图表类型 */
  chartType: ChartType
  /** 布局位置 */
  position: LayoutPosition
}

/** 构建器消息（对话历史） */
export interface BuilderMessage {
  role: 'user' | 'agent'
  content: string
}

/** Hook 返回值 */
export interface UseDashboardBuilderReturn {
  /** 当前构建中的面板列表 */
  panels: BuilderPanel[]
  /** 对话消息列表 */
  messages: BuilderMessage[]
  /** 是否正在加载（SSE 流进行中） */
  loading: boolean
  /** 错误信息 */
  error: string | null
  /** 发送消息给 Agent（dashboard_builder 模式） */
  sendMessage: (message: string) => void
  /** 中止当前 SSE 连接 */
  abort: () => void
  /** 重置所有状态（面板列表、消息、错误） */
  reset: () => void
}

// ============================================================
// 面板事件类型守卫
// ============================================================

/** 判断是否为面板相关事件 */
export function isPanelEvent(event: StreamEvent): boolean {
  return (
    event.type === 'panel_created' ||
    event.type === 'panel_updated' ||
    event.type === 'panel_removed'
  )
}

// ============================================================
// Hook 实现
// ============================================================

/**
 * Dashboard 构建器 Hook
 *
 * 管理面板构建状态，处理 SSE 流中的 panel 事件。
 * 通过 sendMessage 发送消息时自动使用 dashboard_builder 模式，
 * Agent 返回的 panel 事件会实时更新面板列表。
 *
 * @param sessionId - 会话标识
 * @param conversationId - 可选的对话 ID
 * @returns 构建器状态和操作方法
 */
export function useDashboardBuilder(
  sessionId: string,
  conversationId?: string
): UseDashboardBuilderReturn {
  const [panels, setPanels] = useState<BuilderPanel[]>([])
  const [messages, setMessages] = useState<BuilderMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const connectionRef = useRef<SSEConnection | null>(null)

  /**
   * 处理 panel_created 事件
   * 将新面板添加到面板列表
   */
  const handlePanelCreated = useCallback((data: PanelCreatedEventData) => {
    console.log('[DashboardBuilder] Panel created, panel_id:', data.panel_id)
    const newPanel: BuilderPanel = {
      id: data.panel_id,
      title: data.title,
      sql: data.sql,
      chartType: data.chart_type,
      position: {
        x: data.position.pos_x,
        y: data.position.pos_y,
        w: data.position.pos_w,
        h: data.position.pos_h,
      },
    }
    setPanels((prev) => [...prev, newPanel])
  }, [])

  /**
   * 处理 panel_updated 事件
   * 更新已有面板的配置（标题、SQL、图表类型、位置）
   */
  const handlePanelUpdated = useCallback((data: PanelUpdatedEventData) => {
    console.log('[DashboardBuilder] Panel updated, panel_id:', data.panel_id)
    setPanels((prev) =>
      prev.map((panel) => {
        if (panel.id !== data.panel_id) return panel
        return {
          ...panel,
          ...(data.title && { title: data.title }),
          ...(data.sql && { sql: data.sql }),
          ...(data.chart_type && { chartType: data.chart_type }),
          ...(data.position && {
            position: {
              x: data.position.pos_x,
              y: data.position.pos_y,
              w: data.position.pos_w,
              h: data.position.pos_h,
            },
          }),
        }
      })
    )
  }, [])

  /**
   * 处理 panel_removed 事件
   * 从面板列表中移除指定面板
   */
  const handlePanelRemoved = useCallback((data: PanelRemovedEventData) => {
    console.log('[DashboardBuilder] Panel removed, panel_id:', data.panel_id)
    setPanels((prev) => prev.filter((panel) => panel.id !== data.panel_id))
  }, [])

  /**
   * 处理 SSE 流事件
   * 根据事件类型分发到对应处理函数
   */
  const handleStreamEvent = useCallback(
    (event: StreamEvent) => {
      switch (event.type) {
        case 'panel_created':
          handlePanelCreated(event.data as PanelCreatedEventData)
          break
        case 'panel_updated':
          handlePanelUpdated(event.data as PanelUpdatedEventData)
          break
        case 'panel_removed':
          handlePanelRemoved(event.data as PanelRemovedEventData)
          break
        case 'error': {
          const errData = event.data as { message?: string }
          setError(errData.message || '构建过程中发生错误')
          break
        }
        case 'thinking': {
          // 1.Agent 思考中，可用于展示思考状态
          const thinkData = event.data as { content?: string }
          if (thinkData.content) {
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last && last.role === 'agent') {
                // 追加到最后一条 agent 消息
                return [
                  ...prev.slice(0, -1),
                  { ...last, content: last.content + thinkData.content },
                ]
              }
              return [...prev, { role: 'agent', content: thinkData.content! }]
            })
          }
          break
        }
        default:
          // 2.其他事件类型暂不处理
          break
      }
    },
    [handlePanelCreated, handlePanelUpdated, handlePanelRemoved]
  )

  /**
   * 发送消息给 Agent（dashboard_builder 模式）
   * 建立 SSE 连接，接收流式面板事件。
   *
   * @param message - 用户输入的自然语言描述
   */
  const sendMessage = useCallback(
    (message: string) => {
      if (!message.trim()) return

      console.log('[DashboardBuilder] Sending message, sessionId:', sessionId)

      // 1.添加用户消息到对话列表
      setMessages((prev) => [...prev, { role: 'user', content: message }])
      setLoading(true)
      setError(null)

      // 2.建立 SSE 连接（dashboard_builder 模式）
      const connection = createSSEConnection(
        '/chat',
        {
          sessionId,
          message,
          conversationId,
          autoExecute: true,
          mode: 'dashboard_builder',
        },
        {
          onMessage: handleStreamEvent,
          onError: (err: Error) => {
            console.error('[DashboardBuilder] SSE error:', err.message)
            setError(err.message)
            setLoading(false)
          },
          onComplete: () => {
            console.log('[DashboardBuilder] SSE stream completed')
            setLoading(false)
          },
        }
      )

      connectionRef.current = connection
    },
    [sessionId, conversationId, handleStreamEvent]
  )

  /**
   * 中止当前 SSE 连接
   */
  const abort = useCallback(() => {
    if (connectionRef.current) {
      console.log('[DashboardBuilder] Aborting connection')
      connectionRef.current.abort()
      connectionRef.current = null
      setLoading(false)
    }
  }, [])

  /**
   * 重置所有状态
   * 在开始新的 Dashboard 构建时调用。
   */
  const reset = useCallback(() => {
    console.log('[DashboardBuilder] Resetting state')
    abort()
    setPanels([])
    setMessages([])
    setError(null)
  }, [abort])

  return {
    panels,
    messages,
    loading,
    error,
    sendMessage,
    abort,
    reset,
  }
}
