/**
 * 应用根组件
 * 配置 Ant Design 深色主题、全局路由和页面布局
 */
import { ConfigProvider, theme, App as AntApp } from 'antd'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import zhCN from 'antd/locale/zh_CN'
import MainLayout from './layouts/MainLayout'
import ChatPage from './pages/Chat'
import MetricsPage from './pages/Metrics'
import SkillsPage from './pages/Skills'
import DDLPage from './pages/DDL'
import HistoryPage from './pages/History'

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
              <Route path="/history" element={<HistoryPage />} />
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
