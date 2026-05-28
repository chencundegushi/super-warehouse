/**
 * useDashboardBuilder Hook 单元测试
 *
 * 验证面板事件处理逻辑：
 * - panel_created 事件正确添加面板
 * - panel_updated 事件正确更新面板
 * - panel_removed 事件正确移除面板
 * - 多个 panel 事件按序处理
 * - isPanelEvent 类型守卫正确判断
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import {
  useDashboardBuilder,
  isPanelEvent,
  type PanelCreatedEventData,
  type PanelUpdatedEventData,
  type PanelRemovedEventData,
} from './useDashboardBuilder'
import type { StreamEvent } from '@/types'

// Mock SSE 模块
vi.mock('@/services/sse', () => ({
  createSSEConnection: vi.fn(),
}))

import { createSSEConnection } from '@/services/sse'

const mockCreateSSEConnection = vi.mocked(createSSEConnection)

describe('isPanelEvent', () => {
  it('returns true for panel_created event', () => {
    const event: StreamEvent = { type: 'panel_created', data: {} }
    expect(isPanelEvent(event)).toBe(true)
  })

  it('returns true for panel_updated event', () => {
    const event: StreamEvent = { type: 'panel_updated', data: {} }
    expect(isPanelEvent(event)).toBe(true)
  })

  it('returns true for panel_removed event', () => {
    const event: StreamEvent = { type: 'panel_removed', data: {} }
    expect(isPanelEvent(event)).toBe(true)
  })

  it('returns false for non-panel events', () => {
    const events: StreamEvent[] = [
      { type: 'thinking', data: {} },
      { type: 'result', data: {} },
      { type: 'error', data: {} },
      { type: 'sql_preview', data: {} },
    ]
    events.forEach((event) => {
      expect(isPanelEvent(event)).toBe(false)
    })
  })
})

describe('useDashboardBuilder', () => {
  let capturedCallbacks: {
    onMessage: (event: StreamEvent) => void
    onError: (error: Error) => void
    onComplete: () => void
  }

  beforeEach(() => {
    vi.clearAllMocks()
    // 捕获 SSE 回调以便在测试中模拟事件
    mockCreateSSEConnection.mockImplementation((_url, _body, callbacks) => {
      capturedCallbacks = callbacks
      return { abort: vi.fn() }
    })
  })

  it('initializes with empty state', () => {
    const { result } = renderHook(() =>
      useDashboardBuilder('test-session')
    )
    expect(result.current.panels).toEqual([])
    expect(result.current.messages).toEqual([])
    expect(result.current.loading).toBe(false)
    expect(result.current.error).toBeNull()
  })

  it('sends message with dashboard_builder mode', () => {
    const { result } = renderHook(() =>
      useDashboardBuilder('test-session', 'conv-1')
    )

    act(() => {
      result.current.sendMessage('我想看本月充值趋势')
    })

    expect(mockCreateSSEConnection).toHaveBeenCalledWith(
      '/chat',
      {
        sessionId: 'test-session',
        message: '我想看本月充值趋势',
        conversationId: 'conv-1',
        autoExecute: true,
        mode: 'dashboard_builder',
      },
      expect.any(Object)
    )
    expect(result.current.loading).toBe(true)
    expect(result.current.messages).toEqual([
      { role: 'user', content: '我想看本月充值趋势' },
    ])
  })

  it('handles panel_created event correctly', () => {
    const { result } = renderHook(() =>
      useDashboardBuilder('test-session')
    )

    act(() => {
      result.current.sendMessage('创建面板')
    })

    const panelData: PanelCreatedEventData = {
      panel_id: 'panel-1',
      title: '本月充值趋势',
      sql: 'SELECT dt, SUM(amount) FROM orders WHERE dt >= DATE_FORMAT(CURDATE(), "%Y-%m-01") GROUP BY dt',
      chart_type: 'line',
      position: { pos_x: 0, pos_y: 0, pos_w: 4, pos_h: 3 },
    }

    act(() => {
      capturedCallbacks.onMessage({
        type: 'panel_created',
        data: panelData,
      })
    })

    expect(result.current.panels).toHaveLength(1)
    expect(result.current.panels[0]).toEqual({
      id: 'panel-1',
      title: '本月充值趋势',
      sql: 'SELECT dt, SUM(amount) FROM orders WHERE dt >= DATE_FORMAT(CURDATE(), "%Y-%m-01") GROUP BY dt',
      chartType: 'line',
      position: { x: 0, y: 0, w: 4, h: 3 },
    })
  })

  it('handles panel_updated event correctly', () => {
    const { result } = renderHook(() =>
      useDashboardBuilder('test-session')
    )

    act(() => {
      result.current.sendMessage('创建面板')
    })

    // 先创建一个面板
    act(() => {
      capturedCallbacks.onMessage({
        type: 'panel_created',
        data: {
          panel_id: 'panel-1',
          title: '原标题',
          sql: 'SELECT 1',
          chart_type: 'table',
          position: { pos_x: 0, pos_y: 0, pos_w: 4, pos_h: 3 },
        } as PanelCreatedEventData,
      })
    })

    // 更新面板
    const updateData: PanelUpdatedEventData = {
      panel_id: 'panel-1',
      title: '新标题',
      chart_type: 'bar',
    }

    act(() => {
      capturedCallbacks.onMessage({
        type: 'panel_updated',
        data: updateData,
      })
    })

    expect(result.current.panels[0].title).toBe('新标题')
    expect(result.current.panels[0].chartType).toBe('bar')
    // 未更新的字段保持不变
    expect(result.current.panels[0].sql).toBe('SELECT 1')
    expect(result.current.panels[0].position).toEqual({ x: 0, y: 0, w: 4, h: 3 })
  })

  it('handles panel_removed event correctly', () => {
    const { result } = renderHook(() =>
      useDashboardBuilder('test-session')
    )

    act(() => {
      result.current.sendMessage('创建面板')
    })

    // 创建两个面板
    act(() => {
      capturedCallbacks.onMessage({
        type: 'panel_created',
        data: {
          panel_id: 'panel-1',
          title: '面板1',
          sql: 'SELECT 1',
          chart_type: 'table',
          position: { pos_x: 0, pos_y: 0, pos_w: 4, pos_h: 3 },
        } as PanelCreatedEventData,
      })
      capturedCallbacks.onMessage({
        type: 'panel_created',
        data: {
          panel_id: 'panel-2',
          title: '面板2',
          sql: 'SELECT 2',
          chart_type: 'bar',
          position: { pos_x: 4, pos_y: 0, pos_w: 4, pos_h: 3 },
        } as PanelCreatedEventData,
      })
    })

    expect(result.current.panels).toHaveLength(2)

    // 移除第一个面板
    act(() => {
      capturedCallbacks.onMessage({
        type: 'panel_removed',
        data: { panel_id: 'panel-1' } as PanelRemovedEventData,
      })
    })

    expect(result.current.panels).toHaveLength(1)
    expect(result.current.panels[0].id).toBe('panel-2')
  })

  it('handles multiple panel events in a single stream', () => {
    const { result } = renderHook(() =>
      useDashboardBuilder('test-session')
    )

    act(() => {
      result.current.sendMessage('我想看充值趋势、日活用户、游戏消耗TOP5')
    })

    // Agent 一次返回3个 panel_created 事件
    act(() => {
      capturedCallbacks.onMessage({
        type: 'panel_created',
        data: {
          panel_id: 'p1',
          title: '充值趋势',
          sql: 'SELECT 1',
          chart_type: 'line',
          position: { pos_x: 0, pos_y: 0, pos_w: 4, pos_h: 3 },
        } as PanelCreatedEventData,
      })
      capturedCallbacks.onMessage({
        type: 'panel_created',
        data: {
          panel_id: 'p2',
          title: '日活用户',
          sql: 'SELECT 2',
          chart_type: 'bar',
          position: { pos_x: 4, pos_y: 0, pos_w: 4, pos_h: 3 },
        } as PanelCreatedEventData,
      })
      capturedCallbacks.onMessage({
        type: 'panel_created',
        data: {
          panel_id: 'p3',
          title: '游戏消耗TOP5',
          sql: 'SELECT 3',
          chart_type: 'pie',
          position: { pos_x: 8, pos_y: 0, pos_w: 4, pos_h: 3 },
        } as PanelCreatedEventData,
      })
    })

    expect(result.current.panels).toHaveLength(3)
    expect(result.current.panels[0].title).toBe('充值趋势')
    expect(result.current.panels[1].title).toBe('日活用户')
    expect(result.current.panels[2].title).toBe('游戏消耗TOP5')
  })

  it('handles error event', () => {
    const { result } = renderHook(() =>
      useDashboardBuilder('test-session')
    )

    act(() => {
      result.current.sendMessage('测试')
    })

    act(() => {
      capturedCallbacks.onMessage({
        type: 'error',
        data: { message: 'SQL 生成失败' },
      })
    })

    expect(result.current.error).toBe('SQL 生成失败')
  })

  it('sets loading to false on stream complete', () => {
    const { result } = renderHook(() =>
      useDashboardBuilder('test-session')
    )

    act(() => {
      result.current.sendMessage('测试')
    })

    expect(result.current.loading).toBe(true)

    act(() => {
      capturedCallbacks.onComplete()
    })

    expect(result.current.loading).toBe(false)
  })

  it('resets all state correctly', () => {
    const { result } = renderHook(() =>
      useDashboardBuilder('test-session')
    )

    act(() => {
      result.current.sendMessage('创建面板')
    })

    act(() => {
      capturedCallbacks.onMessage({
        type: 'panel_created',
        data: {
          panel_id: 'p1',
          title: '面板',
          sql: 'SELECT 1',
          chart_type: 'table',
          position: { pos_x: 0, pos_y: 0, pos_w: 4, pos_h: 3 },
        } as PanelCreatedEventData,
      })
      capturedCallbacks.onComplete()
    })

    expect(result.current.panels).toHaveLength(1)
    expect(result.current.messages).toHaveLength(1)

    act(() => {
      result.current.reset()
    })

    expect(result.current.panels).toEqual([])
    expect(result.current.messages).toEqual([])
    expect(result.current.error).toBeNull()
    expect(result.current.loading).toBe(false)
  })

  it('does not send empty messages', () => {
    const { result } = renderHook(() =>
      useDashboardBuilder('test-session')
    )

    act(() => {
      result.current.sendMessage('   ')
    })

    expect(mockCreateSSEConnection).not.toHaveBeenCalled()
    expect(result.current.loading).toBe(false)
  })
})
