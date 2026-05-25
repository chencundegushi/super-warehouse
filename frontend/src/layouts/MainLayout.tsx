/**
 * 应用主布局组件
 * 实现侧边栏导航和响应式布局：
 * - 桌面端（≥1024px）：侧边栏常驻，宽度240px
 * - 平板端（≥768px且<1024px）：侧边栏可收起/展开，收起宽度64px
 */
import { useState, useEffect, useCallback } from 'react'
import { Layout, Menu } from 'antd'
import {
  MessageOutlined,
  DashboardOutlined,
  ThunderboltOutlined,
  DatabaseOutlined,
  HistoryOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import type { MenuProps } from 'antd'

const { Sider, Content } = Layout

/** 桌面端断点阈值 */
const DESKTOP_BREAKPOINT = 1024

/** 侧边栏导航菜单项配置 */
const menuItems: MenuProps['items'] = [
  {
    key: '/chat',
    icon: <MessageOutlined />,
    label: '对话',
  },
  {
    key: '/metrics',
    icon: <DashboardOutlined />,
    label: '指标管理',
  },
  {
    key: '/skills',
    icon: <ThunderboltOutlined />,
    label: '技能管理',
  },
  {
    key: '/ddl',
    icon: <DatabaseOutlined />,
    label: 'DDL管理',
  },
  {
    key: '/history',
    icon: <HistoryOutlined />,
    label: '历史记录',
  },
]

/**
 * 主布局组件
 * 包含侧边栏导航和内容区域，支持响应式布局
 * @returns 主布局组件
 */
function MainLayout() {
  const navigate = useNavigate()
  const location = useLocation()

  // 1.判断当前是否为桌面端
  const [isDesktop, setIsDesktop] = useState(
    () => window.innerWidth >= DESKTOP_BREAKPOINT
  )
  // 2.侧边栏折叠状态（仅平板端生效）
  const [collapsed, setCollapsed] = useState(false)

  // 3.监听窗口尺寸变化，更新响应式状态
  useEffect(() => {
    const handleResize = () => {
      const desktop = window.innerWidth >= DESKTOP_BREAKPOINT
      setIsDesktop(desktop)
      // 桌面端始终展开侧边栏
      if (desktop) {
        setCollapsed(false)
      }
    }

    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  /** 处理菜单项点击，导航到对应路由 */
  const handleMenuClick: MenuProps['onClick'] = useCallback(
    ({ key }: { key: string }) => {
      console.log('[MainLayout] Navigate to:', key)
      navigate(key)
    },
    [navigate]
  )

  /** 切换侧边栏折叠状态（平板端） */
  const toggleCollapsed = useCallback(() => {
    setCollapsed((prev) => !prev)
  }, [])

  // 4.确定当前选中的菜单项
  const selectedKey = location.pathname === '/' ? '/chat' : location.pathname

  return (
    <Layout style={{ height: '100%' }}>
      <Sider
        width={240}
        collapsedWidth={64}
        collapsed={!isDesktop && collapsed}
        collapsible={!isDesktop}
        trigger={null}
        style={{
          overflow: 'auto',
          height: '100vh',
          position: 'fixed',
          left: 0,
          top: 0,
          bottom: 0,
          zIndex: 100,
          transition: `width var(--transition-normal) ease`,
        }}
      >
        {/* 侧边栏顶部标题和折叠按钮 */}
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: !isDesktop && collapsed ? 'center' : 'space-between',
            padding: !isDesktop && collapsed ? '0' : '0 16px',
            borderBottom: '1px solid var(--color-border-secondary)',
          }}
        >
          {(!collapsed || isDesktop) && (
            <span
              style={{
                fontSize: 16,
                fontWeight: 600,
                color: 'var(--color-text-primary)',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              Data Agent
            </span>
          )}
          {/* 平板端显示折叠/展开按钮 */}
          {!isDesktop && (
            <span
              onClick={toggleCollapsed}
              style={{ cursor: 'pointer', fontSize: 16, color: 'var(--color-text-secondary)' }}
              role="button"
              aria-label={collapsed ? '展开侧边栏' : '收起侧边栏'}
            >
              {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            </span>
          )}
        </div>

        {/* 导航菜单 */}
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={handleMenuClick}
          style={{ borderRight: 0, marginTop: 8 }}
        />
      </Sider>

      {/* 内容区域 */}
      <Layout
        style={{
          marginLeft: !isDesktop && collapsed ? 64 : 240,
          transition: `margin-left var(--transition-normal) ease`,
          height: '100%',
        }}
      >
        <Content
          style={{
            height: '100%',
            overflow: 'auto',
            position: 'relative',
          }}
        >
          {/* 页面切换动效容器 */}
          <div className="page-transition-wrapper">
            <Outlet />
          </div>
        </Content>
      </Layout>
    </Layout>
  )
}

export default MainLayout
