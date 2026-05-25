/**
 * 技能执行面板组件
 * 展示技能详细说明和所需参数，提供参数输入表单（根据参数类型动态渲染），
 * 支持参数校验、执行操作和结果展示（表格/图表形式）。
 *
 * @module SkillExecutionPanel
 */

import { useState, useMemo } from 'react'
import {
  Card,
  Form,
  Input,
  InputNumber,
  DatePicker,
  Select,
  Button,
  Typography,
  Alert,
  Spin,
  Table,
  Space,
  Divider,
  Segmented,
} from 'antd'
import {
  ThunderboltOutlined,
  CloseOutlined,
  TableOutlined,
  BarChartOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import type { Skill, SkillParameter, SkillExecutionResult, QueryResult, ChartType } from '@/types'
import { executeSkill } from '@/services/skillApi'

const { Paragraph, Text } = Typography

/** 结果展示模式 */
type DisplayMode = 'table' | 'chart'

/**
 * 根据查询结果数据推断合适的图表类型
 * 时间序列数据推荐折线图，分类数据推荐柱状图
 * @param data - 查询结果
 * @returns 推荐的图表类型
 */
function inferChartType(data: QueryResult): ChartType {
  // 1.检查是否包含时间序列列
  const hasDateTime = data.columns.some((col) => col.isDateTime)
  if (hasDateTime) {
    return 'line'
  }
  // 2.检查是否有数值列和分类列
  const hasNumeric = data.columns.some((col) => col.isNumeric)
  const hasCategory = data.columns.some((col) => !col.isNumeric && !col.isDateTime)
  if (hasCategory && hasNumeric) {
    return 'bar'
  }
  // 3.默认柱状图
  return 'bar'
}

/**
 * 根据查询结果和图表类型生成 ECharts 配置
 * @param data - 查询结果
 * @param chartType - 图表类型
 * @returns ECharts option 配置对象
 */
function buildChartOption(data: QueryResult, chartType: ChartType): Record<string, unknown> {
  console.log('[SkillExecutionPanel] Building chart option, type:', chartType, 'rows:', data.rowCount)

  // 1.找到分类列（第一个非数值列）和数值列
  const categoryColIndex = data.columns.findIndex((col) => !col.isNumeric && !col.isDateTime)
  const numericCols = data.columns
    .map((col, idx) => ({ col, idx }))
    .filter(({ col }) => col.isNumeric)

  // 2.如果没有合适的列，返回空配置
  if (categoryColIndex === -1 || numericCols.length === 0) {
    return {
      title: { text: '数据无法生成图表', left: 'center', textStyle: { color: '#ccc' } },
    }
  }

  // 3.提取分类数据
  const categories = data.rows.map((row) => String(row[categoryColIndex] ?? ''))

  // 4.根据图表类型生成配置
  if (chartType === 'pie') {
    // 饼图：使用第一个数值列
    const valueColIdx = numericCols[0].idx
    const pieData = data.rows.map((row) => ({
      name: String(row[categoryColIndex] ?? ''),
      value: Number(row[valueColIdx]) || 0,
    }))
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { type: 'scroll', bottom: 0, textStyle: { color: '#ccc' } },
      series: [
        {
          type: 'pie',
          radius: ['40%', '70%'],
          data: pieData,
          label: { color: '#ccc' },
        },
      ],
    }
  }

  // 5.柱状图/折线图
  const series = numericCols.map(({ col, idx }) => ({
    name: col.name,
    type: chartType === 'line' ? 'line' : 'bar',
    data: data.rows.map((row) => Number(row[idx]) || 0),
    smooth: chartType === 'line',
  }))

  return {
    tooltip: { trigger: 'axis' },
    legend: {
      data: numericCols.map(({ col }) => col.name),
      textStyle: { color: '#ccc' },
      bottom: 0,
    },
    grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
    xAxis: {
      type: 'category',
      data: categories,
      axisLabel: { color: '#ccc', rotate: categories.length > 10 ? 30 : 0 },
    },
    yAxis: { type: 'value', axisLabel: { color: '#ccc' } },
    series,
    dataZoom: data.rows.length > 20 ? [{ type: 'slider', bottom: '5%' }] : undefined,
  }
}

/**
 * SkillExecutionPanel 组件 Props
 * @param skill - 要执行的技能对象
 * @param onClose - 关闭面板回调（可选）
 */
export interface SkillExecutionPanelProps {
  skill: Skill
  onClose?: () => void
}

/**
 * 根据参数类型渲染对应的表单控件
 * @param param - 技能参数定义
 * @returns 对应的 Ant Design 表单控件
 */
function renderParameterInput(param: SkillParameter): React.ReactNode {
  // 1.根据参数类型选择对应控件
  switch (param.type) {
    case 'number':
      return <InputNumber style={{ width: '100%' }} placeholder={`请输入${param.name}`} />
    case 'date':
      return <DatePicker style={{ width: '100%' }} placeholder={`请选择${param.name}`} />
    case 'enum': {
      // 2.从 constraintDesc 解析枚举选项
      const options = parseEnumOptions(param.constraintDesc)
      return (
        <Select placeholder={`请选择${param.name}`} options={options} allowClear />
      )
    }
    case 'string':
    default:
      return <Input placeholder={`请输入${param.name}`} />
  }
}

/**
 * 解析枚举约束描述为 Select 选项
 * 支持逗号分隔或分号分隔的格式
 * @param constraintDesc - 约束描述字符串
 * @returns Select 组件的 options 数组
 */
function parseEnumOptions(constraintDesc?: string): Array<{ label: string; value: string }> {
  if (!constraintDesc) {
    return []
  }
  // 3.尝试用逗号或分号分隔
  const separator = constraintDesc.includes(';') ? ';' : ','
  return constraintDesc
    .split(separator)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => ({ label: item, value: item }))
}

/**
 * 根据参数定义构建表单校验规则
 * 支持必填校验、类型校验和约束校验
 * @param param - 技能参数定义
 * @returns Ant Design Form 校验规则数组
 */
function buildValidationRules(param: SkillParameter): Array<Record<string, unknown>> {
  const rules: Array<Record<string, unknown>> = []

  // 1.必填校验
  if (param.required) {
    rules.push({
      required: true,
      message: `请填写${param.name}`,
    })
  }

  // 2.类型特定校验
  switch (param.type) {
    case 'number':
      rules.push({
        type: 'number',
        message: `${param.name}必须为数字类型`,
      })
      break
    case 'date':
      rules.push({
        type: 'object',
        message: `${param.name}必须为有效日期`,
      })
      break
    case 'enum': {
      // 3.枚举值范围校验
      const options = parseEnumOptions(param.constraintDesc)
      if (options.length > 0) {
        const validValues = options.map((o) => o.value)
        rules.push({
          validator: (_: unknown, value: string) => {
            if (!value) return Promise.resolve()
            if (validValues.includes(value)) return Promise.resolve()
            return Promise.reject(new Error(`${param.name}的值必须是: ${validValues.join(', ')}`))
          },
        })
      }
      break
    }
    case 'string':
    default:
      rules.push({
        type: 'string',
        message: `${param.name}必须为字符串类型`,
      })
      break
  }

  return rules
}

/**
 * 技能执行面板组件
 * 展示技能详细说明、参数输入表单、执行按钮和结果展示区域。
 */
const SkillExecutionPanel: React.FC<SkillExecutionPanelProps> = ({ skill, onClose }) => {
  const [form] = Form.useForm()
  // 1.执行加载状态
  const [executing, setExecuting] = useState(false)
  // 2.执行结果
  const [result, setResult] = useState<SkillExecutionResult | null>(null)
  // 3.错误信息
  const [error, setError] = useState<string | null>(null)
  // 4.结果展示模式（表格/图表）
  const [displayMode, setDisplayMode] = useState<DisplayMode>('table')

  // 5.根据结果数据计算图表配置（缓存避免重复计算）
  const chartOption = useMemo(() => {
    if (!result?.hasData || !result.data) return null
    const chartType = inferChartType(result.data)
    return buildChartOption(result.data, chartType)
  }, [result])

  /**
   * 处理表单提交，执行技能
   * 校验参数后调用 API 执行技能
   */
  const handleExecute = async () => {
    try {
      // 4.校验表单参数
      const values = await form.validateFields()
      console.log('[SkillExecutionPanel] Executing skill, id:', skill.id, 'params:', values)

      setExecuting(true)
      setError(null)
      setResult(null)

      // 5.调用技能执行 API
      const execResult = await executeSkill(skill.id, values)
      console.log('[SkillExecutionPanel] Execution completed, success:', execResult.success)
      setResult(execResult)

      if (!execResult.success) {
        setError(String(execResult.output || '技能执行失败'))
      }
    } catch (err: unknown) {
      // 6.处理网络或校验错误
      if (err && typeof err === 'object' && 'errorFields' in err) {
        // 表单校验失败，不设置错误信息
        console.log('[SkillExecutionPanel] Form validation failed')
        return
      }
      const errorMsg = err instanceof Error ? err.message : '技能执行异常'
      console.error('[SkillExecutionPanel] Execution error:', errorMsg)
      setError(errorMsg)
    } finally {
      setExecuting(false)
    }
  }

  /**
   * 渲染查询结果表格
   * 将 QueryResult 数据转换为 Ant Design Table 格式
   */
  const renderDataTable = () => {
    if (!result?.hasData || !result.data) {
      return null
    }

    const { columns, rows } = result.data

    // 7.构建 Table columns 配置
    const tableColumns = columns.map((col, index) => ({
      title: col.name,
      dataIndex: `col_${index}`,
      key: col.name,
      ellipsis: true,
    }))

    // 8.构建 Table dataSource
    const dataSource = rows.map((row, rowIndex) => {
      const record: Record<string, unknown> = { key: rowIndex }
      row.forEach((cell, colIndex) => {
        record[`col_${colIndex}`] = cell
      })
      return record
    })

    return (
      <Table
        columns={tableColumns}
        dataSource={dataSource}
        size="small"
        scroll={{ x: 'max-content', y: 400 }}
        pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
        style={{ marginTop: 12 }}
      />
    )
  }

  /**
   * 渲染执行结果区域
   * 根据结果类型展示文本输出，并支持表格/图表切换展示数据
   */
  const renderResult = () => {
    if (!result) {
      return null
    }

    // 9.判断是否有可展示的数据
    const hasData = result.hasData && result.data && result.data.rows.length > 0

    return (
      <div style={{ marginTop: 16 }}>
        <Divider orientation="left">执行结果</Divider>
        {/* 10.展示执行耗时 */}
        <Text type="secondary" style={{ fontSize: 12 }}>
          执行耗时: {result.executionTime}ms
        </Text>

        {/* 11.展示文本输出 */}
        {result.output != null && !hasData && (
          <Paragraph style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>
            {typeof result.output === 'string' ? result.output : JSON.stringify(result.output, null, 2)}
          </Paragraph>
        )}

        {/* 12.数据展示模式切换 */}
        {hasData && (
          <>
            <div style={{ marginTop: 12, marginBottom: 12 }}>
              <Segmented
                value={displayMode}
                onChange={(val) => setDisplayMode(val as DisplayMode)}
                options={[
                  { label: '表格', value: 'table', icon: <TableOutlined /> },
                  { label: '图表', value: 'chart', icon: <BarChartOutlined /> },
                ]}
              />
            </div>

            {/* 13.表格模式 */}
            {displayMode === 'table' && renderDataTable()}

            {/* 14.图表模式 */}
            {displayMode === 'chart' && chartOption && (
              <ReactECharts
                option={chartOption}
                style={{ height: 360, marginTop: 12 }}
                theme="dark"
                opts={{ renderer: 'canvas' }}
              />
            )}

            {/* 15.图表模式但无法生成图表时的提示 */}
            {displayMode === 'chart' && !chartOption && (
              <Alert
                type="info"
                message="当前数据无法生成图表，请切换到表格模式查看"
                style={{ marginTop: 12 }}
              />
            )}
          </>
        )}
      </div>
    )
  }

  return (
    <Card
      title={
        <Space>
          <ThunderboltOutlined />
          <span>{skill.name}</span>
        </Space>
      }
      extra={onClose && <Button type="text" icon={<CloseOutlined />} onClick={onClose} />}
      style={{ width: '100%' }}
    >
      {/* 15.技能描述 */}
      {skill.description && (
        <Paragraph type="secondary" style={{ marginBottom: 16 }}>
          {skill.description}
        </Paragraph>
      )}

      {/* 16.参数输入表单 */}
      {skill.parameters.length > 0 && (
        <Form
          form={form}
          layout="vertical"
          requiredMark
          style={{ marginBottom: 16 }}
        >
          {skill.parameters
            .sort((a, b) => a.sortOrder - b.sortOrder)
            .map((param) => (
              <Form.Item
                key={param.id}
                name={param.name}
                label={param.name}
                tooltip={param.constraintDesc}
                rules={buildValidationRules(param)}
              >
                {renderParameterInput(param)}
              </Form.Item>
            ))}
        </Form>
      )}

      {/* 17.执行按钮 */}
      <Button
        type="primary"
        icon={<ThunderboltOutlined />}
        onClick={handleExecute}
        loading={executing}
        block
      >
        执行
      </Button>

      {/* 18.加载状态 */}
      {executing && (
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Spin tip="正在执行技能..." />
        </div>
      )}

      {/* 19.错误提示 */}
      {error && (
        <Alert
          type="error"
          message="执行失败"
          description={error}
          showIcon
          closable
          onClose={() => setError(null)}
          style={{ marginTop: 16 }}
        />
      )}

      {/* 20.执行结果展示 */}
      {renderResult()}
    </Card>
  )
}

export default SkillExecutionPanel
