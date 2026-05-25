/**
 * 历史记录页面
 * 实现对话历史的浏览、搜索和恢复功能。
 * 支持按关键词和时间范围搜索，分页加载（每页20条），
 * 点击历史会话可导航到对话页面恢复上下文。
 *
 * @module HistoryPage
 */
import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  List,
  Input,
  DatePicker,
  Pagination,
  Card,
  Typography,
  Tag,
  Space,
  Empty,
  Spin,
} from 'antd'
import {
  HistoryOutlined,
  SearchOutlined,
  MessageOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'
import { listConversations, searchConversations } from '@/services/conversationApi'
import type { ConversationSummary, PaginatedResult } from '@/types'
import type { Dayjs } from 'dayjs'

const { Title, Text } = Typography
const { RangePicker } = DatePicker

/** 每页展示条数 */
const PAGE_SIZE = 20

/**
 * 历史记录页面组件
 * 提供对话历史列表、搜索和分页功能
 * @returns 历史记录页面
 */
function HistoryPage() {
  // 1.状态定义
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [total, setTotal] = useState(0)
  const [currentPage, setCurrentPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)

  /**
   * 加载对话列表（分页模式）
   * 当没有搜索条件时使用分页接口
   */
  const loadConversations = useCallback(async (page: number) => {
    console.log('[HistoryPage] Loading conversations, page:', page)
    setLoading(true)
    try {
      const result: PaginatedResult<ConversationSummary> = await listConversations({
        page,
        pageSize: PAGE_SIZE,
      })
      setConversations(result.items)
      setTotal(result.total)
      console.log('[HistoryPage] Loaded conversations, total:', result.total)
    } catch (error) {
      console.error('[HistoryPage] Failed to load conversations:', error)
      setConversations([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [])

  /**
   * 搜索对话历史
   * 当有关键词或时间范围时使用搜索接口
   */
  const handleSearch = useCallback(async () => {
    const hasKeyword = keyword.trim().length > 0
    const hasDateRange = dateRange && dateRange[0] && dateRange[1]

    // 2.无搜索条件时回退到分页加载
    if (!hasKeyword && !hasDateRange) {
      setCurrentPage(1)
      loadConversations(1)
      return
    }

    console.log('[HistoryPage] Searching conversations, keyword:', keyword)
    setLoading(true)
    try {
      const startTime = hasDateRange ? dateRange[0]!.startOf('day').toISOString() : undefined
      const endTime = hasDateRange ? dateRange[1]!.endOf('day').toISOString() : undefined

      const results = await searchConversations(
        hasKeyword ? keyword.trim() : undefined,
        startTime,
        endTime
      )
      setConversations(results)
      setTotal(results.length)
      setCurrentPage(1)
      console.log('[HistoryPage] Search results count:', results.length)
    } catch (error) {
      console.error('[HistoryPage] Search failed:', error)
      setConversations([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [keyword, dateRange, loadConversations])

  // 3.初始加载
  useEffect(() => {
    loadConversations(1)
  }, [loadConversations])

  /**
   * 处理分页变化
   * @param page - 目标页码
   */
  const handlePageChange = (page: number) => {
    console.log('[HistoryPage] Page changed to:', page)
    setCurrentPage(page)
    loadConversations(page)
  }

  /**
   * 处理点击会话，导航到对话页面恢复上下文
   * @param conversation - 被点击的会话摘要
   */
  const handleConversationClick = (conversation: ConversationSummary) => {
    console.log('[HistoryPage] Navigating to conversation, id:', conversation.id)
    navigate(`/chat?conversationId=${conversation.id}`)
  }

  /**
   * 处理日期范围变化
   * @param dates - 日期范围
   */
  const handleDateRangeChange = (dates: [Dayjs | null, Dayjs | null] | null) => {
    setDateRange(dates)
  }

  /**
   * 格式化时间显示
   * @param isoString - ISO 8601 时间字符串
   * @returns 格式化后的时间文本
   */
  const formatTime = (isoString: string): string => {
    const date = new Date(isoString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMinutes = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    // 4.相对时间展示
    if (diffMinutes < 1) return '刚刚'
    if (diffMinutes < 60) return `${diffMinutes} 分钟前`
    if (diffHours < 24) return `${diffHours} 小时前`
    if (diffDays < 7) return `${diffDays} 天前`

    return date.toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return (
    <div style={{ padding: 24, maxWidth: 960, margin: '0 auto' }}>
      {/* 页面标题 */}
      <Space align="center" style={{ marginBottom: 24 }}>
        <HistoryOutlined style={{ fontSize: 24, color: 'var(--color-primary)' }} />
        <Title level={3} style={{ margin: 0 }}>历史记录</Title>
      </Space>

      {/* 搜索区域 */}
      <Card
        style={{ marginBottom: 16 }}
        bodyStyle={{ padding: '16px 24px' }}
      >
        <Space wrap size="middle" style={{ width: '100%' }}>
          <Input.Search
            placeholder="搜索会话标题或消息内容"
            allowClear
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onSearch={handleSearch}
            style={{ width: 280 }}
            prefix={<SearchOutlined />}
          />
          <RangePicker
            onChange={handleDateRangeChange}
            placeholder={['开始日期', '结束日期']}
            style={{ width: 260 }}
          />
        </Space>
      </Card>

      {/* 会话列表 */}
      <Spin spinning={loading}>
        {conversations.length === 0 && !loading ? (
          <Empty
            description="暂无历史会话"
            style={{ marginTop: 80 }}
          />
        ) : (
          <List
            dataSource={conversations}
            renderItem={(item) => (
              <List.Item
                key={item.id}
                onClick={() => handleConversationClick(item)}
                style={{
                  cursor: 'pointer',
                  padding: '12px 16px',
                  borderRadius: 6,
                  marginBottom: 8,
                  background: 'var(--ant-color-bg-container)',
                  border: '1px solid var(--ant-color-border-secondary)',
                  transition: 'all 0.2s ease',
                }}
              >
                <List.Item.Meta
                  title={
                    <Text strong style={{ fontSize: 15 }}>
                      {item.title || '未命名会话'}
                    </Text>
                  }
                  description={
                    <Space size="large" style={{ marginTop: 4 }}>
                      <Space size={4}>
                        <ClockCircleOutlined style={{ fontSize: 12 }} />
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {formatTime(item.updatedAt)}
                        </Text>
                      </Space>
                      <Tag
                        icon={<MessageOutlined />}
                        color="blue"
                        style={{ fontSize: 12 }}
                      >
                        {item.messageCount} 条消息
                      </Tag>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Spin>

      {/* 分页控件 */}
      {total > PAGE_SIZE && (
        <div style={{ textAlign: 'center', marginTop: 24 }}>
          <Pagination
            current={currentPage}
            total={total}
            pageSize={PAGE_SIZE}
            onChange={handlePageChange}
            showSizeChanger={false}
            showTotal={(t) => `共 ${t} 条会话`}
          />
        </div>
      )}
    </div>
  )
}

export default HistoryPage
