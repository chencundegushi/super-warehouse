/**
 * 对话页面
 * 实现用户与数仓智能体的对话交互，包括消息列表、输入框、SSE流式接收、
 * 加载状态展示和长时间等待提示。
 * 支持：自动执行SQL（可切换确认模式）、图表绑定到消息、可折叠SQL展示。
 *
 * @module ChatPage
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Input, Button, Spin, Typography, Space, Switch, Tooltip } from 'antd'
import { SendOutlined, LoadingOutlined, CloseCircleOutlined, SafetyOutlined } from '@ant-design/icons'
import type { Message, StreamEvent, StreamEventType, QueryResult, ChartRecommendation } from '@/types'
import { sendMessage, confirmSQL, cancelQuery } from '@/services/chatApi'
import { getMessages } from '@/services/conversationApi'
import type { SSEConnection } from '@/services/sse'
import SQLPreview from '@/components/SQLPreview'
import ChartView from '@/components/ChartView'
import styles from './index.module.css'

const { Text, Paragraph } = Typography
const { TextArea } = Input

/** 加载阶段文案映射 */
const LOADING_PHASE_TEXT: Record<string, string> = {
  thinking: '正在思考...',
  sql_preview: '正在生成SQL',
  executing: '正在执行查询',
  result: '正在处理结果',
}

/** 长时间等待阈值（毫秒） */
const LONG_WAIT_THRESHOLD = 10000

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

/** 对话消息扩展类型，包含附加数据 */
interface ChatMessage extends Omit<Message, 'id' | 'conversationId' | 'createdAt'> {
  id: string
  isStreaming?: boolean
  /** 该消息关联的SQL（可折叠展示） */
  attachedSQL?: string
  /** 该消息关联的查询结果（用于图表） */
  attachedResult?: QueryResult
  /** 该消息关联的图表推荐 */
  attachedChart?: ChartRecommendation
  /** 该消息关联的工具调用记录 */
  toolCalls?: Array<{ tool_name: string; display_name: string; args: Record<string, unknown> }>
}

/**
 * 对话页面主组件
 */
function ChatPage() {
  const [searchParams] = useSearchParams()
  const conversationId = searchParams.get('conversationId')

  // 状态
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [loadingPhase, setLoadingPhase] = useState<string>('')
  const [showLongWait, setShowLongWait] = useState(false)
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  // SQL确认模式：false=自动执行，true=需要确认
  const [requireConfirm, setRequireConfirm] = useState(false)
  // 待确认的SQL（仅确认模式下使用）
  const [pendingSQL, setPendingSQL] = useState<{ sql: string; explanation: string; source: string } | null>(null)
  const [isConfirming, setIsConfirming] = useState(false)

  // Refs
  const sessionIdRef = useRef<string>(generateSessionId())
  const sseConnectionRef = useRef<SSEConnection | null>(null)
  const longWaitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const messageListRef = useRef<HTMLDivElement>(null)
  const streamingMessageIdRef = useRef<string | null>(null)
  // 临时存储当前流中的SQL和结果，用于绑定到消息
  const currentSQLRef = useRef<string>('')
  const currentResultRef = useRef<QueryResult | null>(null)
  const currentChartRef = useRef<ChartRecommendation | null>(null)
  // 是否需要确认的ref（在回调中使用）
  const requireConfirmRef = useRef(requireConfirm)

  // 同步 requireConfirm 到 ref
  useEffect(() => {
    requireConfirmRef.current = requireConfirm
  }, [requireConfirm])

  // 加载历史消息
  useEffect(() => {
    if (!conversationId) return
    const load = async () => {
      console.log('[ChatPage] Loading history messages for conversation:', conversationId)
      setIsLoadingHistory(true)
      try {
        const historyMessages = await getMessages(conversationId)
        const chatMessages: ChatMessage[] = historyMessages.map((msg: Message) => ({
          id: msg.id, role: msg.role, content: msg.content,
          sql: msg.sql, queryResult: msg.queryResult, isStreaming: false,
        }))
        setMessages(chatMessages)
      } catch (error) {
        console.error('[ChatPage] Failed to load history messages:', error)
      } finally {
        setIsLoadingHistory(false)
      }
    }
    load()
  }, [conversationId])

  const scrollToBottom = useCallback(() => {
    if (messageListRef.current) {
      messageListRef.current.scrollTop = messageListRef.current.scrollHeight
    }
  }, [])

  useEffect(() => { scrollToBottom() }, [messages, scrollToBottom])

  const clearLongWaitTimer = useCallback(() => {
    if (longWaitTimerRef.current) { clearTimeout(longWaitTimerRef.current); longWaitTimerRef.current = null }
    setShowLongWait(false)
  }, [])

  const startLongWaitTimer = useCallback(() => {
    clearLongWaitTimer()
    longWaitTimerRef.current = setTimeout(() => setShowLongWait(true), LONG_WAIT_THRESHOLD)
  }, [clearLongWaitTimer])

  const handleCancelQuery = useCallback(async () => {
    console.log('[ChatPage] User cancelling query')
    try {
      if (sseConnectionRef.current) { sseConnectionRef.current.abort(); sseConnectionRef.current = null }
      await cancelQuery(sessionIdRef.current)
    } catch (error) { console.error('[ChatPage] Cancel query error:', error) }
    finally {
      setIsLoading(false); setLoadingPhase(''); clearLongWaitTimer()
      const msgId = streamingMessageIdRef.current
      if (msgId) {
        setMessages(prev => prev.map(msg =>
          msg.id === msgId ? { ...msg, isStreaming: false, content: msg.content || '查询已取消' } : msg
        ))
      }
      streamingMessageIdRef.current = null
    }
  }, [clearLongWaitTimer])

  /** 更新当前流式消息内容 */
  const updateStreamingMessage = useCallback((content: string) => {
    const msgId = streamingMessageIdRef.current
    if (!msgId) return
    setMessages(prev => prev.map(msg => msg.id === msgId ? { ...msg, content } : msg))
  }, [])

  /** 处理SSE流完成 */
  const handleStreamComplete = useCallback(() => {
    console.log('[ChatPage] Stream completed, msgId:', streamingMessageIdRef.current, 'sql:', currentSQLRef.current?.substring(0, 30), 'hasResult:', !!currentResultRef.current, 'hasChart:', !!currentChartRef.current)
    setIsLoading(false); setLoadingPhase(''); clearLongWaitTimer()
    // 先将 ref 值捕获到局部变量，避免 setMessages 更新器异步执行时 ref 已被清空
    const msgId = streamingMessageIdRef.current
    const sql = currentSQLRef.current
    const result = currentResultRef.current
    const chart = currentChartRef.current
    if (msgId) {
      const finalData: Partial<ChatMessage> = { isStreaming: false }
      if (sql) finalData.attachedSQL = sql
      if (result) finalData.attachedResult = result
      if (chart) finalData.attachedChart = chart
      setMessages(prev => prev.map(msg =>
        msg.id === msgId ? { ...msg, ...finalData } : msg
      ))
    }
    streamingMessageIdRef.current = null
    currentSQLRef.current = ''; currentResultRef.current = null; currentChartRef.current = null
    sseConnectionRef.current = null
    // 延迟滚动确保附加内容渲染后可见
    setTimeout(() => scrollToBottom(), 200)
  }, [clearLongWaitTimer, scrollToBottom])

  /** 处理SSE流错误 */
  const handleStreamError = useCallback((error: Error) => {
    console.error('[ChatPage] Stream error:', error.message)
    setIsLoading(false); setLoadingPhase(''); clearLongWaitTimer()
    const msgId = streamingMessageIdRef.current
    if (msgId) {
      setMessages(prev => prev.map(msg =>
        msg.id === msgId
          ? { ...msg, content: `❌ 连接错误: ${error.message}`, isStreaming: false } : msg
      ))
    }
    streamingMessageIdRef.current = null
    currentSQLRef.current = ''; currentResultRef.current = null; currentChartRef.current = null
    sseConnectionRef.current = null
  }, [clearLongWaitTimer])

  /** 处理SSE流事件 - 使用ref避免闭包问题 */
  const handleStreamEventRef = useRef<(event: StreamEvent) => void>(() => {})
  const handleStreamErrorRef = useRef<(error: Error) => void>(() => {})

  const handleStreamEvent = useCallback((event: StreamEvent) => {
    console.log('[ChatPage] Stream event received, type:', event.type)
    const eventType = event.type as StreamEventType

    if (LOADING_PHASE_TEXT[eventType]) setLoadingPhase(LOADING_PHASE_TEXT[eventType])

    switch (eventType) {
      case 'thinking': {
        const thinkingData = event.data as { message?: string } | string
        const thinkingMsg = typeof thinkingData === 'string' ? thinkingData : (thinkingData?.message || '')
        updateStreamingMessage(thinkingMsg)
        break
      }
      case 'tool_call': {
        const tcData = event.data as { tool_name?: string; display_name?: string; args?: Record<string, unknown> }
        if (tcData?.tool_name) {
          const msgId = streamingMessageIdRef.current
          if (msgId) {
            setMessages(prev => prev.map(msg => {
              if (msg.id !== msgId) return msg
              const existing = msg.toolCalls || []
              return { ...msg, toolCalls: [...existing, { tool_name: tcData.tool_name!, display_name: tcData.display_name || tcData.tool_name!, args: tcData.args || {} }] }
            }))
          }
        }
        break
      }
      case 'sql_preview': {
        const data = event.data as { sql?: string; explanation?: string; source?: string }
        const sql = data?.sql || String(event.data)
        currentSQLRef.current = sql
        if (requireConfirmRef.current) {
          // 确认模式：暂停等待用户确认
          setPendingSQL({ sql, explanation: data?.explanation || '', source: data?.source || 'sql_generator' })
          updateStreamingMessage('')
          setIsLoading(false); setLoadingPhase(''); clearLongWaitTimer()
        }
        // 自动执行模式：不做任何事，后端会继续在同一个流中发送 executing/result/chart_recommendation
        break
      }
      case 'executing':
        setLoadingPhase('正在执行查询')
        break
      case 'result': {
        const resultData = event.data as { columns?: Array<{ name: string; type?: string; is_numeric?: boolean; is_datetime?: boolean }>; rows?: unknown[][]; row_count?: number; execution_time?: number; message?: string } | string
        if (typeof resultData === 'string') {
          updateStreamingMessage(resultData || '查询完成')
        } else if (resultData?.message) {
          updateStreamingMessage(resultData.message)
        } else if (resultData?.columns && resultData?.rows) {
          const qr: QueryResult = {
            columns: resultData.columns.map(c => ({ name: c.name, type: c.type || 'VARCHAR', isNumeric: c.is_numeric ?? false, isDateTime: c.is_datetime ?? false })),
            rows: resultData.rows, rowCount: resultData.row_count ?? resultData.rows.length,
            executionTime: resultData.execution_time ?? 0, truncated: false,
          }
          currentResultRef.current = qr
          const cols = resultData.columns.map(c => c.name).join(' | ')
          const rowCount = resultData.row_count ?? resultData.rows.length
          const execTime = Math.round(resultData.execution_time ?? 0)
          let text = `查询完成，返回 ${rowCount} 行数据（耗时 ${execTime}ms）\n\n| ${cols} |\n| ${resultData.columns.map(() => '---').join(' | ')} |\n`
          for (const row of resultData.rows.slice(0, 30)) { text += `| ${(row as unknown[]).join(' | ')} |\n` }
          if (resultData.rows.length > 30) text += `\n... 共 ${rowCount} 行，仅展示前30行`
          // 直接更新消息，同时附加SQL和结果
          const msgId = streamingMessageIdRef.current
          if (msgId) {
            setMessages(prev => prev.map(msg =>
              msg.id === msgId ? { ...msg, content: text, attachedSQL: currentSQLRef.current || undefined, attachedResult: qr } : msg
            ))
          }
        } else { updateStreamingMessage('查询完成') }
        break
      }
      case 'chart_recommendation': {
        const recData = event.data as { recommended?: string; reason?: string; alternatives?: string[] }
        if (recData?.recommended) {
          const chart: ChartRecommendation = {
            recommended: recData.recommended as ChartRecommendation['recommended'],
            reason: recData.reason || '',
            alternatives: (recData.alternatives || []) as ChartRecommendation['alternatives'],
          }
          currentChartRef.current = chart
          // 直接附加图表到消息
          const msgId = streamingMessageIdRef.current
          if (msgId) {
            setMessages(prev => prev.map(msg =>
              msg.id === msgId ? { ...msg, attachedChart: chart } : msg
            ))
          }
        }
        break
      }
      case 'error':
        updateStreamingMessage(`❌ ${(event.data as { message?: string })?.message || '发生错误'}`)
        break
      case 'clarification':
        updateStreamingMessage(String((event.data as { message?: string })?.message || event.data))
        break
      default:
        if (event.data) updateStreamingMessage(String(event.data))
    }
  }, [updateStreamingMessage, clearLongWaitTimer])

  // 保持ref同步
  useEffect(() => { handleStreamEventRef.current = handleStreamEvent }, [handleStreamEvent])
  useEffect(() => { handleStreamErrorRef.current = handleStreamError }, [handleStreamError])

  /** 确认SQL执行（确认模式下） */
  const handleConfirmSQL = useCallback(() => {
    if (!pendingSQL) return
    console.log('[ChatPage] User confirmed SQL')
    setIsConfirming(true); setPendingSQL(null)
    setIsLoading(true); setLoadingPhase('正在执行查询'); startLongWaitTimer()
    const resultMsgId = `agent-result-${Date.now()}`
    setMessages(prev => [...prev, { id: resultMsgId, role: 'agent', content: '', isStreaming: true }])
    streamingMessageIdRef.current = resultMsgId
    const connection = confirmSQL(sessionIdRef.current, true, {
      onMessage: handleStreamEvent,
      onComplete: () => { setIsConfirming(false); handleStreamComplete() },
      onError: (error) => { setIsConfirming(false); handleStreamError(error) },
    })
    sseConnectionRef.current = connection
  }, [pendingSQL, startLongWaitTimer, handleStreamEvent, handleStreamComplete, handleStreamError])

  /** 拒绝SQL */
  const handleRejectSQL = useCallback((feedback: string) => {
    console.log('[ChatPage] User rejected SQL')
    setPendingSQL(null); setIsLoading(true); setLoadingPhase('正在重新生成SQL...'); startLongWaitTimer()
    const newMsgId = `agent-retry-${Date.now()}`
    setMessages(prev => [...prev, { id: newMsgId, role: 'agent', content: '', isStreaming: true }])
    streamingMessageIdRef.current = newMsgId
    const connection = confirmSQL(sessionIdRef.current, false, {
      onMessage: handleStreamEvent, onComplete: handleStreamComplete, onError: handleStreamError,
    }, feedback)
    sseConnectionRef.current = connection
  }, [startLongWaitTimer, handleStreamEvent, handleStreamComplete, handleStreamError])

  /** 发送消息 */
  const handleSend = useCallback(() => {
    const text = inputValue.trim()
    if (!text || isLoading) return
    console.log('[ChatPage] Sending message:', text.substring(0, 50))
    const userMessage: ChatMessage = { id: `user-${Date.now()}`, role: 'user', content: text }
    const agentMessageId = `agent-${Date.now()}`
    const agentMessage: ChatMessage = { id: agentMessageId, role: 'agent', content: '', isStreaming: true }
    setMessages(prev => [...prev, userMessage, agentMessage])
    setInputValue(''); setIsLoading(true); setLoadingPhase('正在思考...')
    currentSQLRef.current = ''; currentResultRef.current = null; currentChartRef.current = null
    streamingMessageIdRef.current = agentMessageId
    startLongWaitTimer()
    const connection = sendMessage(
      { sessionId: sessionIdRef.current, message: text, conversationId: conversationId || undefined, autoExecute: !requireConfirmRef.current },
      { onMessage: handleStreamEvent, onComplete: handleStreamComplete, onError: handleStreamError }
    )
    sseConnectionRef.current = connection
  }, [inputValue, isLoading, conversationId, startLongWaitTimer, handleStreamEvent, handleStreamComplete, handleStreamError])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  useEffect(() => {
    return () => {
      if (sseConnectionRef.current) sseConnectionRef.current.abort()
      if (longWaitTimerRef.current) clearTimeout(longWaitTimerRef.current)
    }
  }, [])

  return (
    <div className={styles.chatContainer}>
      {/* 消息列表区域 */}
      <div className={styles.messageList} ref={messageListRef}>
        {isLoadingHistory && (
          <div className={styles.emptyState}>
            <Space><Spin indicator={<LoadingOutlined spin />} size="small" /><Text type="secondary">正在加载历史对话...</Text></Space>
          </div>
        )}
        {messages.length === 0 && !isLoadingHistory && (
          <div className={styles.emptyState}>
            <Text type="secondary">输入问题开始对话，例如："查询昨天的销售总额"</Text>
          </div>
        )}
        {messages.map((msg) => (
          <div key={msg.id}>
            <div className={`${styles.messageItem} ${msg.role === 'user' ? styles.userMessage : styles.agentMessage}`}>
              <div className={styles.messageBubble}>
                {/* 消息文本 */}
                {(msg.content || msg.isStreaming) && (
                  <Paragraph className={styles.messageContent} style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                    {msg.content || ''}
                  </Paragraph>
                )}
                {msg.isStreaming && !msg.content && (
                  <Spin indicator={<LoadingOutlined spin />} size="small" />
                )}
              </div>
            </div>
            {/* 该消息关联的工具调用记录 */}
            {msg.toolCalls && msg.toolCalls.length > 0 && (
              <div className={styles.messageItem + ' ' + styles.agentMessage}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, maxWidth: '80%' }}>
                  {msg.toolCalls.map((tc, idx) => (
                    <span key={idx} style={{
                      display: 'inline-flex', alignItems: 'center', gap: 4,
                      padding: '3px 10px', borderRadius: 12,
                      background: 'rgba(22, 119, 255, 0.1)', border: '1px solid rgba(22, 119, 255, 0.3)',
                      fontSize: 12, color: '#4096ff',
                    }}>
                      ⚡ {tc.display_name}
                      {tc.args && Object.keys(tc.args).length > 0 && (
                        <span style={{ color: '#888', marginLeft: 4 }}>
                          ({Object.entries(tc.args).map(([k, v]) => `${k}=${v}`).join(', ')})
                        </span>
                      )}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {/* 该消息关联的SQL（可折叠） */}
            {msg.attachedSQL && !msg.isStreaming && (
              <div className={styles.messageItem + ' ' + styles.agentMessage}>
                <details style={{ background: 'var(--color-bg-elevated)', borderRadius: 6, padding: '6px 10px', border: '1px solid var(--color-border-secondary)', maxWidth: '80%', fontSize: 12 }}>
                  <summary style={{ cursor: 'pointer', color: '#999', userSelect: 'none' }}>🔍 执行的SQL（点击展开）</summary>
                  <pre style={{ margin: '8px 0 0', padding: 8, background: '#1a1a1a', borderRadius: 4, overflow: 'auto', fontSize: 12, color: '#e0e0e0' }}>{msg.attachedSQL}</pre>
                </details>
              </div>
            )}
            {/* 该消息关联的图表（可折叠） */}
            {msg.attachedResult && !msg.isStreaming && (
              <div className={styles.messageItem + ' ' + styles.agentMessage}>
                <div style={{ maxWidth: '90%', width: '100%' }}>
                  <details open style={{ background: 'var(--color-bg-elevated)', borderRadius: 8, padding: '8px 12px', border: '1px solid var(--color-border-secondary)' }}>
                    <summary style={{ cursor: 'pointer', padding: '4px 0', fontSize: 13, color: '#ccc', userSelect: 'none' }}>📊 数据可视化（点击收起/展开）</summary>
                    <div style={{ marginTop: 8 }}>
                      <ChartView queryResult={msg.attachedResult} recommendation={msg.attachedChart} userSpecifiedType={msg.attachedChart?.recommended} />
                    </div>
                  </details>
                </div>
              </div>
            )}
          </div>
        ))}

        {/* SQL确认组件（仅确认模式） */}
        {pendingSQL && (
          <div className={styles.messageItem + ' ' + styles.agentMessage}>
            <div style={{ maxWidth: '80%', width: '100%' }}>
              <SQLPreview sql={pendingSQL.sql} explanation={pendingSQL.explanation} source={pendingSQL.source} onConfirm={handleConfirmSQL} onReject={handleRejectSQL} loading={isConfirming} />
            </div>
          </div>
        )}

        {/* 加载状态 */}
        {isLoading && loadingPhase && (
          <div className={styles.loadingStatus}>
            <Space><Spin indicator={<LoadingOutlined spin />} size="small" /><Text type="secondary">{loadingPhase}</Text></Space>
            {showLongWait && (
              <div className={styles.longWaitHint}>
                <Text type="warning">仍在处理中...</Text>
                <Button type="link" danger icon={<CloseCircleOutlined />} onClick={handleCancelQuery} size="small">取消查询</Button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 输入区域 */}
      <div className={styles.inputArea}>
        <div className={styles.inputWrapper}>
          <TextArea value={inputValue} onChange={(e) => setInputValue(e.target.value)} onKeyDown={handleKeyDown}
            placeholder="输入问题，按 Enter 发送，Shift+Enter 换行"
            autoSize={{ minRows: 1, maxRows: 4 }} disabled={isLoading} className={styles.textInput} />
          <Tooltip title={requireConfirm ? 'SQL需确认后执行' : 'SQL自动执行'}>
            <Switch size="small" checked={requireConfirm} onChange={setRequireConfirm}
              checkedChildren={<SafetyOutlined />} unCheckedChildren={<SafetyOutlined />}
              style={{ marginRight: 4 }} />
          </Tooltip>
          <Button type="primary" icon={<SendOutlined />} onClick={handleSend}
            disabled={!inputValue.trim() || isLoading} className={styles.sendButton} />
        </div>
      </div>
    </div>
  )
}

export default ChatPage
