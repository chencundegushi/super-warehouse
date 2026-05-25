/**
 * SQLPreview 组件单元测试
 * 验证 SQL 预览展示、确认/拒绝交互、反馈输入等核心功能。
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import SQLPreview from './SQLPreview'
import type { SQLPreviewProps } from './SQLPreview'

// 1.Mock Monaco Editor，避免在测试环境中加载完整编辑器
vi.mock('@monaco-editor/react', () => ({
  default: ({ value }: { value: string }) => (
    <div data-testid="monaco-editor">{value}</div>
  ),
}))

const defaultProps: SQLPreviewProps = {
  sql: 'SELECT * FROM orders WHERE status = 1',
  explanation: '查询所有状态为1的订单',
  source: 'sql_generator',
  onConfirm: vi.fn(),
  onReject: vi.fn(),
}

describe('SQLPreview', () => {
  it('应展示 SQL 解释说明文本', () => {
    render(<SQLPreview {...defaultProps} />)
    expect(screen.getByText('查询所有状态为1的订单')).toBeInTheDocument()
  })

  it('应展示 SQL 内容', () => {
    render(<SQLPreview {...defaultProps} />)
    expect(screen.getByTestId('monaco-editor')).toHaveTextContent(
      'SELECT * FROM orders WHERE status = 1'
    )
  })

  it('应展示来源标签 - SQL生成器', () => {
    render(<SQLPreview {...defaultProps} source="sql_generator" />)
    expect(screen.getByText(/SQL生成器/)).toBeInTheDocument()
  })

  it('应展示来源标签 - 指标匹配', () => {
    render(<SQLPreview {...defaultProps} source="metric" />)
    expect(screen.getByText(/指标匹配/)).toBeInTheDocument()
  })

  it('点击确认执行按钮应调用 onConfirm', () => {
    const onConfirm = vi.fn()
    render(<SQLPreview {...defaultProps} onConfirm={onConfirm} />)
    fireEvent.click(screen.getByText('确认执行'))
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('点击拒绝按钮应展示反馈输入框', () => {
    render(<SQLPreview {...defaultProps} />)
    // Ant Design 对两个中文字符的按钮会插入空格，使用 role 查找
    const rejectBtn = screen.getByRole('button', { name: /拒\s*绝/ })
    fireEvent.click(rejectBtn)
    expect(
      screen.getByPlaceholderText(/请输入修改意见/)
    ).toBeInTheDocument()
    expect(screen.getByText('提交修改意见')).toBeInTheDocument()
  })

  it('提交修改意见应调用 onReject 并传递反馈内容', () => {
    const onReject = vi.fn()
    render(<SQLPreview {...defaultProps} onReject={onReject} />)

    // 2.点击拒绝展示输入框
    const rejectBtn = screen.getByRole('button', { name: /拒\s*绝/ })
    fireEvent.click(rejectBtn)

    // 3.输入反馈内容
    const textarea = screen.getByPlaceholderText(/请输入修改意见/)
    fireEvent.change(textarea, { target: { value: '请添加 LIMIT 100' } })

    // 4.提交反馈
    fireEvent.click(screen.getByText('提交修改意见'))
    expect(onReject).toHaveBeenCalledWith('请添加 LIMIT 100')
  })

  it('空反馈时提交按钮应禁用', () => {
    render(<SQLPreview {...defaultProps} />)
    const rejectBtn = screen.getByRole('button', { name: /拒\s*绝/ })
    fireEvent.click(rejectBtn)
    const submitBtn = screen.getByText('提交修改意见')
    expect(submitBtn.closest('button')).toBeDisabled()
  })

  it('loading 状态下确认按钮应显示加载状态', () => {
    render(<SQLPreview {...defaultProps} loading={true} />)
    const confirmBtn = screen.getByText('确认执行').closest('button')
    expect(confirmBtn).toHaveClass('ant-btn-loading')
  })

  it('点击取消应隐藏反馈输入框', () => {
    render(<SQLPreview {...defaultProps} />)
    const rejectBtn = screen.getByRole('button', { name: /拒\s*绝/ })
    fireEvent.click(rejectBtn)
    expect(screen.getByPlaceholderText(/请输入修改意见/)).toBeInTheDocument()

    const cancelBtn = screen.getByRole('button', { name: /取\s*消/ })
    fireEvent.click(cancelBtn)
    expect(screen.queryByPlaceholderText(/请输入修改意见/)).not.toBeInTheDocument()
  })
})
