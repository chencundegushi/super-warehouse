/**
 * 指标管理页面
 * 提供指标的列表展示、创建、编辑和删除功能。
 * 支持分页浏览，表单校验（名称≤64字符、描述≤512字符、参数≤20个）。
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  Select,
  Space,
  Popconfirm,
  message,
  Switch,
  Card,
  Typography,
} from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  MinusCircleOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { Metric, MetricParameter, MetricCreateInput, MetricUpdateInput } from '@/types'
import {
  listMetrics,
  createMetric,
  updateMetric,
  deleteMetric,
} from '@/services/metricApi'
import MetricSQLEditor from '@/components/MetricSQLEditor'

const { Title } = Typography
const { TextArea } = Input

/** 参数类型选项 */
const PARAM_TYPE_OPTIONS = [
  { label: 'String', value: 'string' },
  { label: 'Number', value: 'number' },
  { label: 'Date', value: 'date' },
  { label: 'Enum', value: 'enum' },
]

/** 默认分页大小 */
const DEFAULT_PAGE_SIZE = 10

/**
 * 指标管理页面组件
 * @returns 指标管理页面，包含列表、创建/编辑弹窗和删除确认
 */
function MetricsPage() {
  // 1. 列表状态
  const [metrics, setMetrics] = useState<Metric[]>([])
  const [total, setTotal] = useState(0)
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [loading, setLoading] = useState(false)

  // 2. 弹窗状态
  const [modalVisible, setModalVisible] = useState(false)
  const [editingMetric, setEditingMetric] = useState<Metric | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const [form] = Form.useForm()

  // 5. 监听表单中的指标名称和描述，用于传递给 MetricSQLEditor
  const watchedMetricName = Form.useWatch('name', form)
  const watchedMetricDescription = Form.useWatch('description', form)

  /**
   * 加载指标列表
   * @param page - 页码
   * @param size - 每页条数
   */
  const fetchMetrics = useCallback(async (page: number, size: number) => {
    console.log('[MetricsPage] Fetching metrics, page:', page, 'pageSize:', size)
    setLoading(true)
    try {
      const result = await listMetrics({ page, pageSize: size })
      setMetrics(result.items)
      setTotal(result.total)
    } catch (err) {
      console.error('[MetricsPage] Failed to fetch metrics:', err)
      message.error('加载指标列表失败')
    } finally {
      setLoading(false)
    }
  }, [])

  // 3. 初始加载
  useEffect(() => {
    fetchMetrics(currentPage, pageSize)
  }, [currentPage, pageSize, fetchMetrics])

  /**
   * 打开创建弹窗
   */
  const handleCreate = () => {
    console.log('[MetricsPage] Opening create modal')
    setEditingMetric(null)
    form.resetFields()
    form.setFieldsValue({ parameters: [] })
    setModalVisible(true)
  }

  /**
   * 打开编辑弹窗
   * @param metric - 待编辑的指标
   */
  const handleEdit = (metric: Metric) => {
    console.log('[MetricsPage] Opening edit modal, metricId:', metric.id)
    setEditingMetric(metric)
    form.setFieldsValue({
      name: metric.name,
      description: metric.description,
      sqlTemplate: metric.sqlTemplate,
      parameters: metric.parameters.map((p) => ({
        name: p.name,
        type: p.type,
        required: p.required,
        defaultValue: p.defaultValue ?? '',
      })),
    })
    setModalVisible(true)
  }

  /**
   * 删除指标
   * @param id - 指标 ID
   */
  const handleDelete = async (id: string) => {
    console.log('[MetricsPage] Deleting metric, id:', id)
    try {
      await deleteMetric(id)
      message.success('删除成功')
      fetchMetrics(currentPage, pageSize)
    } catch (err) {
      console.error('[MetricsPage] Failed to delete metric:', err)
      message.error('删除失败')
    }
  }

  /**
   * 提交创建/编辑表单
   */
  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      console.log('[MetricsPage] Form validated, submitting:', values.name)
      setSubmitting(true)

      // 构建参数列表
      const parameters: MetricParameter[] = (values.parameters || []).map(
        (p: { name: string; type: string; required: boolean; defaultValue?: string }) => ({
          name: p.name,
          type: p.type as MetricParameter['type'],
          required: p.required ?? false,
          defaultValue: p.defaultValue || undefined,
        })
      )

      if (editingMetric) {
        // 编辑模式
        const input: MetricUpdateInput = {
          name: values.name,
          description: values.description,
          sqlTemplate: values.sqlTemplate,
          parameters,
        }
        await updateMetric(editingMetric.id, input)
        message.success('更新成功')
      } else {
        // 创建模式
        const input: MetricCreateInput = {
          name: values.name,
          description: values.description,
          sqlTemplate: values.sqlTemplate,
          parameters,
        }
        await createMetric(input)
        message.success('创建成功')
      }

      setModalVisible(false)
      fetchMetrics(currentPage, pageSize)
    } catch (err) {
      // 表单校验失败不提示，API 错误提示
      if (err && typeof err === 'object' && 'errorFields' in err) {
        return
      }
      console.error('[MetricsPage] Submit failed:', err)
      message.error(editingMetric ? '更新失败' : '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  /**
   * 表格列定义
   */
  const columns: ColumnsType<Metric> = [
    {
      title: '指标名称',
      dataIndex: 'name',
      key: 'name',
      width: 200,
      ellipsis: true,
    },
    {
      title: '用途说明',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
    {
      title: '参数数量',
      key: 'paramCount',
      width: 100,
      align: 'center',
      render: (_: unknown, record: Metric) => record.parameters?.length ?? 0,
    },
    {
      title: '创建时间',
      dataIndex: 'createdAt',
      key: 'createdAt',
      width: 180,
      render: (val: string) => {
        if (!val) return '-'
        return new Date(val).toLocaleString('zh-CN')
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      render: (_: unknown, record: Metric) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除"
            description="删除后不可恢复，确认删除该指标？"
            onConfirm={() => handleDelete(record.id)}
            okText="确认"
            cancelText="取消"
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      {/* 页面标题和操作栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>指标管理</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
          创建指标
        </Button>
      </div>

      {/* 指标列表表格 */}
      <Card>
        <Table<Metric>
          columns={columns}
          dataSource={metrics}
          rowKey="id"
          loading={loading}
          pagination={{
            current: currentPage,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (page, size) => {
              setCurrentPage(page)
              setPageSize(size)
            },
          }}
        />
      </Card>

      {/* 创建/编辑弹窗 */}
      <Modal
        title={editingMetric ? '编辑指标' : '创建指标'}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        confirmLoading={submitting}
        width={720}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ parameters: [] }}
        >
          {/* 指标名称 */}
          <Form.Item
            name="name"
            label="指标名称"
            rules={[
              { required: true, message: '请输入指标名称' },
              { max: 64, message: '指标名称不超过64个字符' },
            ]}
          >
            <Input placeholder="请输入指标名称" maxLength={64} showCount />
          </Form.Item>

          {/* 用途说明 */}
          <Form.Item
            name="description"
            label="用途说明"
            rules={[
              { required: true, message: '请输入用途说明' },
              { max: 512, message: '用途说明不超过512个字符' },
            ]}
          >
            <TextArea
              placeholder="请输入指标用途说明"
              maxLength={512}
              showCount
              rows={3}
            />
          </Form.Item>

          {/* SQL 模板 - 使用 MetricSQLEditor 组件 */}
          <Form.Item
            name="sqlTemplate"
            label="SQL 模板"
            rules={[{ required: true, message: '请输入SQL模板' }]}
          >
            <MetricSQLEditor
              metricName={watchedMetricName}
              metricDescription={watchedMetricDescription}
            />
          </Form.Item>

          {/* 参数配置（动态列表） */}
          <Form.Item label="参数配置">
            <Form.List
              name="parameters"
              rules={[
                {
                  validator: async (_, params) => {
                    if (params && params.length > 20) {
                      return Promise.reject(new Error('参数数量不能超过20个'))
                    }
                  },
                },
              ]}
            >
              {(fields, { add, remove }, { errors }) => (
                <>
                  {fields.map(({ key, name, ...restField }) => (
                    <Space
                      key={key}
                      style={{ display: 'flex', marginBottom: 8 }}
                      align="baseline"
                    >

                      {/* 参数名称 */}
                      <Form.Item
                        {...restField}
                        name={[name, 'name']}
                        rules={[{ required: true, message: '请输入参数名' }]}
                      >
                        <Input placeholder="参数名" style={{ width: 120 }} />
                      </Form.Item>

                      {/* 参数类型 */}
                      <Form.Item
                        {...restField}
                        name={[name, 'type']}
                        rules={[{ required: true, message: '请选择类型' }]}
                      >
                        <Select
                          placeholder="类型"
                          options={PARAM_TYPE_OPTIONS}
                          style={{ width: 100 }}
                        />
                      </Form.Item>

                      {/* 是否必填 */}
                      <Form.Item
                        {...restField}
                        name={[name, 'required']}
                        valuePropName="checked"
                        initialValue={false}
                      >
                        <Switch checkedChildren="必填" unCheckedChildren="可选" />
                      </Form.Item>

                      {/* 默认值 */}
                      <Form.Item
                        {...restField}
                        name={[name, 'defaultValue']}
                      >
                        <Input placeholder="默认值" style={{ width: 120 }} />
                      </Form.Item>

                      {/* 删除按钮 */}
                      <MinusCircleOutlined onClick={() => remove(name)} />
                    </Space>
                  ))}

                  {/* 添加参数按钮 */}
                  <Form.Item>
                    <Button
                      type="dashed"
                      onClick={() => add()}
                      block
                      icon={<PlusOutlined />}
                      disabled={fields.length >= 20}
                    >
                      添加参数{fields.length > 0 ? ` (${fields.length}/20)` : ''}
                    </Button>
                  </Form.Item>
                  <Form.ErrorList errors={errors} />
                </>
              )}
            </Form.List>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default MetricsPage
