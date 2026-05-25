/**
 * ChartView 组件单元测试
 * 验证图表类型切换、兼容性检查、空数据处理、推荐默认选中等核心功能。
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ChartView, { validateCompatibility } from './ChartView'
import type { ChartViewProps } from './ChartView'
import type { QueryResult, ChartRecommendation, ColumnInfo } from '../types'

// 1.Mock echarts-for-react，避免在测试环境中加载完整 ECharts
vi.mock('echarts-for-react', () => ({
  default: ({ option }: { option: unknown }) => (
    <div data-testid="echarts-container">{JSON.stringify(option)}</div>
  ),
}))

// ============================================================
// 测试数据
// ============================================================

const mockColumns: ColumnInfo[] = [
  { name: 'category', type: 'VARCHAR', isNumeric: false, isDateTime: false },
  { name: 'amount', type: 'DOUBLE', isNumeric: true, isDateTime: false },
  { name: 'count', type: 'INT', isNumeric: true, isDateTime: false },
]

const mockQueryResult: QueryResult = {
  columns: mockColumns,
  rows: [
    ['电子产品', 15000, 120],
    ['服装', 8000, 85],
    ['食品', 5000, 200],
  ],
  rowCount: 3,
  executionTime: 150,
  truncated: false,
}

const emptyQueryResult: QueryResult = {
  columns: mockColumns,
  rows: [],
  rowCount: 0,
  executionTime: 50,
  truncated: false,
}

const mockRecommendation: ChartRecommendation = {
  recommended: 'line',
  reason: '数据包含时间序列维度',
  alternatives: ['bar', 'pie'],
}

const defaultProps: ChartViewProps = {
  queryResult: mockQueryResult,
}

// ============================================================
// 组件渲染测试
// ============================================================

describe('ChartView', () => {
  it('应正常渲染图表区域', () => {
    render(<ChartView {...defaultProps} />)
    expect(screen.getByTestId('echarts-container')).toBeInTheDocument()
  })

  it('空数据时应展示空状态提示', () => {
    render(<ChartView queryResult={emptyQueryResult} />)
    expect(screen.getByText('当前查询无返回数据')).toBeInTheDocument()
    expect(screen.queryByTestId('echarts-container')).not.toBeInTheDocument()
  })

  it('默认应选中柱状图类型', () => {
    render(<ChartView {...defaultProps} />)
    const barRadio = screen.getByRole('radio', { name: /柱状图/ })
    expect(barRadio).toBeChecked()
  })

  it('Agent 推荐类型应作为默认选中', () => {
    render(<ChartView {...defaultProps} recommendation={mockRecommendation} />)
    const lineRadio = screen.getByRole('radio', { name: /折线图/ })
    expect(lineRadio).toBeChecked()
  })

  it('用户指定类型应优先于 Agent 推荐', () => {
    render(
      <ChartView
        {...defaultProps}
        recommendation={mockRecommendation}
        userSpecifiedType="pie"
      />
    )
    const pieRadio = screen.getByRole('radio', { name: /饼图/ })
    expect(pieRadio).toBeChecked()
  })

  it('切换图表类型应更新选中状态', () => {
    render(<ChartView {...defaultProps} />)
    const lineRadio = screen.getByRole('radio', { name: /折线图/ })
    fireEvent.click(lineRadio)
    expect(lineRadio).toBeChecked()
  })

  it('推荐类型选中时应展示推荐原因', () => {
    render(<ChartView {...defaultProps} recommendation={mockRecommendation} />)
    expect(screen.getByText(/数据包含时间序列维度/)).toBeInTheDocument()
  })
})

// ============================================================
// validateCompatibility 函数测试
// ============================================================

describe('validateCompatibility', () => {
  const numericOnlyCols: ColumnInfo[] = [
    { name: 'a', type: 'INT', isNumeric: true, isDateTime: false },
    { name: 'b', type: 'DOUBLE', isNumeric: true, isDateTime: false },
  ]

  const categoryOnlyCols: ColumnInfo[] = [
    { name: 'name', type: 'VARCHAR', isNumeric: false, isDateTime: false },
    { name: 'city', type: 'VARCHAR', isNumeric: false, isDateTime: false },
  ]

  const mixedCols: ColumnInfo[] = [
    { name: 'name', type: 'VARCHAR', isNumeric: false, isDateTime: false },
    { name: 'value', type: 'INT', isNumeric: true, isDateTime: false },
  ]

  it('柱状图 - 有分类和数值列时应兼容', () => {
    const result = validateCompatibility(mixedCols, 'bar')
    expect(result.compatible).toBe(true)
    expect(result.warnings).toHaveLength(0)
  })

  it('柱状图 - 仅数值列时应不兼容', () => {
    const result = validateCompatibility(numericOnlyCols, 'bar')
    expect(result.compatible).toBe(false)
    expect(result.warnings.length).toBeGreaterThan(0)
  })

  it('饼图 - 仅分类列时应不兼容（缺少数值）', () => {
    const result = validateCompatibility(categoryOnlyCols, 'pie')
    expect(result.compatible).toBe(false)
    expect(result.warnings.some((w) => w.includes('数值'))).toBe(true)
  })

  it('折线图 - 有分类和数值列时应兼容', () => {
    const result = validateCompatibility(mixedCols, 'line')
    expect(result.compatible).toBe(true)
  })

  it('折线图 - 仅数值列时应不兼容', () => {
    const result = validateCompatibility(numericOnlyCols, 'line')
    expect(result.compatible).toBe(false)
  })

  it('table 类型不做兼容性检查', () => {
    const result = validateCompatibility(numericOnlyCols, 'table')
    expect(result.compatible).toBe(true)
  })

  it('数据不兼容时应展示适配建议', () => {
    const numericOnlyResult: QueryResult = {
      columns: numericOnlyCols,
      rows: [[1, 2], [3, 4]],
      rowCount: 2,
      executionTime: 50,
      truncated: false,
    }
    render(<ChartView queryResult={numericOnlyResult} userSpecifiedType="pie" />)
    expect(screen.getByText('数据适配建议')).toBeInTheDocument()
  })
})
