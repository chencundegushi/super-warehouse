/**
 * Dashboard 面板组件
 * 单个数据面板的完整渲染，包含图表展示、操作栏、加载/错误/超时状态处理。
 * 复用 ChartView 组件渲染图表，复用 DataTable 展示表格数据。
 *
 * @module DashboardPanel
 */

import { useCallback, useState } from 'react'
import {
  Card,
  Spin,
  Alert,
  Button,
  Space,
  Dropdown,
  Input,
  Typography,
  Tooltip,
} from 'antd'
import {
  ReloadOutlined,
  DeleteOutlined,
  EditOutlined,
  BarChartOutlined,
  LineChartOutlined,
  PieChartOutlined,
  TableOutlined,
  CheckOutlined,
  CloseOutlined,
  DownOutlined,
} from '@ant-design/icons'
import type { MenuProps } from 'antd'
import ChartView from './ChartView'
import DataTable from './DataTable'
import type { Panel } from '@/services/dashboardApi'
import type { ChartType, QueryResult } from '@/types'

const { Text } = Typography

// ============================================================
// Props 接口定义
// ============================================================

/**
 * DashboardPanel 组件 Props
 * @param panel - 面板配置信息（标题、SQL、图表类型等）
 * @param data - 查询结果数据
 * @param loading - 是否正在加载数据
 * @param error - 错误信息（SQL执行失败时）
 * @param lastRefreshTime - 最近一次数据刷新时间戳
 * @param editable - 是否展示编辑控件（编辑模式下为true）
 * @param onRefresh - 刷新当前面板数据
 * @param onChartTypeChange - 切换图表类型
 * @param onTitleChange - 编辑面板标题
 * @param onDelete - 删除当前面板
 */
export interface DashboardPanelProps {
  /** 面板配置 */
  panel: Panel
  /** 查询结果数据 */
  data?: QueryResult | null
  /** 是否正在加载 */
  loading?: boolean
  /** 错误信息 */
  error?: string | null
  /** 最近刷新时间戳（ISO 8601） */
  lastRefreshTime?: string | null
  /** 是否展示编辑控件 */
  editable?: boolean
  /** 刷新面板数据回调 */
  onRefresh?: () => void
  /** 图表类型切换回调 */
  onChartTypeChange?: (type: ChartType) => void
  /** 标题修改回调 */
  onTitleChange?: (title: string) => void
  /** 删除面板回调 */
  onDelete?: () => void
}

// ============================================================
// 图表类型配置
// ============================================================

/** 图表类型选项配置 */
const CHART_TYPE_OPTIONS: { key: ChartType; label: string; icon: React.ReactNode }[] = [
  { key: 'table', label: '表格', icon: <TableOutlined /> },
  { key: 'bar', label: '柱状图', icon: <BarChartOutlined /> },
  { key: 'line', label: '折线图', icon: <LineChartOutlined /> },
  { key: 'pie', label: '饼图', icon: <PieChartOutlined /> },
]

/** 超时错误关键词匹配 */
const TIMEOUT_KEYWORDS = ['timeout', '超时', 'timed out', 'cancel']

/**
 * 判断错误是否为超时错误
 * @param error - 错误信息字符串
 * @returns 是否为超时类型错误
 */
function isTimeoutError(error: string): boolean {
  const lowerError = error.toLowerCase()
  return TIMEOUT_KEYWORDS.some((keyword) => lowerError.includes(keyword))
}

/**
 * 格式化刷新时间戳为可读字符串
 * @param isoTime - ISO 8601 时间字符串
 * @returns 格式化后的时间字符串
 */
function formatRefreshTime(isoTime: string): string {
  try {
    const date = new Date(isoTime)
    return date.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return isoTime
  }
}

// ============================================================
// 主组件
// ============================================================

/**
 * Dashboard 面板组件
 * 渲染单个数据面板，包含标题栏、图表区域、状态展示和操作按钮。
 * 支持加载中、错误、超时三种异常状态的展示和重试。
 */
const DashboardPanel: React.FC<DashboardPanelProps> = ({
  panel,
  data,
  loading = false,
  error = null,
  lastRefreshTime = null,
  editable = false,
  onRefresh,
  onChartTypeChange,
  onTitleChange,
  onDelete,
}) => {
  console.log('[DashboardPanel] Rendering panel:', panel.id, 'loading:', loading, 'error:', error)

  // 1.标题编辑状态管理
  const [isEditingTitle, setIsEditingTitle] = useState(false)
  const [editTitleValue, setEditTitleValue] = useState(panel.title)

  /**
   * 确认标题修改
   */
  const handleTitleConfirm = useCallback(() => {
    const trimmed = editTitleValue.trim()
    if (trimmed && trimmed !== panel.title) {
      console.log('[DashboardPanel] Title changed, panelId:', panel.id, 'newTitle:', trimmed)
      onTitleChange?.(trimmed)
    }
    setIsEditingTitle(false)
  }, [editTitleValue, panel.title, panel.id, onTitleChange])

  /**
   * 取消标题编辑
   */
  const handleTitleCancel = useCallback(() => {
    setEditTitleValue(panel.title)
    setIsEditingTitle(false)
  }, [panel.title])

  /**
   * 开始编辑标题
   */
  const handleStartEditTitle = useCallback(() => {
    setEditTitleValue(panel.title)
    setIsEditingTitle(true)
  }, [panel.title])

  // 2.图表类型切换下拉菜单配置
  const chartTypeMenuItems: MenuProps['items'] = CHART_TYPE_OPTIONS.map((opt) => ({
    key: opt.key,
    label: (
      <Space>
        {opt.icon}
        <span>{opt.label}</span>
      </Space>
    ),
  }))

  /**
   * 处理图表类型切换
   */
  const handleChartTypeChange: MenuProps['onClick'] = useCallback(
    ({ key }) => {
      const newType = key as ChartType
      console.log('[DashboardPanel] Chart type changed, panelId:', panel.id, 'newType:', newType)
      onChartTypeChange?.(newType)
    },
    [panel.id, onChartTypeChange]
  )

  // 3.获取当前图表类型的图标
  const currentTypeOption = CHART_TYPE_OPTIONS.find((opt) => opt.key === panel.chartType)

  // ============================================================
  // 渲染标题区域
  // ============================================================

  /**
   * 渲染面板标题（支持编辑模式下的内联编辑）
   */
  const renderTitle = () => {
    if (isEditingTitle) {
      return (
        <Space size={4}>
          <Input
            size="small"
            value={editTitleValue}
            onChange={(e) => setEditTitleValue(e.target.value)}
            onPressEnter={handleTitleConfirm}
            onKeyDown={(e) => e.key === 'Escape' && handleTitleCancel()}
            style={{ width: 160 }}
            autoFocus
            maxLength={64}
          />
          <Button type="text" size="small" icon={<CheckOutlined />} onClick={handleTitleConfirm} />
          <Button type="text" size="small" icon={<CloseOutlined />} onClick={handleTitleCancel} />
        </Space>
      )
    }
    return <span>{panel.title}</span>
  }

  // ============================================================
  // 渲染操作栏
  // ============================================================

  /**
   * 渲染面板右上角操作按钮组
   */
  const renderActions = () => {
    const actions: React.ReactNode[] = []

    // 图表类型切换下拉
    if (editable) {
      actions.push(
        <Dropdown
          key="chart-type"
          menu={{ items: chartTypeMenuItems, onClick: handleChartTypeChange }}
          trigger={['click']}
        >
          <Tooltip title="切换图表类型">
            <Button type="text" size="small">
              {currentTypeOption?.icon} <DownOutlined style={{ fontSize: 10 }} />
            </Button>
          </Tooltip>
        </Dropdown>
      )
    }

    // 刷新按钮
    actions.push(
      <Tooltip key="refresh" title="刷新数据">
        <Button
          type="text"
          size="small"
          icon={<ReloadOutlined spin={loading} />}
          onClick={onRefresh}
          disabled={loading}
        />
      </Tooltip>
    )

    // 编辑标题按钮（仅编辑模式）
    if (editable) {
      actions.push(
        <Tooltip key="edit-title" title="编辑标题">
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={handleStartEditTitle}
          />
        </Tooltip>
      )
    }

    // 删除按钮（仅编辑模式）
    if (editable) {
      actions.push(
        <Tooltip key="delete" title="删除面板">
          <Button
            type="text"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={onDelete}
          />
        </Tooltip>
      )
    }

    return <Space size={0}>{actions}</Space>
  }

  // ============================================================
  // 渲染内容区域
  // ============================================================

  /**
   * 渲染面板主体内容：加载态 / 错误态 / 超时态 / 正常图表
   */
  const renderContent = () => {
    // 加载状态：居中 Spin 动画
    if (loading) {
      return (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          minHeight: 120,
        }}>
          <Spin tip="加载中..." />
        </div>
      )
    }

    // 错误状态：区分超时和普通错误
    if (error) {
      const isTimeout = isTimeoutError(error)
      return (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          minHeight: 120,
          padding: 16,
        }}>
          <Alert
            type={isTimeout ? 'warning' : 'error'}
            showIcon
            message={isTimeout ? '查询超时' : '查询失败'}
            description={isTimeout ? '面板 SQL 执行超过30秒未返回结果' : error}
            action={
              <Button size="small" onClick={onRefresh}>
                重试
              </Button>
            }
            style={{ width: '100%' }}
          />
        </div>
      )
    }

    // 无数据状态
    if (!data) {
      return (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: '100%',
          minHeight: 120,
          color: '#999',
        }}>
          <Text type="secondary">暂无数据</Text>
        </div>
      )
    }

    // 正常渲染：根据图表类型选择组件
    if (panel.chartType === 'table') {
      return <DataTable data={data} pageSize={20} />
    }

    // 使用 ChartView 渲染图表（bar/line/pie）
    return (
      <ChartView
        queryResult={data}
        userSpecifiedType={panel.chartType}
      />
    )
  }

  // ============================================================
  // 渲染底部信息栏
  // ============================================================

  /**
   * 渲染面板底部：最近刷新时间
   */
  const renderFooter = () => {
    if (!lastRefreshTime) return null
    return (
      <div style={{ textAlign: 'right', paddingTop: 4 }}>
        <Text type="secondary" style={{ fontSize: 11 }}>
          最近刷新: {formatRefreshTime(lastRefreshTime)}
        </Text>
      </div>
    )
  }

  // ============================================================
  // 组件主渲染
  // ============================================================

  return (
    <Card
      size="small"
      title={renderTitle()}
      extra={renderActions()}
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
      styles={{
        body: {
          flex: 1,
          overflow: 'auto',
          padding: '8px 12px',
          display: 'flex',
          flexDirection: 'column',
        },
      }}
    >
      <div style={{ flex: 1, minHeight: 0 }}>
        {renderContent()}
      </div>
      {renderFooter()}
    </Card>
  )
}

export default DashboardPanel
