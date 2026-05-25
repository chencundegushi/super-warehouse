/**
 * DDL管理页面
 * 提供数据库表结构（DDL）的列表展示、加载、刷新和缓存清理功能。
 * 支持选择数据库和表名进行加载，手动刷新已加载的DDL，以及清除单条缓存。
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  Space,
  Popconfirm,
  message,
  Tag,
  Typography,
} from 'antd'
import {
  PlusOutlined,
  ReloadOutlined,
  DeleteOutlined,
  DatabaseOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { DDLInfo, DDLLoadParams } from '@/types'
import { loadDDL, refreshDDL, listDDL, clearCache } from '@/services/ddlApi'

const { Title } = Typography

/**
 * DDL管理页面组件
 * @returns DDL管理页面，包含已加载表结构列表、加载弹窗、刷新和清除缓存操作
 */
function DDLPage() {
  // 1. 列表状态
  const [ddlList, setDdlList] = useState<DDLInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  // 2. 加载弹窗状态
  const [modalVisible, setModalVisible] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const [form] = Form.useForm()

  /**
   * 获取已加载的DDL列表
   */
  const fetchDDLList = useCallback(async () => {
    console.log('[DDLPage] Fetching DDL list')
    setLoading(true)
    try {
      const result = await listDDL()
      setDdlList(result)
    } catch (err) {
      console.error('[DDLPage] Failed to fetch DDL list:', err)
      message.error('加载DDL列表失败')
    } finally {
      setLoading(false)
    }
  }, [])

  // 3. 页面挂载时加载列表
  useEffect(() => {
    fetchDDLList()
  }, [fetchDDLList])

  /**
   * 处理加载DDL操作
   * 从表单获取数据库名和表名列表，调用加载接口
   */
  const handleLoadDDL = async () => {
    console.log('[DDLPage] Handling load DDL submit')
    try {
      const values = await form.validateFields()
      setSubmitting(true)

      // 1.解析表名列表（逗号分隔）
      const params: DDLLoadParams = {
        database: values.database.trim(),
      }
      if (values.tables && values.tables.trim()) {
        params.tables = values.tables
          .split(',')
          .map((t: string) => t.trim())
          .filter((t: string) => t.length > 0)
      }

      console.log('[DDLPage] Loading DDL with params:', params)
      await loadDDL(params)
      message.success('DDL加载成功')
      setModalVisible(false)
      form.resetFields()
      // 2.刷新列表
      fetchDDLList()
    } catch (err) {
      console.error('[DDLPage] Failed to load DDL:', err)
      message.error('DDL加载失败，请检查数据库连接和参数')
    } finally {
      setSubmitting(false)
    }
  }

  /**
   * 处理刷新全部DDL操作
   * 重新从Doris获取所有已加载表的最新DDL
   */
  const handleRefreshAll = async () => {
    console.log('[DDLPage] Refreshing all DDL')
    setRefreshing(true)
    try {
      await refreshDDL()
      message.success('DDL刷新成功')
      fetchDDLList()
    } catch (err) {
      console.error('[DDLPage] Failed to refresh DDL:', err)
      message.error('DDL刷新失败，请检查数据库连接')
    } finally {
      setRefreshing(false)
    }
  }

  /**
   * 处理清除单条DDL缓存
   * @param record - 要清除缓存的DDL记录
   */
  const handleClearCache = async (record: DDLInfo) => {
    console.log('[DDLPage] Clearing cache for:', record.database, record.tableName)
    try {
      await clearCache(record.database, record.tableName)
      message.success(`已清除 ${record.database}.${record.tableName} 的缓存`)
      fetchDDLList()
    } catch (err) {
      console.error('[DDLPage] Failed to clear cache:', err)
      message.error('清除缓存失败')
    }
  }

  /** 表格列定义 */
  const columns: ColumnsType<DDLInfo> = [
    {
      title: '数据库',
      dataIndex: 'database',
      key: 'database',
      render: (text: string) => <Tag color="blue">{text}</Tag>,
    },
    {
      title: '表名',
      dataIndex: 'tableName',
      key: 'tableName',
    },
    {
      title: '字段数量',
      dataIndex: 'fieldCount',
      key: 'fieldCount',
      width: 100,
      align: 'center',
    },
    {
      title: '最近加载时间',
      dataIndex: 'loadedAt',
      key: 'loadedAt',
      width: 200,
      render: (text: string) => {
        if (!text) return '-'
        return new Date(text).toLocaleString('zh-CN')
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: unknown, record: DDLInfo) => (
        <Popconfirm
          title="确认清除缓存"
          description={`确定要清除 ${record.database}.${record.tableName} 的缓存吗？`}
          onConfirm={() => handleClearCache(record)}
          okText="确认"
          cancelText="取消"
        >
          <Button type="link" danger icon={<DeleteOutlined />} size="small">
            清除缓存
          </Button>
        </Popconfirm>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      {/* 页面标题和操作按钮 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          <DatabaseOutlined style={{ marginRight: 8 }} />
          DDL管理
        </Title>
        <Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={handleRefreshAll}
            loading={refreshing}
          >
            刷新全部
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setModalVisible(true)}
          >
            加载DDL
          </Button>
        </Space>
      </div>

      {/* 已加载DDL列表 */}
      <Table<DDLInfo>
        columns={columns}
        dataSource={ddlList}
        rowKey="id"
        loading={loading}
        scroll={{ y: 'calc(100vh - 260px)' }}
        pagination={{
          pageSize: 20,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 张表`,
        }}
        locale={{ emptyText: '暂无已加载的DDL，请点击"加载DDL"按钮添加' }}
      />

      {/* 加载DDL弹窗 */}
      <Modal
        title="加载DDL"
        open={modalVisible}
        onOk={handleLoadDDL}
        onCancel={() => {
          setModalVisible(false)
          form.resetFields()
        }}
        confirmLoading={submitting}
        okText="加载"
        cancelText="取消"
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          autoComplete="off"
        >
          <Form.Item
            name="database"
            label="数据库名"
            rules={[{ required: true, message: '请输入数据库名' }]}
          >
            <Input placeholder="请输入Doris数据库名称" />
          </Form.Item>
          <Form.Item
            name="tables"
            label="表名（可选）"
            extra="多个表名用逗号分隔，留空则加载整个数据库的所有表"
          >
            <Input placeholder="例如: table1, table2, table3" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default DDLPage
