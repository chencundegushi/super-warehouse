/**
 * Dashboard 构建器页面
 * 通过对话方式创建 Dashboard，左侧对话输入区，右侧实时预览区（网格布局）。
 * 对话消息通过 SSE 流式接收，面板配置通过特殊事件类型推送。
 * 支持继续对话修改/添加/删除面板，提供保存按钮。
 *
 * @module DashboardBuilder
 */

import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Input, Button, Spin, Typography, Space, Modal, message } from 'antd'
import {
  SendOutlined,
  LoadingOutlined,
  SaveOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons'
import { Responsive } from 'react-grid-layout'
import type { StreamEvent } from '@/types'
import type { SSEConnection } from '@/services/sse'
import { createSSEConnection } from '@/services/sse'
import { createDashboard, type LayoutPosition } from '@/services/dashboardApi'
import type { ChartType, QueryResult } from '@/types'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import './Dashboard.css'
import DashboardPanel from '@/components/DashboardPanel'
import type { Panel } from '@/services/dashboardApi'

const { TextArea } = Input
const { Text, Paragraph } = Typography
// 使用 Responsive 组件（新版 react-grid-layout 不需要 WidthProvider）

// ============================================================
// 类型定义
// ============================================================

/** 构建器中的面板信息（含预览数据） */
interface BuilderPanel {
  id: string
  title: string
  sql: string
  chartType: ChartType
  position: LayoutPosition
  queryData?: QueryResult
  queryError?: string
}

/** 对话消息 */
interface BuilderMessage {
  id: string
  role: 'user' | 'agent'
  content: string
  isStreaming?: boolean
}

/** 长时间等待阈值（毫秒） */
const LONG_WAIT_THRESHOLD = 15000

/**
 * 生成 UUID v4 格式的会话标识
 */
function generateSessionId(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

// ============================================================
// 主组件
// ============================================================

/**
 * Dashboard 构建器主组件
 * 左右分栏布局：左侧对话区（~40%），右侧预览区（~60%）
 */
function DashboardBuilder() {
  const navigate = useNavigate()

  // 1.对话状态
  const [messages, setMessages] = useState<BuilderMessage[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [showLongWait, setShowLongWait] = useState(false)

  // 2.面板状态
  const [panels, setPanels] = useState<BuilderPanel[]>([])

  // 3.保存弹窗状态
  const [saveModalVisible, setSaveModalVisible] = useState(false)
  const [dashboardName, setDashboardName] = useState('')
  const [isSaving, setIsSaving] = useState(false)

  // Refs
  const sessionIdRef = useRef<string>(generateSessionId())
  const sseConnectionRef = useRef<SSEConnection | null>(null)
  const longWaitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const messageListRef = useRef<HTMLDivElement>(null)
  const streamingMessageIdRef = useRef<string | null>(null)

  console.log('[DashboardBuilder] Rendered, panels:', panels.length, 'messages:', messages.length)

  // ============================================================
  // 工具函数
  // ============================================================

  /** 滚动消息列表到底部 */
  const scrollToBottom = useCallback(() => {
    if (messageListRef.current) {
      messageListRef.current.scrollTop = messageListRef.current.scrollHeight
    }
  }, [])

  useEffect(() => { scrollToBottom() }, [messages, scrollToBottom])

  /** 清除长时间等待计时器 */
  const clearLongWaitTimer = useCallback(() => {
    if (longWaitTimerRef.current) {
      clearTimeout(longWaitTimerRef.current)
      longWaitTimerRef.current = null
    }
    setShowLongWait(false)
  }, [])

  /** 启动长时间等待计时器 */
  const startLongWaitTimer = useCallback(() => {
    clearLongWaitTimer()
    longWaitTimerRef.current = setTimeout(() => setShowLongWait(true), LONG_WAIT_THRESHOLD)
  }, [clearLongWaitTimer])

  /** 更新当前流式消息内容 */
  const updateStreamingMessage = useCallback((content: string) => {
    const msgId = streamingMessageIdRef.current
    if (!msgId) return
    setMessages(prev => prev.map(msg =>
      msg.id === msgId ? { ...msg, content } : msg
    ))
  }, [])

  // ============================================================
  // SSE 事件处理
  // ============================================================

  /** 处理 SSE 流事件 */
  const handleStreamEvent = useCallback((event: StreamEvent) => {
    console.log('[DashboardBuilder] Stream event, type:', event.type)
    const eventType = event.type as string

    switch (eventType) {
      case 'thinking': {
        const data = event.data as { message?: string } | string
        const msg = typeof data === 'string' ? data : (data?.message || '')
        updateStreamingMessage(msg)
        break
      }
      case 'clarification': {
        const data = event.data as { message?: string } | string
        const msg = typeof data === 'string' ? data : (data?.message || '')
        updateStreamingMessage(msg)
        break
      }
      case 'tool_call': {
        // 工具调用中，不做特殊处理
        break
      }
      case 'panel_created': {
        // 面板创建事件：添加新面板到预览区
        const data = event.data as {
          panel_id: string; title: string; sql: string;
          chart_type: string; position: { pos_x: number; pos_y: number; pos_w: number; pos_h: number }
          query_data?: QueryResult
          query_error?: string
        }
        console.log('[DashboardBuilder] Panel created:', data.panel_id, data.title)
        // 将后端 pos_x/pos_y/pos_w/pos_h 映射为前端 x/y/w/h
        const newPanel: BuilderPanel = {
          id: data.panel_id,
          title: data.title,
          sql: data.sql,
          chartType: data.chart_type as ChartType,
          position: {
            x: data.position.pos_x,
            y: data.position.pos_y,
            w: data.position.pos_w,
            h: data.position.pos_h,
          },
          queryData: data.query_data || undefined,
          queryError: data.query_error || undefined,
        }
        setPanels(prev => [...prev, newPanel])
        break
      }

      case 'panel_updated': {
        // 面板更新事件：更新已有面板配置（含新的查询数据）
        const data = event.data as {
          panel_id: string; title?: string; sql?: string;
          chart_type?: string; position?: { pos_x: number; pos_y: number; pos_w: number; pos_h: number }
          query_data?: QueryResult
          query_error?: string
        }
        console.log('[DashboardBuilder] Panel updated:', data.panel_id)
        setPanels(prev => prev.map(p => {
          if (p.id !== data.panel_id) return p
          return {
            ...p,
            ...(data.title && { title: data.title }),
            ...(data.sql && { sql: data.sql }),
            ...(data.chart_type && { chartType: data.chart_type as ChartType }),
            ...(data.position && { position: {
              x: data.position.pos_x,
              y: data.position.pos_y,
              w: data.position.pos_w,
              h: data.position.pos_h,
            } }),
            // 更新查询数据（无论有无都覆盖，清除旧的错误/数据）
            queryData: data.query_data || undefined,
            queryError: data.query_error || undefined,
          }
        }))
        break
      }
      case 'panel_removed': {
        // 面板删除事件：从预览区移除面板
        const data = event.data as { panel_id: string }
        console.log('[DashboardBuilder] Panel removed:', data.panel_id)
        setPanels(prev => prev.filter(p => p.id !== data.panel_id))
        break
      }
      case 'error': {
        const data = event.data as { message?: string }
        updateStreamingMessage(`❌ ${data?.message || '发生错误'}`)
        break
      }
      default: {
        // 其他事件类型（如 result 等），更新消息内容
        if (event.data) {
          const data = event.data as { message?: string } | string
          const msg = typeof data === 'string' ? data : (data?.message || '')
          if (msg) updateStreamingMessage(msg)
        }
      }
    }
  }, [updateStreamingMessage])

  /** 处理 SSE 流完成 */
  const handleStreamComplete = useCallback(() => {
    console.log('[DashboardBuilder] Stream completed')
    setIsLoading(false)
    clearLongWaitTimer()
    const msgId = streamingMessageIdRef.current
    if (msgId) {
      setMessages(prev => prev.map(msg =>
        msg.id === msgId ? { ...msg, isStreaming: false } : msg
      ))
    }
    streamingMessageIdRef.current = null
    sseConnectionRef.current = null
  }, [clearLongWaitTimer])

  /** 处理 SSE 流错误 */
  const handleStreamError = useCallback((error: Error) => {
    console.error('[DashboardBuilder] Stream error:', error.message)
    setIsLoading(false)
    clearLongWaitTimer()
    const msgId = streamingMessageIdRef.current
    if (msgId) {
      setMessages(prev => prev.map(msg =>
        msg.id === msgId
          ? { ...msg, content: `❌ 连接错误: ${error.message}`, isStreaming: false }
          : msg
      ))
    }
    streamingMessageIdRef.current = null
    sseConnectionRef.current = null
  }, [clearLongWaitTimer])

  // ============================================================
  // 用户操作处理
  // ============================================================

  /** 发送消息到 Agent（dashboard_builder 模式） */
  const handleSend = useCallback(() => {
    const text = inputValue.trim()
    if (!text || isLoading) return
    console.log('[DashboardBuilder] Sending message:', text.substring(0, 50))

    // 1.添加用户消息和 Agent 占位消息
    const userMsg: BuilderMessage = { id: `user-${Date.now()}`, role: 'user', content: text }
    const agentMsgId = `agent-${Date.now()}`
    const agentMsg: BuilderMessage = { id: agentMsgId, role: 'agent', content: '', isStreaming: true }
    setMessages(prev => [...prev, userMsg, agentMsg])
    setInputValue('')
    setIsLoading(true)
    streamingMessageIdRef.current = agentMsgId
    startLongWaitTimer()

    // 2.通过 SSE 发送消息，使用 dashboard_builder 模式
    const connection = createSSEConnection('/chat', {
      sessionId: sessionIdRef.current,
      message: text,
      mode: 'dashboard_builder',
      autoExecute: true,
    }, {
      onMessage: handleStreamEvent,
      onComplete: handleStreamComplete,
      onError: handleStreamError,
    })
    sseConnectionRef.current = connection
  }, [inputValue, isLoading, startLongWaitTimer, handleStreamEvent, handleStreamComplete, handleStreamError])

  /** 取消当前查询 */
  const handleCancel = useCallback(() => {
    console.log('[DashboardBuilder] User cancelling query')
    if (sseConnectionRef.current) {
      sseConnectionRef.current.abort()
      sseConnectionRef.current = null
    }
    setIsLoading(false)
    clearLongWaitTimer()
    const msgId = streamingMessageIdRef.current
    if (msgId) {
      setMessages(prev => prev.map(msg =>
        msg.id === msgId ? { ...msg, content: msg.content || '已取消', isStreaming: false } : msg
      ))
    }
    streamingMessageIdRef.current = null
  }, [clearLongWaitTimer])

  /** 键盘事件：Enter 发送，Shift+Enter 换行 */
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  /** 保存 Dashboard */
  const handleSave = useCallback(async () => {
    const name = dashboardName.trim()
    if (!name) {
      message.warning('请输入大屏名称')
      return
    }
    if (name.length > 64) {
      message.warning('名称不能超过64个字符')
      return
    }
    if (panels.length === 0) {
      message.warning('请先通过对话创建至少一个面板')
      return
    }

    console.log('[DashboardBuilder] Saving dashboard, name:', name, 'panels:', panels.length)
    setIsSaving(true)
    try {
      const panelData = panels.map(p => ({
        title: p.title,
        sql: p.sql,
        chartType: p.chartType,
        posX: p.position.x,
        posY: p.position.y,
        posW: p.position.w,
        posH: p.position.h,
      }))
      const result = await createDashboard(name, panelData)
      console.log('[DashboardBuilder] Dashboard saved, id:', result.id)
      message.success('大屏保存成功')
      setSaveModalVisible(false)
      setDashboardName('')
      // 跳转到查看页
      navigate(`/dashboards/${result.id}`)
    } catch (error: unknown) {
      console.error('[DashboardBuilder] Save failed:', error)
      const errMsg = error instanceof Error ? error.message : '保存失败'
      if (errMsg.includes('already exists') || errMsg.includes('唯一') || errMsg.includes('unique')) {
        message.error('名称已被使用，请修改')
      } else {
        message.error(errMsg)
      }
    } finally {
      setIsSaving(false)
    }
  }, [dashboardName, panels, navigate])

  // 组件卸载时清理
  useEffect(() => {
    return () => {
      if (sseConnectionRef.current) sseConnectionRef.current.abort()
      if (longWaitTimerRef.current) clearTimeout(longWaitTimerRef.current)
    }
  }, [])

  // ============================================================
  // 布局计算
  // ============================================================

  /** 将面板列表转换为 react-grid-layout 的 layout 配置 */
  const gridLayout = panels.map(p => ({
    i: p.id,
    x: p.position.x,
    y: p.position.y,
    w: p.position.w,
    h: p.position.h,
    minW: 3,
    minH: 2,
  }))

  // ============================================================
  // 渲染
  // ============================================================

  return (
    <div style={{
      display: 'flex',
      height: '100vh',
      overflow: 'hidden',
    }}>
      {/* 左侧：对话输入区（~40%） */}
      <div style={{
        width: '40%',
        minWidth: 360,
        display: 'flex',
        flexDirection: 'column',
        borderRight: '1px solid var(--color-border-secondary)',
        background: 'var(--color-bg-container)',
      }}>
        {/* 对话区顶部标题 */}
        <div style={{
          padding: '12px 16px',
          borderBottom: '1px solid var(--color-border-secondary)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <Text strong style={{ fontSize: 15 }}>大屏构建对话</Text>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={() => setSaveModalVisible(true)}
            disabled={panels.length === 0}
            size="small"
          >
            保存大屏
          </Button>
        </div>

        {/* 消息列表 */}
        <div
          ref={messageListRef}
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '16px',
          }}
        >
          {messages.length === 0 && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              textAlign: 'center',
            }}>
              <Text type="secondary" style={{ fontSize: 14 }}>
                描述你想要的大屏内容，例如：<br />
                "我想看本月充值趋势、日活用户数、游戏消耗TOP5"
              </Text>
            </div>
          )}
          {messages.map((msg) => (
            <div
              key={msg.id}
              style={{
                display: 'flex',
                justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                marginBottom: 12,
              }}
            >
              <div style={{
                maxWidth: '85%',
                padding: '8px 12px',
                borderRadius: 8,
                wordBreak: 'break-word',
                ...(msg.role === 'user'
                  ? { background: 'var(--color-primary)', color: '#fff', borderBottomRightRadius: 2 }
                  : { background: 'var(--color-bg-elevated)', border: '1px solid var(--color-border-secondary)', borderBottomLeftRadius: 2 }
                ),
              }}>
                {msg.content ? (
                  <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap', color: 'inherit' }}>
                    {msg.content}
                  </Paragraph>
                ) : msg.isStreaming ? (
                  <Spin indicator={<LoadingOutlined spin />} size="small" />
                ) : null}
              </div>
            </div>
          ))}

          {/* 加载状态 */}
          {isLoading && (
            <div style={{ padding: '8px 0' }}>
              <Space>
                <Spin indicator={<LoadingOutlined spin />} size="small" />
                <Text type="secondary">正在生成面板...</Text>
              </Space>
              {showLongWait && (
                <div style={{ marginTop: 4 }}>
                  <Text type="warning" style={{ fontSize: 12 }}>仍在处理中...</Text>
                  <Button
                    type="link"
                    danger
                    icon={<CloseCircleOutlined />}
                    onClick={handleCancel}
                    size="small"
                  >
                    取消
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* 输入区域 */}
        <div style={{
          padding: '12px 16px',
          borderTop: '1px solid var(--color-border-secondary)',
          background: 'var(--color-bg-container)',
        }}>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8 }}>
            <TextArea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="描述你想要的大屏面板，按 Enter 发送"
              autoSize={{ minRows: 1, maxRows: 4 }}
              disabled={isLoading}
              style={{ flex: 1 }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSend}
              disabled={!inputValue.trim() || isLoading}
              style={{ height: 36, width: 36, flexShrink: 0 }}
            />
          </div>
        </div>
      </div>

      {/* 右侧：实时预览区（~60%） */}
      <div style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        background: 'var(--color-bg-layout)',
      }}>
        {/* 预览区顶部 */}
        <div style={{
          padding: '12px 16px',
          borderBottom: '1px solid var(--color-border-secondary)',
          background: 'var(--color-bg-container)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <Text strong style={{ fontSize: 15 }}>面板预览</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {panels.length > 0 ? `${panels.length} 个面板` : '暂无面板'}
          </Text>
        </div>

        {/* 网格预览区 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          {panels.length === 0 ? (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              minHeight: 300,
            }}>
              <Text type="secondary" style={{ fontSize: 14 }}>
                通过左侧对话创建面板后，将在此处实时预览
              </Text>
            </div>
          ) : (
            <Responsive
              className="dashboard-grid-layout"
              width={800}
              layouts={{ lg: gridLayout }}
              breakpoints={{ lg: 600, md: 400, sm: 0 }}
              cols={{ lg: 12, md: 12, sm: 12 }}
              rowHeight={80}
              margin={[12, 12]}
            >

              {panels.map(panel => {
                // 将 BuilderPanel 转换为 DashboardPanel 需要的 Panel 类型
                const panelProps: Panel = {
                  id: panel.id,
                  dashboardId: '',
                  title: panel.title,
                  sql: panel.sql,
                  chartType: panel.chartType,
                  position: panel.position,
                  sortOrder: 0,
                  createdAt: '',
                  updatedAt: '',
                }
                return (
                  <div key={panel.id}>
                    <DashboardPanel
                      panel={panelProps}
                      data={panel.queryData}
                      loading={false}
                      error={panel.queryError}
                    />
                  </div>
                )
              })}
            </Responsive>
          )}
        </div>
      </div>

      {/* 保存弹窗 */}
      <Modal
        title="保存大屏"
        open={saveModalVisible}
        onOk={handleSave}
        onCancel={() => { setSaveModalVisible(false); setDashboardName('') }}
        confirmLoading={isSaving}
        okText="保存"
        cancelText="取消"
      >
        <div style={{ padding: '16px 0' }}>
          <Text style={{ display: 'block', marginBottom: 8 }}>请输入大屏名称：</Text>
          <Input
            value={dashboardName}
            onChange={(e) => setDashboardName(e.target.value)}
            placeholder="例如：月度经营数据看板"
            maxLength={64}
            onPressEnter={handleSave}
            autoFocus
          />
          <Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 12 }}>
            名称不超过64个字符，且在系统内唯一
          </Text>
        </div>
      </Modal>
    </div>
  )
}

export default DashboardBuilder
