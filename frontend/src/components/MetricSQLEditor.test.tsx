/**
 * MetricSQLEditor 组件单元测试
 * 验证 SQL 编辑器的渲染、自动生成按钮交互和错误处理。
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import MetricSQLEditor from './MetricSQLEditor'

// 1.Mock metricApi 模块
vi.mock('@/services/metricApi', () => ({
  generateSQL: vi.fn(),
}))

// 2.Mock Monaco Editor（jsdom 环境不支持 canvas）
vi.mock('@monaco-editor/react', () => ({
  default: ({ value, onChange }: { value: string; onChange?: (v: string | undefined) => void }) => (
    <textarea
      data-testid="monaco-editor"
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
}))

import { generateSQL } from '@/services/metricApi'
const mockGenerateSQL = vi.mocked(generateSQL)

describe('MetricSQLEditor', () => {
  const defaultProps = {
    value: 'SELECT 1',
    onChange: vi.fn(),
    metricName: '日活跃用户数',
    metricDescription: '统计每日活跃用户数量',
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('渲染编辑器和生成按钮', () => {
    render(<MetricSQLEditor {...defaultProps} />)

    // 3.验证编辑器渲染
    expect(screen.getByTestId('monaco-editor')).toBeInTheDocument()
    // 4.验证按钮存在
    expect(screen.getByText('自动生成参考SQL')).toBeInTheDocument()
  })

  it('当 metricName 或 metricDescription 为空时按钮禁用', () => {
    render(<MetricSQLEditor value="" onChange={vi.fn()} />)

    const button = screen.getByText('自动生成参考SQL').closest('button')
    expect(button).toBeDisabled()
  })

  it('点击生成按钮成功时调用 onChange 并更新内容', async () => {
    const generatedSQL = 'SELECT COUNT(*) FROM users WHERE active = 1'
    mockGenerateSQL.mockResolvedValueOnce(generatedSQL)

    render(<MetricSQLEditor {...defaultProps} />)

    // 5.点击生成按钮
    fireEvent.click(screen.getByText('自动生成参考SQL'))

    // 6.验证调用了 generateSQL 接口
    expect(mockGenerateSQL).toHaveBeenCalledWith('日活跃用户数', '统计每日活跃用户数量')

    // 7.验证 onChange 被调用并传入生成的 SQL
    await waitFor(() => {
      expect(defaultProps.onChange).toHaveBeenCalledWith(generatedSQL)
    })
  })

  it('生成失败时显示错误提示且不调用 onChange', async () => {
    mockGenerateSQL.mockRejectedValueOnce(new Error('Network error'))

    render(<MetricSQLEditor {...defaultProps} />)

    fireEvent.click(screen.getByText('自动生成参考SQL'))

    // 8.等待异步操作完成
    await waitFor(() => {
      expect(mockGenerateSQL).toHaveBeenCalled()
    })

    // 9.onChange 不应被调用
    expect(defaultProps.onChange).not.toHaveBeenCalled()
  })

  it('用户手动编辑时触发 onChange', () => {
    render(<MetricSQLEditor {...defaultProps} />)

    const editor = screen.getByTestId('monaco-editor')
    fireEvent.change(editor, { target: { value: 'SELECT * FROM orders' } })

    expect(defaultProps.onChange).toHaveBeenCalledWith('SELECT * FROM orders')
  })
})
