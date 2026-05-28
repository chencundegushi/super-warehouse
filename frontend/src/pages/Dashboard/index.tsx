/**
 * Dashboard 列表页面
 * 展示所有已保存的 Dashboard，支持新建、删除、重命名操作。
 * 按最近访问时间降序排列，点击卡片跳转到查看页。
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Button,
  Card,
  Empty,
  Spin,
  Modal,
  Input,
  message,
  Popconfirm,
  Space,
  Tag,
} from 'antd'
import {
  PlusOutlined,
  FundProjectionScreenOutlined,
  DeleteOutlined,
  EditOutlined,
  ClockCircleOutlined,
  AppstoreOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  listDashboards,
  deleteDashboard,
  updateDashboard,
} from '@/services/dashboardApi'
import type { DashboardSummary } from '@/services/dashboardApi'

/**
 * 格式化时间为可读字符串
 * @param isoStr - ISO 8601 时间字符串
 * @returns 格式化后的时间字符串
 */
function formatTime(isoStr: string): string {
  if (!isoStr) return '-'
  const date = new Date(isoStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  const diffHour = Math.floor(diffMs / 3600000)
  const diffDay = Math.floor(diffMs / 86400000)

  // 1.相对时间展示
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  if (diffHour < 24) return `${diffHour} 小时前`
  if (diffDay < 7) return `${diffDay} 天前`

  // 2.超过7天展示具体日期
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}

/**
 * Dashboard 列表页面组件
 * 展示所有已保存的 Dashboard 卡片，支持 CRUD 操作
 */
function DashboardListPage() {
  // 1.状态管理
  const [dashboards, setDashboards] = useState<DashboardSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [renameModalOpen, setRenameModalOpen] = useState(false)
  const [renamingDashboard, setRenamingDashboard] = useState<DashboardSummary | null>(null)
  const [newName, setNewName] = useState('')
  const [renameLoading, setRenameLoading] = useState(false)
  const navigate = useNavigate()

  /**
   * 加载 Dashboard 列表
   * 按最近访问时间降序排列
   */
  const loadDashboards = useCallback(async () => {
    console.log('[DashboardListPage] Loading dashboard list')
    setLoading(true)
    try {
      const result = await listDashboards(1, 50)
      setDashboards(result.items)
      console.log('[DashboardListPage] Loaded dashboards, count:', result.items.length)
    } catch (err) {
      console.error('[DashboardListPage] Failed to load dashboards:', err)
      message.error('加载大屏列表失败')
    } finally {
      setLoading(false)
    }
  }, [])

  // 2.页面挂载时加载数据
  useEffect(() => {
    loadDashboards()
  }, [loadDashboards])

  /**
   * 删除 Dashboard
   * @param dashboard - 要删除的 Dashboard
   */
  const handleDelete = useCallback(async (dashboard: DashboardSummary) => {
    console.log('[DashboardListPage] Deleting dashboard, id:', dashboard.id)
    try {
      await deleteDashboard(dashboard.id)
      message.success(`已删除「${dashboard.name}」`)
      loadDashboards()
    } catch (err) {
      console.error('[DashboardListPage] Failed to delete dashboard:', err)
      message.error('删除失败')
    }
  }, [loadDashboards])

  /**
   * 打开重命名弹窗
   * @param dashboard - 要重命名的 Dashboard
   */
  const handleOpenRename = useCallback((dashboard: DashboardSummary) => {
    console.log('[DashboardListPage] Opening rename modal, id:', dashboard.id)
    setRenamingDashboard(dashboard)
    setNewName(dashboard.name)
    setRenameModalOpen(true)
  }, [])

  /**
   * 执行重命名操作
   */
  const handleRename = useCallback(async () => {
    if (!renamingDashboard) return
    const trimmedName = newName.trim()
    if (!trimmedName) {
      message.warning('名称不能为空')
      return
    }
    if (trimmedName.length > 64) {
      message.warning('名称不能超过64个字符')
      return
    }
    console.log('[DashboardListPage] Renaming dashboard, id:', renamingDashboard.id, 'newName:', trimmedName)
    setRenameLoading(true)
    try {
      await updateDashboard(renamingDashboard.id, { name: trimmedName })
      message.success('重命名成功')
      setRenameModalOpen(false)
      setRenamingDashboard(null)
      loadDashboards()
    } catch (err) {
      console.error('[DashboardListPage] Failed to rename dashboard:', err)
      message.error('重命名失败，名称可能已被使用')
    } finally {
      setRenameLoading(false)
    }
  }, [renamingDashboard, newName, loadDashboards])

  /**
   * 点击卡片跳转到查看页
   * @param id - Dashboard ID
   */
  const handleCardClick = useCallback((id: string) => {
    console.log('[DashboardListPage] Navigating to dashboard, id:', id)
    navigate(`/dashboards/${id}`)
  }, [navigate])

  // 3.渲染页面
  return (
    <div style={{ padding: '16px 24px', height: '100%', overflow: 'auto' }}>
      {/* 页面标题和操作按钮 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Space>
          <FundProjectionScreenOutlined style={{ fontSize: 20, color: '#1890ff' }} />
          <h2 style={{ margin: 0, color: '#fff' }}>智能大屏</h2>
        </Space>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate('/dashboards/new')}
        >
          新建大屏
        </Button>
      </div>

      {/* Dashboard 卡片列表 */}
      <Spin spinning={loading} tip="加载中...">
        {dashboards.length === 0 && !loading ? (
          <Card>
            <Empty
              description="暂无大屏，点击「新建大屏」开始创建"
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            >
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => navigate('/dashboards/new')}
              >
                新建大屏
              </Button>
            </Empty>
          </Card>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16 }}>
            {dashboards.map((dashboard) => (
              <Card
                key={dashboard.id}
                hoverable
                style={{ cursor: 'pointer' }}
                onClick={() => handleCardClick(dashboard.id)}
                actions={[
                  <EditOutlined
                    key="rename"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleOpenRename(dashboard)
                    }}
                  />,
                  <Popconfirm
                    key="delete"
                    title="确认删除"
                    description={`确定要删除「${dashboard.name}」吗？此操作不可恢复。`}
                    onConfirm={(e) => {
                      e?.stopPropagation()
                      handleDelete(dashboard)
                    }}
                    onCancel={(e) => e?.stopPropagation()}
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                  >
                    <DeleteOutlined
                      onClick={(e) => e.stopPropagation()}
                      style={{ color: '#ff4d4f' }}
                    />
                  </Popconfirm>,
                ]}
              >
                <Card.Meta
                  title={
                    <span style={{ fontSize: 16 }}>{dashboard.name}</span>
                  }
                  description={
                    <div style={{ marginTop: 8 }}>
                      <Space direction="vertical" size={4} style={{ width: '100%' }}>
                        <Space>
                          <AppstoreOutlined />
                          <Tag color="blue">{dashboard.panelCount} 个面板</Tag>
                        </Space>
                        <Space>
                          <ClockCircleOutlined />
                          <span style={{ fontSize: 12, color: '#999' }}>
                            创建于 {formatTime(dashboard.createdAt)}
                          </span>
                        </Space>
                        <Space>
                          <ClockCircleOutlined />
                          <span style={{ fontSize: 12, color: '#999' }}>
                            最近访问 {formatTime(dashboard.lastAccessedAt)}
                          </span>
                        </Space>
                      </Space>
                    </div>
                  }
                />
              </Card>
            ))}
          </div>
        )}
      </Spin>

      {/* 重命名弹窗 */}
      <Modal
        title="重命名大屏"
        open={renameModalOpen}
        onOk={handleRename}
        onCancel={() => {
          setRenameModalOpen(false)
          setRenamingDashboard(null)
        }}
        confirmLoading={renameLoading}
        okText="确认"
        cancelText="取消"
        destroyOnClose
      >
        <Input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="请输入新名称"
          maxLength={64}
          showCount
          onPressEnter={handleRename}
          autoFocus
        />
      </Modal>
    </div>
  )
}

export default DashboardListPage
