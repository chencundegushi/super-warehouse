/**
 * Dashboard 查看页面（支持只读模式和编辑模式）
 * 加载已保存的 Dashboard 配置，并行执行所有面板 SQL，使用 react-grid-layout 渲染网格布局。
 * 每个面板独立展示加载状态/数据/错误，支持全局刷新。
 * 编辑模式下支持面板拖拽移动、缩放、删除和图表类型切换，退出时提示保存/放弃。
 *
 * @module DashboardView
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Button,
  Skeleton,
  Space,
  Typography,
  Modal,
  message,
} from 'antd'
import {
  ReloadOutlined,
  ArrowLeftOutlined,
  ClockCircleOutlined,
  EditOutlined,
  CheckOutlined,
} from '@ant-design/icons'
import { GridLayout } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import './Dashboard.css'
import {
  getDashboard,
  executeAllPanels,
  updateDashboard,
} from '@/services/dashboardApi'
import type {
  Dashboard,
  Panel,
  PanelExecutionResult,
} from '@/services/dashboardApi'
import type { ChartType, QueryResult } from '@/types'
import DashboardPanel from '@/components/DashboardPanel'

const { Title, Text } = Typography

/** 网格布局列数 */
const GRID_COLS = 12
/** 网格行高（像素） */
const GRID_ROW_HEIGHT = 100

/** 单面板数据状态 */
interface PanelDataState {
  loading: boolean
  data?: QueryResult
  error?: string
}

/**
 * 格式化刷新时间戳
 * @param date - 时间对象
 * @returns 格式化后的时间字符串
 */
function formatRefreshTime(date: Date | null): string {
  if (!date) return '-'
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/**
 * Dashboard 查看页面组件
 * 支持只读模式和编辑模式：编辑模式下面板可拖拽/缩放/删除/切换图表类型
 */
function DashboardView() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  // 1.状态管理
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [configLoading, setConfigLoading] = useState(true)
  const [panelDataMap, setPanelDataMap] = useState<Record<string, PanelDataState>>({})
  const [lastRefreshTime, setLastRefreshTime] = useState<Date | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  // 2.编辑模式状态管理
  const [editMode, setEditMode] = useState(false)
  const [isDirty, setIsDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [exitModalOpen, setExitModalOpen] = useState(false)
  /** 进入编辑模式时保存的原始面板快照，用于放弃修改时恢复 */
  const originalPanelsRef = useRef<Panel[]>([])

  // 3.网格容器宽度动态计算
  const gridContainerRef = useRef<HTMLDivElement>(null)
  const [gridWidth, setGridWidth] = useState(1200)

  console.log('[DashboardView] Rendered, dashboardId:', id, 'editMode:', editMode)

  // 动态监听容器宽度变化，更新网格宽度
  useEffect(() => {
    const container = gridContainerRef.current
    if (!container) return
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const width = entry.contentRect.width
        if (width > 0) setGridWidth(width)
      }
    })
    observer.observe(container)
    // 初始化宽度
    const initWidth = container.clientWidth
    if (initWidth > 0) setGridWidth(initWidth)
    return () => observer.disconnect()
  }, [configLoading])

  /**
   * 执行所有面板 SQL 并更新面板数据状态
   * 调用 executeAllPanels 接口并行执行，每个面板独立处理结果
   * @param dashboardId - Dashboard ID
   * @param panels - 面板列表
   */
  const executePanels = useCallback(async (dashboardId: string, panels: Panel[]) => {
    console.log('[DashboardView] Executing all panels, dashboardId:', dashboardId)

    // 1.将所有面板设为加载状态
    const loadingState: Record<string, PanelDataState> = {}
    panels.forEach((panel) => {
      loadingState[panel.id] = { loading: true }
    })
    setPanelDataMap(loadingState)
    setRefreshing(true)

    try {
      // 2.并行执行所有面板 SQL
      const results: PanelExecutionResult[] = await executeAllPanels(dashboardId)
      console.log('[DashboardView] All panels executed, results count:', results.length)

      // 3.更新每个面板的数据状态
      const newDataMap: Record<string, PanelDataState> = {}
      results.forEach((result) => {
        if (result.success && result.data) {
          newDataMap[result.panelId] = { loading: false, data: result.data }
        } else {
          newDataMap[result.panelId] = {
            loading: false,
            error: result.error || '执行失败',
          }
        }
      })

      // 4.处理未返回结果的面板（可能被跳过）
      panels.forEach((panel) => {
        if (!newDataMap[panel.id]) {
          newDataMap[panel.id] = { loading: false, error: '未获取到执行结果' }
        }
      })

      setPanelDataMap(newDataMap)
      setLastRefreshTime(new Date())
    } catch (err) {
      console.error('[DashboardView] Failed to execute panels:', err)
      // 5.全局执行失败时，所有面板标记为错误
      const errorState: Record<string, PanelDataState> = {}
      panels.forEach((panel) => {
        errorState[panel.id] = { loading: false, error: '数据加载失败，请重试' }
      })
      setPanelDataMap(errorState)
      message.error('面板数据加载失败')
    } finally {
      setRefreshing(false)
    }
  }, [])

  /**
   * 加载 Dashboard 配置并执行面板 SQL
   * 页面挂载时调用，加载配置后自动执行所有面板查询
   */
  const loadDashboard = useCallback(async () => {
    if (!id) {
      console.error('[DashboardView] No dashboard ID provided')
      message.error('Dashboard ID 缺失')
      navigate('/dashboards')
      return
    }

    console.log('[DashboardView] Loading dashboard config, id:', id)
    setConfigLoading(true)

    try {
      const data = await getDashboard(id)
      console.log('[DashboardView] Dashboard loaded, name:', data.name, 'panels:', data.panels.length)
      setDashboard(data)
      setConfigLoading(false)

      // 配置加载完成后，并行执行所有面板 SQL
      if (data.panels.length > 0) {
        await executePanels(id, data.panels)
      }
    } catch (err) {
      console.error('[DashboardView] Failed to load dashboard:', err)
      message.error('Dashboard 加载失败，即将返回列表')
      setConfigLoading(false)
      // 加载失败时导航回列表页
      setTimeout(() => navigate('/dashboards'), 1500)
    }
  }, [id, navigate, executePanels])

  // 2.页面挂载时加载数据
  useEffect(() => {
    loadDashboard()
  }, [loadDashboard])

  /**
   * 全局刷新：重新执行所有面板 SQL
   */
  const handleGlobalRefresh = useCallback(async () => {
    if (!dashboard || !id) return
    console.log('[DashboardView] Global refresh triggered')
    await executePanels(id, dashboard.panels)
  }, [dashboard, id, executePanels])

  /**
   * 单面板刷新：重新执行指定面板 SQL
   * @param panelId - 面板 ID
   */
  const handlePanelRefresh = useCallback(async (panelId: string) => {
    if (!id) return
    console.log('[DashboardView] Single panel refresh, panelId:', panelId)

    // 1.设置该面板为加载状态
    setPanelDataMap((prev) => ({
      ...prev,
      [panelId]: { loading: true },
    }))

    try {
      // 2.使用 executeAllPanels 获取所有结果，提取目标面板
      const results = await executeAllPanels(id)
      const panelResult = results.find((r) => r.panelId === panelId)

      if (panelResult) {
        setPanelDataMap((prev) => ({
          ...prev,
          [panelId]: panelResult.success && panelResult.data
            ? { loading: false, data: panelResult.data }
            : { loading: false, error: panelResult.error || '执行失败' },
        }))
      } else {
        setPanelDataMap((prev) => ({
          ...prev,
          [panelId]: { loading: false, error: '未获取到执行结果' },
        }))
      }
      setLastRefreshTime(new Date())
    } catch (err) {
      console.error('[DashboardView] Failed to refresh panel:', panelId, err)
      setPanelDataMap((prev) => ({
        ...prev,
        [panelId]: { loading: false, error: '刷新失败，请重试' },
      }))
    }
  }, [id])

  /**
   * 生成 react-grid-layout 布局配置
   * 将面板的 position 转换为 GridLayout 的 layout 数组
   * 编辑模式下启用拖拽/缩放，设置最小尺寸约束
   */
  const gridLayout = useMemo(() => {
    if (!dashboard) return []
    return dashboard.panels.map((panel) => ({
      i: panel.id,
      x: panel.position.x,
      y: panel.position.y,
      w: panel.position.w,
      h: panel.position.h,
      minW: 3,
      minH: 3,
      static: !editMode,
    }))
  }, [dashboard, editMode])

  // ============================================================
  // 编辑模式相关操作
  // ============================================================

  /**
   * 进入编辑模式：保存当前面板快照用于后续恢复
   */
  const handleEnterEditMode = useCallback(() => {
    if (!dashboard) return
    console.log('[DashboardView] Entering edit mode')
    originalPanelsRef.current = JSON.parse(JSON.stringify(dashboard.panels))
    setEditMode(true)
    setIsDirty(false)
  }, [dashboard])

  /**
   * 尝试退出编辑模式：如果有未保存修改则弹出确认弹窗
   */
  const handleExitEditMode = useCallback(() => {
    if (isDirty) {
      console.log('[DashboardView] Exiting edit mode with unsaved changes, showing modal')
      setExitModalOpen(true)
    } else {
      console.log('[DashboardView] Exiting edit mode, no changes')
      setEditMode(false)
    }
  }, [isDirty])

  /**
   * 保存修改：调用 updateDashboard API 持久化布局变更
   */
  const handleSaveChanges = useCallback(async () => {
    if (!dashboard || !id) return
    console.log('[DashboardView] Saving dashboard changes, id:', id)
    setSaving(true)

    try {
      const panelsPayload = dashboard.panels.map((p) => ({
        id: p.id,
        title: p.title,
        sql: p.sql,
        chartType: p.chartType,
        position: p.position,
      }))
      await updateDashboard(id, { panels: panelsPayload })
      message.success('保存成功')
      setIsDirty(false)
      setEditMode(false)
      setExitModalOpen(false)
    } catch (err) {
      console.error('[DashboardView] Failed to save changes:', err)
      message.error('保存失败，请重试')
    } finally {
      setSaving(false)
    }
  }, [dashboard, id])

  /**
   * 放弃修改：恢复到进入编辑模式前的面板快照
   */
  const handleDiscardChanges = useCallback(() => {
    if (!dashboard) return
    console.log('[DashboardView] Discarding changes, reverting to original panels')
    setDashboard({
      ...dashboard,
      panels: JSON.parse(JSON.stringify(originalPanelsRef.current)),
    })
    setIsDirty(false)
    setEditMode(false)
    setExitModalOpen(false)
  }, [dashboard])

  /**
   * 继续编辑：关闭弹窗，保持编辑模式
   */
  const handleContinueEditing = useCallback(() => {
    console.log('[DashboardView] Continuing editing')
    setExitModalOpen(false)
  }, [])

  /**
   * 处理布局变更（拖拽/缩放后触发）
   * 更新面板的 position 信息并标记为已修改
   * @param newLayout - 新的布局数组
   */
  const handleLayoutChange = useCallback((newLayout: readonly { i: string; x: number; y: number; w: number; h: number }[]) => {
    if (!dashboard || !editMode) return
    console.log('[DashboardView] Layout changed, updating panel positions')

    const updatedPanels = dashboard.panels.map((panel) => {
      const layoutItem = newLayout.find((item) => item.i === panel.id)
      if (layoutItem) {
        return {
          ...panel,
          position: {
            x: layoutItem.x,
            y: layoutItem.y,
            w: layoutItem.w,
            h: layoutItem.h,
          },
        }
      }
      return panel
    })

    setDashboard({ ...dashboard, panels: updatedPanels })
    setIsDirty(true)
  }, [dashboard, editMode])

  /**
   * 删除面板：从面板列表中移除指定面板
   * @param panelId - 要删除的面板 ID
   */
  const handleDeletePanel = useCallback((panelId: string) => {
    if (!dashboard) return
    console.log('[DashboardView] Deleting panel, panelId:', panelId)

    const updatedPanels = dashboard.panels.filter((p) => p.id !== panelId)
    setDashboard({ ...dashboard, panels: updatedPanels, panelCount: updatedPanels.length })
    setIsDirty(true)
  }, [dashboard])

  /**
   * 切换面板图表类型
   * @param panelId - 面板 ID
   * @param newType - 新的图表类型
   */
  const handleChartTypeChange = useCallback((panelId: string, newType: ChartType) => {
    if (!dashboard) return
    console.log('[DashboardView] Changing chart type, panelId:', panelId, 'newType:', newType)

    const updatedPanels = dashboard.panels.map((p) =>
      p.id === panelId ? { ...p, chartType: newType } : p
    )
    setDashboard({ ...dashboard, panels: updatedPanels })
    setIsDirty(true)
  }, [dashboard])

  /**
   * 修改面板标题
   * @param panelId - 面板 ID
   * @param newTitle - 新标题
   */
  const handleTitleChange = useCallback((panelId: string, newTitle: string) => {
    if (!dashboard) return
    console.log('[DashboardView] Changing panel title, panelId:', panelId, 'newTitle:', newTitle)

    const updatedPanels = dashboard.panels.map((p) =>
      p.id === panelId ? { ...p, title: newTitle } : p
    )
    setDashboard({ ...dashboard, panels: updatedPanels })
    setIsDirty(true)
  }, [dashboard])

  // ============================================================
  // 渲染：骨架屏（配置加载中）
  // ============================================================
  if (configLoading) {
    return (
      <div style={{ padding: '16px 24px', height: '100%', overflow: 'auto' }}>
        {/* 顶部骨架 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
          <Skeleton.Input active style={{ width: 200, height: 32 }} />
          <Skeleton.Button active style={{ width: 100 }} />
        </div>
        {/* 面板骨架屏 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <Skeleton key={i} active paragraph={{ rows: 6 }} />
          ))}
        </div>
      </div>
    )
  }

  // ============================================================
  // 渲染：Dashboard 不存在
  // ============================================================
  if (!dashboard) {
    return (
      <div style={{ padding: '16px 24px', textAlign: 'center', paddingTop: 100 }}>
        <Title level={4} style={{ color: '#fff' }}>Dashboard 未找到</Title>
        <Button type="primary" onClick={() => navigate('/dashboards')}>
          返回列表
        </Button>
      </div>
    )
  }

  // ============================================================
  // 渲染：Dashboard 查看页面
  // ============================================================
  return (
    <div className="dashboard-scroll-container" ref={gridContainerRef} style={{ padding: '16px 24px', height: '100vh', overflowY: 'auto' }}>
      {/* 页面头部：标题 + 操作按钮 */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 16,
      }}>
        <Space>
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/dashboards')}
            style={{ color: '#fff' }}
          />
          <Title level={4} style={{ margin: 0, color: '#fff' }}>
            {dashboard.name}
          </Title>
        </Space>

        <Space>
          {/* 最近刷新时间 */}
          {lastRefreshTime && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              <ClockCircleOutlined style={{ marginRight: 4 }} />
              最近刷新: {formatRefreshTime(lastRefreshTime)}
            </Text>
          )}
          {/* 全局刷新按钮 */}
          <Button
            icon={<ReloadOutlined spin={refreshing} />}
            onClick={handleGlobalRefresh}
            loading={refreshing}
          >
            刷新
          </Button>
          {/* 编辑模式切换按钮 */}
          {editMode ? (
            <Button
              type="primary"
              icon={<CheckOutlined />}
              onClick={handleExitEditMode}
            >
              退出编辑
            </Button>
          ) : (
            <Button
              icon={<EditOutlined />}
              onClick={handleEnterEditMode}
            >
              编辑模式
            </Button>
          )}
        </Space>
      </div>

      {/* 面板网格布局 */}
      {dashboard.panels.length === 0 ? (
        <div style={{ textAlign: 'center', paddingTop: 80 }}>
          <Text type="secondary">该大屏暂无面板</Text>
        </div>
      ) : (
        <GridLayout
          className={`dashboard-grid-layout${editMode ? ' edit-mode' : ''}`}
          layout={gridLayout}
          width={gridWidth - 48}
          gridConfig={{
            cols: GRID_COLS,
            rowHeight: GRID_ROW_HEIGHT,
            margin: [16, 16] as const,
            containerPadding: [0, 0] as const,
          }}
          dragConfig={{ enabled: editMode, bounded: false, threshold: 3 }}
          resizeConfig={{ enabled: editMode, handles: ['se'] }}
          autoSize={true}
          onLayoutChange={handleLayoutChange}
        >
          {dashboard.panels.map((panel) => {
            const panelState = panelDataMap[panel.id]
            return (
              <div key={panel.id}>
                <DashboardPanel
                  panel={panel}
                  data={panelState?.data}
                  loading={panelState?.loading ?? true}
                  error={panelState?.error}
                  editable={editMode}
                  onRefresh={() => handlePanelRefresh(panel.id)}
                  onChartTypeChange={(type) => handleChartTypeChange(panel.id, type)}
                  onTitleChange={(title) => handleTitleChange(panel.id, title)}
                  onDelete={() => handleDeletePanel(panel.id)}
                />
              </div>
            )
          })}
        </GridLayout>
      )}

      {/* 退出编辑模式确认弹窗 */}
      <Modal
        title="退出编辑模式"
        open={exitModalOpen}
        onCancel={handleContinueEditing}
        footer={[
          <Button key="continue" onClick={handleContinueEditing}>
            继续编辑
          </Button>,
          <Button key="discard" danger onClick={handleDiscardChanges}>
            放弃修改
          </Button>,
          <Button key="save" type="primary" loading={saving} onClick={handleSaveChanges}>
            保存修改
          </Button>,
        ]}
      >
        <p>您有未保存的修改，请选择操作：</p>
      </Modal>
    </div>
  )
}

export default DashboardView
