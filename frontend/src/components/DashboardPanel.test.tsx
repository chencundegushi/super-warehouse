/**
 * DashboardPanel 组件单元测试
 * 验证面板渲染、操作栏交互、加载/错误/超时状态展示等核心功能。
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import DashboardPanel from './DashboardPanel'
import type { DashboardPanelProps } from './DashboardPanel'
import type { Panel } from '@/services/dashboardApi'
import type { QueryResult } from '@/types'

// 1.Mock echarts-for-react，避免在测试环境中加载完整 ECharts
vi.mock('echarts-for-react', () => ({
  default: ({ option }: { option: unknown }) => (
    <div data-testid="echarts-container">{JSON.stringify(option)}</div>
  ),
}))

// 2.Mock matchMedia，Ant Design Table 的响应式布局依赖此 API
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// ============================================================
// 测试数据
// ============================================================

const mockPanel: Panel = {
  id: 'panel-1',
  dashboardId: 'dash-1',
  title: '本月充值趋势',
  sql: 'SELECT date, amount FROM revenue WHERE date >= CURDATE() - INTERVAL 30 DAY',
  chartType: 'bar',
  position: { x: 0, y: 0, w: 4, h: 3 },
  sortOrder: 0,
  createdAt: '2024-01-01T00:00:00Z',
  updatedAt: '2024-01-01T00:00:00Z',
}

const mockData: QueryResult = {
  columns: [
    { name: 'date', type: 'DATE', isNumeric: false, isDateTime: true },
    { name: 'amount', type: 'DOUBLE', isNumeric: true, isDateTime: false },
  ],
  rows: [
    ['2024-01-01', 15000],
    ['2024-01-02', 18000],
    ['2024-01-03', 12000],
  ],
  rowCount: 3,
  executionTime: 120,
  truncated: false,
}

const defaultProps: DashboardPanelProps = {
  panel: mockPanel,
  data: mockData,
  loading: false,
  error: null,
  lastRefreshTime: '2024-06-15T10:30:00Z',
  editable: true,
  onRefresh: vi.fn(),
  onChartTypeChange: vi.fn(),
  onTitleChange: vi.fn(),
  onDelete: vi.fn(),
}

// ============================================================
// 正常渲染测试
// ============================================================

describe('DashboardPanel - 正常渲染', () => {
  it('应展示面板标题', () => {
    render(<DashboardPanel {...defaultProps} />)
    expect(screen.getByText('本月充值趋势')).toBeInTheDocument()
  })

  it('应渲染图表内容（bar类型）', () => {
    render(<DashboardPanel {...defaultProps} />)
    expect(screen.getByTestId('echarts-container')).toBeInTheDocument()
  })

  it('table类型应渲染DataTable而非ECharts', () => {
    const tablePanel = { ...mockPanel, chartType: 'table' as const }
    render(<DashboardPanel {...defaultProps} panel={tablePanel} />)
    // table 类型不应渲染 ECharts 图表
    expect(screen.queryByTestId('echarts-container')).not.toBeInTheDocument()
  })

  it('应展示最近刷新时间', () => {
    render(<DashboardPanel {...defaultProps} />)
    expect(screen.getByText(/最近刷新/)).toBeInTheDocument()
  })

  it('无刷新时间时不展示底部信息', () => {
    render(<DashboardPanel {...defaultProps} lastRefreshTime={null} />)
    expect(screen.queryByText(/最近刷新/)).not.toBeInTheDocument()
  })
})

// ============================================================
// 加载状态测试
// ============================================================

describe('DashboardPanel - 加载状态', () => {
  it('loading为true时应展示Spin加载动画', () => {
    const { container } = render(<DashboardPanel {...defaultProps} loading={true} data={null} />)
    expect(container.querySelector('.ant-spin')).toBeInTheDocument()
  })

  it('loading时刷新按钮应禁用', () => {
    render(<DashboardPanel {...defaultProps} loading={true} />)
    const refreshBtn = screen.getByRole('button', { name: /reload/ })
    expect(refreshBtn).toBeDisabled()
  })
})

// ============================================================
// 错误状态测试
// ============================================================

describe('DashboardPanel - 错误状态', () => {
  it('普通错误应展示错误信息和重试按钮', () => {
    const { container } = render(<DashboardPanel {...defaultProps} error="Table not found: revenue" data={null} />)
    expect(screen.getByText('查询失败')).toBeInTheDocument()
    expect(screen.getByText('Table not found: revenue')).toBeInTheDocument()
    // Alert action 中的重试按钮
    const retryBtn = container.querySelector('.ant-alert-action button')
    expect(retryBtn).toBeInTheDocument()
  })

  it('超时错误应展示超时提示', () => {
    const { container } = render(<DashboardPanel {...defaultProps} error="Query execution timeout after 30s" data={null} />)
    expect(screen.getByText('查询超时')).toBeInTheDocument()
    const retryBtn = container.querySelector('.ant-alert-action button')
    expect(retryBtn).toBeInTheDocument()
  })

  it('点击重试按钮应调用onRefresh', () => {
    const onRefresh = vi.fn()
    const { container } = render(<DashboardPanel {...defaultProps} error="Some error" data={null} onRefresh={onRefresh} />)
    const retryBtn = container.querySelector('.ant-alert-action button') as HTMLElement
    fireEvent.click(retryBtn)
    expect(onRefresh).toHaveBeenCalledTimes(1)
  })
})

// ============================================================
// 操作栏测试
// ============================================================

describe('DashboardPanel - 操作栏', () => {
  it('编辑模式下应展示所有操作按钮', () => {
    render(<DashboardPanel {...defaultProps} editable={true} />)
    expect(screen.getByRole('button', { name: /reload/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /edit/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /delete/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /bar-chart down/ })).toBeInTheDocument()
  })

  it('非编辑模式下仅展示刷新按钮', () => {
    render(<DashboardPanel {...defaultProps} editable={false} />)
    expect(screen.getByRole('button', { name: /reload/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /edit/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /delete/ })).not.toBeInTheDocument()
  })

  it('点击刷新按钮应调用onRefresh', () => {
    const onRefresh = vi.fn()
    render(<DashboardPanel {...defaultProps} onRefresh={onRefresh} />)
    fireEvent.click(screen.getByRole('button', { name: /reload/ }))
    expect(onRefresh).toHaveBeenCalledTimes(1)
  })

  it('点击删除按钮应调用onDelete', () => {
    const onDelete = vi.fn()
    render(<DashboardPanel {...defaultProps} onDelete={onDelete} />)
    fireEvent.click(screen.getByRole('button', { name: /delete/ }))
    expect(onDelete).toHaveBeenCalledTimes(1)
  })
})

// ============================================================
// 标题编辑测试
// ============================================================

describe('DashboardPanel - 标题编辑', () => {
  it('点击编辑标题按钮应进入编辑模式', () => {
    render(<DashboardPanel {...defaultProps} />)
    fireEvent.click(screen.getByRole('button', { name: /edit/ }))
    // 编辑模式下应出现输入框
    expect(screen.getByRole('textbox')).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveValue('本月充值趋势')
  })

  it('修改标题后按Enter应调用onTitleChange', () => {
    const onTitleChange = vi.fn()
    render(<DashboardPanel {...defaultProps} onTitleChange={onTitleChange} />)
    fireEvent.click(screen.getByRole('button', { name: /edit/ }))
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '新标题' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onTitleChange).toHaveBeenCalledWith('新标题')
  })

  it('标题未修改时按Enter不应调用onTitleChange', () => {
    const onTitleChange = vi.fn()
    render(<DashboardPanel {...defaultProps} onTitleChange={onTitleChange} />)
    fireEvent.click(screen.getByRole('button', { name: /edit/ }))
    const input = screen.getByRole('textbox')
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onTitleChange).not.toHaveBeenCalled()
  })

  it('按Escape应取消编辑', () => {
    render(<DashboardPanel {...defaultProps} />)
    fireEvent.click(screen.getByRole('button', { name: /edit/ }))
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '新标题' } })
    fireEvent.keyDown(input, { key: 'Escape' })
    // 应恢复原标题展示
    expect(screen.getByText('本月充值趋势')).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })
})
