/**
 * App 组件基础测试
 * 验证应用根组件能正常渲染，包含主布局和侧边栏导航
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from './App'

describe('App', () => {
  it('renders without crashing', () => {
    render(<App />)
    // 验证侧边栏标题存在
    expect(screen.getByText('Doris Agent')).toBeInTheDocument()
  })

  it('renders sidebar navigation items', () => {
    render(<App />)
    // 验证导航菜单项存在（使用 role 定位菜单项）
    const menuItems = screen.getAllByRole('menuitem')
    expect(menuItems.length).toBe(5)
    expect(screen.getByText('指标管理')).toBeInTheDocument()
    expect(screen.getByText('技能管理')).toBeInTheDocument()
    expect(screen.getByText('DDL管理')).toBeInTheDocument()
    expect(screen.getByText('历史记录')).toBeInTheDocument()
  })
})
