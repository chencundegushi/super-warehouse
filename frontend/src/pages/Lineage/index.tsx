/**
 * 表血缘关系页面
 * 展示 Doris 数仓表的层级关系和 ETL 调度周期。
 * 使用 ECharts 有向图按层级分列展示，节点从左到右按 ODS→DWS→ADS 排列。
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import { Button, Space, Spin, message, Tag, Card, Empty, Tooltip, Collapse } from 'antd'
import {
  ReloadOutlined,
  ApartmentOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react'
import type { LineageData, LineageEdge, TableInfo } from '@/services/lineageApi'
import { analyzeLineage, getCachedLineage } from '@/services/lineageApi'

/** 层级颜色映射 */
const LAYER_COLORS: Record<string, string> = {
  ODS: '#52c41a',
  DWD: '#1890ff',
  DWS: '#722ed1',
  ADS: '#fa541c',
  DIM: '#faad14',
  OTHER: '#8c8c8c',
}

/** 层级描述映射 */
const LAYER_DESCRIPTIONS: Record<string, string> = {
  ODS: '原始数据层',
  DWD: '明细数据层',
  DWS: '汇总数据层',
  ADS: '应用数据层',
  DIM: '维度表',
  OTHER: '其他',
}

/**
 * 表血缘关系页面组件
 * @returns 包含层级图表和表详情的页面
 */
function LineagePage() {
  // 1.状态管理
  const [lineageData, setLineageData] = useState<LineageData | null>(null)
  const [loading, setLoading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)

  /**
   * 加载缓存的血缘数据
   */
  const loadCachedData = useCallback(async () => {
    console.log('[LineagePage] Loading cached lineage data')
    setLoading(true)
    try {
      const data = await getCachedLineage()
      if (data.layers.length > 0 || data.edges.length > 0) {
        setLineageData(data)
      }
    } catch (err) {
      console.error('[LineagePage] Failed to load cached data:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  /**
   * 触发血缘分析（调用 LLM）
   */
  const handleAnalyze = useCallback(async (forceRefresh = false) => {
    console.log('[LineagePage] Starting lineage analysis, forceRefresh:', forceRefresh)
    setAnalyzing(true)
    try {
      const data = await analyzeLineage(forceRefresh)
      setLineageData(data)
      message.success('血缘分析完成')
    } catch (err) {
      console.error('[LineagePage] Lineage analysis failed:', err)
      message.error('血缘分析失败，请检查 Doris 连接和 LLM 配置')
    } finally {
      setAnalyzing(false)
    }
  }, [])

  // 2.页面挂载时加载缓存数据
  useEffect(() => {
    loadCachedData()
  }, [loadCachedData])

  /**
   * 构建 ECharts Graph 图表配置
   * 使用分层横向布局：每层一列，节点垂直均匀分布
   */
  const chartOption = useMemo(() => {
    if (!lineageData || lineageData.tables.length === 0) return null

    const { tables, edges, layers } = lineageData

    // 1.按层级分组表
    const layerGroups: Record<string, TableInfo[]> = {}
    tables.forEach((table) => {
      const layer = table.layer || 'OTHER'
      if (!layerGroups[layer]) layerGroups[layer] = []
      layerGroups[layer].push(table)
    })

    // 2.确定层级顺序（从左到右）
    const defaultOrder = ['ODS', 'DIM', 'DWD', 'DWS', 'ADS', 'OTHER']
    const sortedLayers = layers.length > 0
      ? layers.sort((a, b) => a.level - b.level).map((l) => l.name)
      : defaultOrder.filter((l) => layerGroups[l])

    // 3.构建分类
    const categoryMap: Record<string, number> = {}
    const categories = sortedLayers.map((layer, idx) => {
      categoryMap[layer] = idx
      return { name: `${layer} - ${LAYER_DESCRIPTIONS[layer] || layer}` }
    })

    // 4.计算布局参数 - 使用像素坐标
    // ECharts graph layout:'none' 下 x/y 为像素值
    const chartWidth = 1100
    const chartPadding = 60
    const totalLayers = sortedLayers.length

    // 每层水平位置：均匀分布
    const getLayerX = (layerIdx: number) => {
      if (totalLayers <= 1) return chartWidth / 2
      return chartPadding + (layerIdx / (totalLayers - 1)) * (chartWidth - chartPadding * 2)
    }

    // 找出节点最多的层，用于计算垂直间距
    const maxNodesInLayer = Math.max(...sortedLayers.map((l) => (layerGroups[l] || []).length), 1)
    const chartContentHeight = Math.max(400, maxNodesInLayer * 50)

    // 5.构建节点，按层级分列、垂直均匀分布
    const nodes: Array<{
      name: string
      x: number
      y: number
      symbolSize: number
      itemStyle: { color: string; borderColor: string; borderWidth: number }
      category: number
      label: { show: boolean; formatter: string; position: string; color: string; fontSize: number }
    }> = []

    sortedLayers.forEach((layer, layerIdx) => {
      const layerTables = layerGroups[layer] || []
      const count = layerTables.length
      const x = getLayerX(layerIdx)

      layerTables.forEach((table, tableIdx) => {
        // 垂直均匀分布
        const y = count <= 1
          ? chartContentHeight / 2
          : 30 + (tableIdx / (count - 1)) * (chartContentHeight - 60)
        nodes.push({
          name: table.name,
          x,
          y,
          symbolSize: 28,
          itemStyle: {
            color: LAYER_COLORS[layer] || LAYER_COLORS.OTHER,
            borderColor: '#fff',
            borderWidth: 1,
          },
          category: categoryMap[layer] ?? 0,
          label: {
            show: true,
            formatter: table.name.length > 25 ? table.name.substring(0, 25) + '...' : table.name,
            position: 'right',
            color: '#e0e0e0',
            fontSize: 11,
          },
        })
      })
    })

    // 6.构建边（links）- 只保留存在的节点之间的边，标注调度频率
    const nodeNames = new Set(nodes.map((n) => n.name))
    const links = edges
      .filter((edge: LineageEdge) => nodeNames.has(edge.source) && nodeNames.has(edge.target))
      .map((edge: LineageEdge) => ({
        source: edge.source,
        target: edge.target,
        lineStyle: {
          color: '#666',
          width: 1.5,
          curveness: 0.15,
          opacity: 0.7,
        },
        label: {
          show: true,
          formatter: edge.schedule || '',
          fontSize: 10,
          color: '#faad14',
          backgroundColor: '#1f1f1f',
          padding: [2, 4],
          borderRadius: 2,
        },
      }))

    // 7.构建层级标注（使用 graphic 组件在每列顶部标注层名）
    const graphicElements = sortedLayers.map((layer, idx) => ({
      type: 'text' as const,
      left: getLayerX(idx) + 30,
      top: 10,
      style: {
        text: `${layer}\n${LAYER_DESCRIPTIONS[layer] || ''}`,
        fill: LAYER_COLORS[layer] || '#999',
        fontSize: 13,
        fontWeight: 'bold' as const,
        textAlign: 'center' as const,
      },
    }))

    // 8.返回 ECharts 配置
    return {
      tooltip: {
        trigger: 'item',
        backgroundColor: '#1f1f1f',
        borderColor: '#424242',
        textStyle: { color: '#e0e0e0' },
        formatter: (params: { dataType: string; data: { name: string }; name: string }) => {
          if (params.dataType === 'node') {
            const table = tables.find((t) => t.name === params.data.name)
            if (table) {
              return `<b>${table.name}</b><br/>层级: ${table.layer}<br/>描述: ${table.description || '-'}`
            }
            return params.data.name
          }
          if (params.dataType === 'edge') {
            const edge = edges.find(
              (e: LineageEdge) => params.name.includes(e.source) && params.name.includes(e.target)
            )
            if (edge) {
              return `<b>${edge.source} → ${edge.target}</b><br/>Job: ${edge.job_name}<br/>调度: ${edge.schedule}`
            }
          }
          return ''
        },
      },

      legend: {
        data: categories.map((c) => c.name),
        orient: 'horizontal',
        bottom: 10,
        textStyle: { color: '#ccc', fontSize: 11 },
        itemWidth: 14,
        itemHeight: 14,
      },
      graphic: graphicElements,
      grid: { left: 80, right: 80, top: 60, bottom: 60 },
      animationDuration: 800,
      animationEasingUpdate: 'cubicOut',
      series: [
        {
          type: 'graph',
          layout: 'none',
          coordinateSystem: undefined,
          data: nodes,
          links,
          categories,
          roam: true,
          zoom: 1,
          scaleLimit: { min: 0.3, max: 3 },
          label: {
            show: true,
            position: 'right',
            fontSize: 11,
            color: '#e0e0e0',
            distance: 8,
          },
          lineStyle: {
            color: '#555',
            width: 1.5,
            opacity: 0.7,
          },
          edgeSymbol: ['none', 'arrow'],
          edgeSymbolSize: [4, 8],
          emphasis: {
            focus: 'adjacency',
            itemStyle: { borderWidth: 3, borderColor: '#fff' },
            lineStyle: { width: 3, opacity: 1 },
            label: { fontSize: 13, fontWeight: 'bold' },
          },
        },
      ],
    }
  }, [lineageData])

  // 3.渲染层级标签
  const renderLayerTags = () => {
    if (!lineageData) return null
    return (
      <Space wrap style={{ marginBottom: 16 }}>
        {Object.entries(LAYER_COLORS).map(([layer, color]) => {
          const count = lineageData.tables.filter((t) => t.layer === layer).length
          if (count === 0) return null
          return (
            <Tag key={layer} color={color}>
              {layer} ({LAYER_DESCRIPTIONS[layer]}) - {count}张表
            </Tag>
          )
        })}
      </Space>
    )
  }

  // 4.渲染调度信息列表（使用 Collapse 默认收起）
  const renderScheduleList = () => {
    if (!lineageData || lineageData.edges.length === 0) return null
    return (
      <Collapse
        style={{ marginTop: 12 }}
        items={[
          {
            key: 'etl-schedule',
            label: (
              <Space>
                <ClockCircleOutlined />
                <span>ETL 调度周期（{lineageData.edges.length} 条）</span>
              </Space>
            ),
            children: (
              <div style={{ maxHeight: 400, overflow: 'auto' }}>
                <div style={{ display: 'grid', gap: 8 }}>
                  {lineageData.edges.map((edge, idx) => (
                    <div
                      key={idx}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        padding: '4px 8px',
                        background: '#2a2a2a',
                        borderRadius: 4,
                        fontSize: 12,
                        flexWrap: 'wrap',
                      }}
                    >
                      <Tag color={LAYER_COLORS[lineageData.tables.find((t) => t.name === edge.source)?.layer || 'OTHER']}>
                        {edge.source}
                      </Tag>
                      <span style={{ color: '#666' }}>→</span>
                      <Tag color={LAYER_COLORS[lineageData.tables.find((t) => t.name === edge.target)?.layer || 'OTHER']}>
                        {edge.target}
                      </Tag>
                      <Tooltip title={`Job: ${edge.job_name}`}>
                        <Tag color="blue" icon={<ClockCircleOutlined />}>
                          {edge.schedule || '未知'}
                        </Tag>
                      </Tooltip>
                    </div>
                  ))}
                </div>
              </div>
            ),
          },
        ]}
      />
    )
  }

  return (
    <div style={{ padding: '16px 24px', height: '100%', overflow: 'auto' }}>
      {/* 页面标题和操作按钮 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Space>
          <ApartmentOutlined style={{ fontSize: 20, color: '#1890ff' }} />
          <h2 style={{ margin: 0, color: '#fff' }}>表血缘关系</h2>
        </Space>
        <Space>
          <Button
            type="primary"
            icon={<ApartmentOutlined />}
            loading={analyzing}
            onClick={() => handleAnalyze(false)}
          >
            分析血缘
          </Button>
          <Button
            icon={<ReloadOutlined />}
            loading={analyzing}
            onClick={() => handleAnalyze(true)}
          >
            强制刷新
          </Button>
        </Space>
      </div>

      {/* 层级标签 */}
      <div>{renderLayerTags()}</div>

      {/* 图表区域 */}
      <div>
        <Spin spinning={loading || analyzing} tip={analyzing ? '正在分析血缘关系...' : '加载中...'}>
          {chartOption ? (
            <Card styles={{ body: { padding: 8 } }}>
              <ReactEChartsCore
                option={chartOption}
                style={{ height: 550, width: '100%' }}
                opts={{ renderer: 'canvas' }}
              />
            </Card>
          ) : (
            <Card>
              <Empty
                description="暂无血缘数据，请点击「分析血缘」按钮开始分析"
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            </Card>
          )}
        </Spin>

        {/* 调度信息 */}
        {renderScheduleList()}
      </div>
    </div>
  )
}

export default LineagePage
