/**
 * 图表可视化组件
 * 集成 ECharts 5，支持柱状图、折线图、饼图三种图表类型。
 * 提供图表类型切换、交互操作（缩放、悬停提示、数据筛选）、
 * Agent 推荐图表类型默认选中、数据不兼容时的适配建议展示。
 *
 * @module ChartView
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Radio, Space, Typography, Empty } from 'antd'
import {
  BarChartOutlined,
  LineChartOutlined,
  PieChartOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import type {
  ChartRecommendation,
  ChartType,
  ColumnInfo,
  QueryResult,
} from '../types'

const { Text } = Typography

/**
 * ChartView 组件 Props
 * @param queryResult - 查询结果数据
 * @param recommendation - Agent 推荐的图表类型信息
 * @param userSpecifiedType - 用户在查询中明确指定的图表类型
 */
export interface ChartViewProps {
  queryResult: QueryResult
  recommendation?: ChartRecommendation
  userSpecifiedType?: ChartType
}

/**
 * 兼容性检查结果
 */
interface CompatibilityCheck {
  compatible: boolean
  warnings: string[]
}

// ============================================================
// 辅助函数
// ============================================================

/**
 * 检查数据与图表类型的兼容性
 * 饼图需要至少一个分类维度和一个数值度量
 * 折线图需要至少一个有序维度和一个数值度量
 * 柱状图需要至少一个分类维度和一个数值度量
 *
 * @param columns - 列信息数组
 * @param chartType - 目标图表类型
 * @returns 兼容性检查结果
 */
export function validateCompatibility(
  columns: ColumnInfo[],
  chartType: ChartType
): CompatibilityCheck {
  const numericCols = columns.filter((c) => c.isNumeric)
  const dateTimeCols = columns.filter((c) => c.isDateTime)
  const categoryCols = columns.filter((c) => !c.isNumeric && !c.isDateTime)
  const warnings: string[] = []

  if (chartType === 'pie') {
    // 饼图需要至少一个分类维度和一个数值度量
    if (categoryCols.length === 0 && dateTimeCols.length === 0) {
      warnings.push('饼图要求至少一个分类维度，当前数据缺少分类字段')
    }
    if (numericCols.length === 0) {
      warnings.push('饼图要求至少一个数值度量，当前数据缺少数值字段')
    }
  } else if (chartType === 'line') {
    // 折线图需要至少一个有序维度（时间或数值）和一个数值度量
    if (dateTimeCols.length === 0 && categoryCols.length === 0) {
      warnings.push('折线图要求至少一个有序维度（时间或分类），当前数据缺少有序字段')
    }
    if (numericCols.length === 0) {
      warnings.push('折线图要求至少一个数值度量，当前数据缺少数值字段')
    }
  } else if (chartType === 'bar') {
    // 柱状图需要至少一个分类维度和一个数值度量
    if (categoryCols.length === 0 && dateTimeCols.length === 0) {
      warnings.push('柱状图要求至少一个分类维度，当前数据缺少分类字段')
    }
    if (numericCols.length === 0) {
      warnings.push('柱状图要求至少一个数值度量，当前数据缺少数值字段')
    }
  }

  return {
    compatible: warnings.length === 0,
    warnings,
  }
}

/**
 * 生成柱状图 ECharts 配置
 * @param queryResult - 查询结果
 * @param columns - 列信息
 * @returns ECharts 配置对象
 */
function generateBarOption(queryResult: QueryResult, columns: ColumnInfo[]): EChartsOption {
  const categoryCol = columns.find((c) => !c.isNumeric) || columns[0]
  const numericCols = columns.filter((c) => c.isNumeric)
  const categoryIndex = columns.indexOf(categoryCol)

  // 提取分类轴数据
  const xData = queryResult.rows.map((row) => String(row[categoryIndex] ?? ''))

  // 构建系列数据
  const series = numericCols.map((col) => {
    const colIndex = columns.indexOf(col)
    return {
      name: col.name,
      type: 'bar' as const,
      data: queryResult.rows.map((row) => Number(row[colIndex]) || 0),
    }
  })

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
    },
    legend: {
      data: numericCols.map((c) => c.name),
      textStyle: { color: '#ccc' },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: xData,
      axisLabel: { color: '#ccc', rotate: xData.length > 10 ? 30 : 0 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#ccc' },
    },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', start: 0, end: 100 },
    ],
    series,
  }
}

/**
 * 生成折线图 ECharts 配置
 * @param queryResult - 查询结果
 * @param columns - 列信息
 * @returns ECharts 配置对象
 */
function generateLineOption(queryResult: QueryResult, columns: ColumnInfo[]): EChartsOption {
  // 优先使用时间列作为 X 轴，否则使用第一个非数值列
  const xCol = columns.find((c) => c.isDateTime)
    || columns.find((c) => !c.isNumeric)
    || columns[0]
  const numericCols = columns.filter((c) => c.isNumeric)
  const xIndex = columns.indexOf(xCol)

  const xData = queryResult.rows.map((row) => String(row[xIndex] ?? ''))

  const series = numericCols.map((col) => {
    const colIndex = columns.indexOf(col)
    return {
      name: col.name,
      type: 'line' as const,
      data: queryResult.rows.map((row) => Number(row[colIndex]) || 0),
      smooth: true,
    }
  })

  return {
    tooltip: {
      trigger: 'axis',
    },
    legend: {
      data: numericCols.map((c) => c.name),
      textStyle: { color: '#ccc' },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: xData,
      axisLabel: { color: '#ccc' },
      boundaryGap: false,
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#ccc' },
    },
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', start: 0, end: 100 },
    ],
    series,
  }
}

/**
 * 生成饼图 ECharts 配置
 * @param queryResult - 查询结果
 * @param columns - 列信息
 * @returns ECharts 配置对象
 */
function generatePieOption(queryResult: QueryResult, columns: ColumnInfo[]): EChartsOption {
  // 使用第一个非数值列作为名称，第一个数值列作为值
  const nameCol = columns.find((c) => !c.isNumeric) || columns[0]
  const valueCol = columns.find((c) => c.isNumeric) || columns[1] || columns[0]
  const nameIndex = columns.indexOf(nameCol)
  const valueIndex = columns.indexOf(valueCol)

  const data = queryResult.rows.map((row) => ({
    name: String(row[nameIndex] ?? ''),
    value: Number(row[valueIndex]) || 0,
  }))

  return {
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} ({d}%)',
    },
    legend: {
      orient: 'vertical',
      left: 'left',
      textStyle: { color: '#ccc' },
    },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 6,
          borderColor: '#1f1f1f',
          borderWidth: 2,
        },
        label: {
          show: true,
          color: '#ccc',
        },
        emphasis: {
          label: { show: true, fontSize: 14, fontWeight: 'bold' },
        },
        data,
      },
    ],
  }
}

/**
 * 根据图表类型生成对应的 ECharts 配置
 * @param queryResult - 查询结果
 * @param chartType - 图表类型
 * @returns ECharts 配置对象
 */
function generateChartOption(
  queryResult: QueryResult,
  chartType: ChartType
): EChartsOption {
  const { columns } = queryResult

  switch (chartType) {
    case 'bar':
      return generateBarOption(queryResult, columns)
    case 'line':
      return generateLineOption(queryResult, columns)
    case 'pie':
      return generatePieOption(queryResult, columns)
    default:
      return generateBarOption(queryResult, columns)
  }
}

// ============================================================
// 主组件
// ============================================================

/**
 * 图表可视化组件
 * 支持柱状图、折线图、饼图三种类型切换，集成 ECharts 5 交互能力。
 */
const ChartView: React.FC<ChartViewProps> = ({
  queryResult,
  recommendation,
  userSpecifiedType,
}) => {
  // 1.确定初始图表类型：用户指定 > Agent推荐 > 默认柱状图
  const initialType: ChartType = useMemo(() => {
    if (userSpecifiedType && userSpecifiedType !== 'table') {
      return userSpecifiedType
    }
    if (recommendation?.recommended && recommendation.recommended !== 'table') {
      return recommendation.recommended
    }
    return 'bar'
  }, [userSpecifiedType, recommendation])

  const [activeType, setActiveType] = useState<ChartType>(initialType)

  // 2.当推荐或用户指定类型变化时，同步更新当前选中类型
  useEffect(() => {
    setActiveType(initialType)
  }, [initialType])

  // 3.兼容性检查
  const compatibility = useMemo(
    () => validateCompatibility(queryResult.columns, activeType),
    [queryResult.columns, activeType]
  )

  // 4.生成 ECharts 配置
  const chartOption = useMemo(
    () => generateChartOption(queryResult, activeType),
    [queryResult, activeType]
  )

  /**
   * 处理图表类型切换
   * 切换后重新渲染图表（ECharts 内部处理，2秒内完成）
   */
  const handleTypeChange = useCallback((type: ChartType) => {
    console.log('[ChartView] Chart type switched to:', type)
    setActiveType(type)
  }, [])

  // 5.空数据状态处理
  if (queryResult.rowCount === 0 || queryResult.rows.length === 0) {
    return (
      <Empty
        description="当前查询无返回数据"
        style={{ padding: '40px 0' }}
      />
    )
  }

  return (
    <div style={{ width: '100%' }}>
      {/* 图表类型切换按钮组 */}
      <Space style={{ marginBottom: 12 }} align="center">
        <Text type="secondary" style={{ fontSize: 13 }}>图表类型：</Text>
        <Radio.Group
          value={activeType}
          onChange={(e) => handleTypeChange(e.target.value)}
          optionType="button"
          buttonStyle="solid"
          size="small"
        >
          <Radio.Button value="bar">
            <BarChartOutlined /> 柱状图
          </Radio.Button>
          <Radio.Button value="line">
            <LineChartOutlined /> 折线图
          </Radio.Button>
          <Radio.Button value="pie">
            <PieChartOutlined /> 饼图
          </Radio.Button>
        </Radio.Group>

        {/* 推荐标识 */}
        {recommendation && activeType === recommendation.recommended && (
          <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
            (推荐: {recommendation.reason})
          </Text>
        )}
      </Space>

      {/* 数据不兼容时的适配建议 */}
      {!compatibility.compatible && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="数据适配建议"
          description={
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {compatibility.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          }
        />
      )}

      {/* ECharts 图表渲染区域 */}
      <ReactECharts
        option={chartOption}
        style={{ height: 400, width: '100%' }}
        notMerge={true}
        lazyUpdate={true}
        theme="dark"
        opts={{ renderer: 'canvas' }}
      />
    </div>
  )
}

export default ChartView
