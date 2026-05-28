/**
 * 应用根组件
 * 配置 Ant Design 深色主题、全局路由和页面布局
 */
import { lazy, Suspense } from 'react'
import { ConfigProvider, theme, App as AntApp, Spin } from 'antd'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import zhCN from 'antd/locale/zh_CN'
import MainLayout from './layouts/MainLayout'
import ChatPage from './pages/Chat'
import MetricsPage from './pages/Metrics'
import SkillsPage from './pages/Skills'
import DDLPage from './pages/DDL'
import HistoryPage from './pages/History'
import LineagePage from './pages/Lineage'
import SettingsPage from './pages/Settings'

// 懒加载 Dashboard 相关页面
const DashboardListPage = lazy(() => import('./pages/Dashboard/index'))
const DashboardViewPage = lazy(() => import('./pages/Dashboard/DashboardView'))
const DashboardBuilderPage = lazy(() => import('./pages/Dashboard/DashboardBuilder'))

/**
 * 应用入口组件，配置全局主题和路由
 * @returns 包含主题配置、路由和布局的根组件
 */
function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: '#1668dc',
          colorBgBase: '#141414',
          colorBgContainer: '#1f1f1f',
          colorBgElevated: '#2a2a2a',
          colorBorder: '#424242',
          colorBorderSecondary: '#303030',
          borderRadius: 6,
        },
        components: {
          Layout: {
            siderBg: '#1f1f1f',
            headerBg: '#1f1f1f',
            bodyBg: '#141414',
          },
          Menu: {
            darkItemBg: '#1f1f1f',
            darkSubMenuItemBg: '#141414',
          },
        },
      }}
    >
      <AntApp>
        <BrowserRouter>
          <Routes>
            <Route element={<MainLayout />}>
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/metrics" element={<MetricsPage />} />
              <Route path="/skills" element={<SkillsPage />} />
              <Route path="/ddl" element={<DDLPage />} />
              <Route path="/lineage" element={<LineagePage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              {/* Dashboard 智能大屏路由（懒加载） */}
              <Route path="/dashboards" element={<Suspense fallback={<Spin style={{ display: 'flex', justifyContent: 'center', marginTop: 120 }} />}><DashboardListPage /></Suspense>} />
              <Route path="/dashboards/new" element={<Suspense fallback={<Spin style={{ display: 'flex', justifyContent: 'center', marginTop: 120 }} />}><DashboardBuilderPage /></Suspense>} />
              <Route path="/dashboards/:id" element={<Suspense fallback={<Spin style={{ display: 'flex', justifyContent: 'center', marginTop: 120 }} />}><DashboardViewPage /></Suspense>} />
              {/* 默认重定向到对话页面 */}
              <Route path="/" element={<Navigate to="/chat" replace />} />
              <Route path="*" element={<Navigate to="/chat" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  )
}

export default App
