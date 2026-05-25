/**
 * DataTable 组件单元测试
 * 验证数据表格展示、分页浏览、空数据状态提示等核心功能。
 */

import { describe, it, expect, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import DataTable from './DataTable'
import type { QueryResult } from '../types'

// 1.Mock window.matchMedia（Ant Design Table 内部使用响应式断点）
beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  })
})

/** 构造测试用查询结果数据 */
function createMockQueryResult(rowCount: number): QueryResult {
  return {
    columns: [
      { name: 'id', type: 'INT', isNumeric: true, isDateTime: false },
      { name: 'name', type: 'VARCHAR', isNumeric: false, isDateTime: false },
      { name: 'created_at', type: 'DATETIME', isNumeric: false, isDateTime: true },
    ],
    rows: Array.from({ length: rowCount }, (_, i) => [
      i + 1,
      `item_${i + 1}`,
      '2024-01-01 00:00:00',
    ]),
    rowCount,
    executionTime: 120,
    truncated: false,
  }
}

describe('DataTable', () => {
  it('data 为 null 时应展示空数据状态提示', () => {
    render(<DataTable data={null} />)
    expect(screen.getByText('当前查询无返回数据')).toBeInTheDocument()
  })

  it('行数为 0 时应展示空数据状态提示', () => {
    const emptyResult: QueryResult = {
      columns: [
        { name: 'id', type: 'INT', isNumeric: true, isDateTime: false },
      ],
      rows: [],
      rowCount: 0,
      executionTime: 50,
      truncated: false,
    }
    render(<DataTable data={emptyResult} />)
    expect(screen.getByText('当前查询无返回数据')).toBeInTheDocument()
  })

  it('应正确展示列标题', () => {
    const data = createMockQueryResult(3)
    render(<DataTable data={data} />)
    // 2.Ant Design Table 固定表头模式下列标题可能出现多次
    expect(screen.getAllByText('id').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('name').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('created_at').length).toBeGreaterThanOrEqual(1)
  })

  it('应正确展示行数据', () => {
    const data = createMockQueryResult(2)
    render(<DataTable data={data} />)
    expect(screen.getByText('item_1')).toBeInTheDocument()
    expect(screen.getByText('item_2')).toBeInTheDocument()
  })

  it('应展示执行耗时和行数信息', () => {
    const data = createMockQueryResult(5)
    render(<DataTable data={data} />)
    expect(screen.getByText(/执行耗时: 120ms/)).toBeInTheDocument()
    expect(screen.getByText(/共 5 行/)).toBeInTheDocument()
  })

  it('数据截断时应展示截断提示', () => {
    const data: QueryResult = {
      ...createMockQueryResult(1000),
      truncated: true,
      rowCount: 1000,
    }
    render(<DataTable data={data} />)
    expect(screen.getByText(/查询结果已截断/)).toBeInTheDocument()
  })

  it('未截断时不应展示截断提示', () => {
    const data = createMockQueryResult(10)
    render(<DataTable data={data} />)
    expect(screen.queryByText(/查询结果已截断/)).not.toBeInTheDocument()
  })

  it('loading 状态下不应展示空数据提示', () => {
    render(<DataTable data={null} loading={true} />)
    expect(screen.queryByText('当前查询无返回数据')).not.toBeInTheDocument()
  })

  it('应展示分页总数信息', () => {
    const data = createMockQueryResult(100)
    render(<DataTable data={data} pageSize={20} />)
    expect(screen.getByText(/共 100 条数据/)).toBeInTheDocument()
  })
})
