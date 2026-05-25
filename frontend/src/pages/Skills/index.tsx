/**
 * 技能管理页面
 * 提供技能列表展示、导入、编辑、导出、删除等完整管理功能。
 * 支持 .md/.txt 格式文件上传，单个文件不超过 1MB。
 *
 * @module SkillsPage
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Card,
  List,
  Button,
  Upload,
  Modal,
  Input,
  Popconfirm,
  message,
  Space,
  Typography,
  Empty,
  Spin,
} from 'antd'
import {
  ThunderboltOutlined,
  UploadOutlined,
  EditOutlined,
  ExportOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons'
import type { UploadProps } from 'antd'
import type { Skill, SkillListItem } from '@/types'
import {
  listSkills,
  importSkill,
  updateSkill,
  deleteSkill,
  exportSkill,
  getSkill,
} from '@/services/skillApi'
import SkillExecutionPanel from '@/components/SkillExecutionPanel'

const { Title } = Typography
const { TextArea } = Input

/** 文件大小上限：1MB */
const MAX_FILE_SIZE = 1 * 1024 * 1024

/**
 * 技能管理页面组件
 * 实现技能列表展示、导入、编辑、导出、删除操作
 */
function SkillsPage() {
  // 1.技能列表数据
  const [skills, setSkills] = useState<SkillListItem[]>([])
  // 2.加载状态
  const [loading, setLoading] = useState(false)
  // 3.编辑弹窗可见性
  const [editModalVisible, setEditModalVisible] = useState(false)
  // 4.当前编辑的技能
  const [editingSkill, setEditingSkill] = useState<SkillListItem | null>(null)
  // 5.编辑表单字段
  const [editName, setEditName] = useState('')
  const [editDescription, setEditDescription] = useState('')
  // 6.当前选中执行的技能（需要完整信息）
  const [executingSkill, setExecutingSkill] = useState<Skill | null>(null)

  /**
   * 加载技能列表
   * 调用后端接口获取所有已导入的技能
   */
  const fetchSkills = useCallback(async () => {
    console.log('[SkillsPage] Fetching skills list')
    setLoading(true)
    try {
      const data = await listSkills()
      setSkills(data)
      console.log('[SkillsPage] Skills loaded, count:', data.length)
    } catch (err) {
      console.error('[SkillsPage] Failed to fetch skills:', err)
      message.error('加载技能列表失败')
    } finally {
      setLoading(false)
    }
  }, [])

  // 6.页面挂载时加载技能列表
  useEffect(() => {
    fetchSkills()
  }, [fetchSkills])

  /**
   * 处理文件上传前的校验
   * 检查文件大小是否超过 1MB 限制
   *
   * @param file - 待上传的文件
   * @returns false 阻止默认上传行为，手动处理
   */
  const handleBeforeUpload: UploadProps['beforeUpload'] = (file) => {
    console.log('[SkillsPage] Upload file check, name:', file.name, 'size:', file.size)
    // 1.校验文件大小
    if (file.size > MAX_FILE_SIZE) {
      message.error('文件大小不能超过 1MB')
      return Upload.LIST_IGNORE
    }
    // 2.读取文件内容并调用导入接口
    handleImportFile(file)
    return false
  }

  /**
   * 读取文件内容并调用导入接口
   * 使用 FileReader 读取文件文本内容，然后调用 skillApi.importSkill
   *
   * @param file - 用户选择的文件对象
   */
  const handleImportFile = async (file: File) => {
    console.log('[SkillsPage] Importing skill file:', file.name)
    try {
      const content = await readFileContent(file)
      // 1.提取文件名（去掉扩展名）作为技能名称
      const name = file.name.replace(/\.(md|txt)$/i, '')
      await importSkill({ name, content, format: 'claude-skill' })
      message.success('技能导入成功')
      // 2.刷新列表
      fetchSkills()
    } catch (err) {
      console.error('[SkillsPage] Import skill failed:', err)
      message.error('技能导入失败')
    }
  }

  /**
   * 读取文件文本内容
   * @param file - 文件对象
   * @returns 文件文本内容
   */
  const readFileContent = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result as string)
      reader.onerror = () => reject(new Error('文件读取失败'))
      reader.readAsText(file)
    })
  }

  /**
   * 打开编辑弹窗
   * @param skill - 要编辑的技能
   */
  const handleEdit = (skill: SkillListItem) => {
    console.log('[SkillsPage] Opening edit modal, skill:', skill.name)
    setEditingSkill(skill)
    setEditName(skill.name)
    setEditDescription(skill.description || '')
    setEditModalVisible(true)
  }

  /**
   * 提交编辑表单
   * 调用 updateSkill 接口保存修改
   */
  const handleEditSubmit = async () => {
    if (!editingSkill) return
    console.log('[SkillsPage] Submitting edit, skill id:', editingSkill.id)
    try {
      await updateSkill(editingSkill.id, {
        name: editName,
        description: editDescription,
      })
      message.success('技能更新成功')
      setEditModalVisible(false)
      setEditingSkill(null)
      // 1.刷新列表
      fetchSkills()
    } catch (err) {
      console.error('[SkillsPage] Update skill failed:', err)
      message.error('技能更新失败')
    }
  }

  /**
   * 导出技能
   * 调用 exportSkill 接口获取文件内容，触发浏览器下载
   *
   * @param skill - 要导出的技能
   */
  const handleExport = async (skill: SkillListItem) => {
    console.log('[SkillsPage] Exporting skill:', skill.name)
    try {
      const fileData = await exportSkill(skill.id)
      // 1.创建 Blob 并触发下载
      const blob = new Blob([fileData.content], { type: 'text/plain;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${fileData.name}.md`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
      message.success('技能导出成功')
    } catch (err) {
      console.error('[SkillsPage] Export skill failed:', err)
      message.error('技能导出失败')
    }
  }

  /**
   * 删除技能
   * 调用 deleteSkill 接口删除指定技能
   *
   * @param skill - 要删除的技能
   */
  const handleDelete = async (skill: SkillListItem) => {
    console.log('[SkillsPage] Deleting skill:', skill.name)
    try {
      await deleteSkill(skill.id)
      message.success('技能删除成功')
      // 1.刷新列表
      fetchSkills()
    } catch (err) {
      console.error('[SkillsPage] Delete skill failed:', err)
      message.error('技能删除失败')
    }
  }

  return (
    <div style={{ padding: 24 }}>
      {/* 页面标题和导入按钮 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>
          <ThunderboltOutlined style={{ marginRight: 8 }} />
          技能管理
        </Title>
        <Upload
          accept=".md,.txt"
          showUploadList={false}
          beforeUpload={handleBeforeUpload}
        >
          <Button type="primary" icon={<UploadOutlined />}>
            导入技能
          </Button>
        </Upload>
      </div>

      {/* 技能列表 */}
      <Spin spinning={loading}>
        {skills.length === 0 && !loading ? (
          <Empty description="暂无技能，请点击「导入技能」添加" />
        ) : (
          <List
            grid={{ gutter: 16, xs: 1, sm: 1, md: 2, lg: 3, xl: 3, xxl: 4 }}
            dataSource={skills}
            renderItem={(skill) => (
              <List.Item>
                <Card
                  title={skill.name}
                  hoverable
                  actions={[
                    <PlayCircleOutlined key="execute" onClick={async () => {
                      console.log('[SkillsPage] Opening execution panel, skill:', skill.name)
                      try {
                        // 获取完整技能信息（含 content 和 parameters）
                        const fullSkill = await getSkill(skill.id)
                        setExecutingSkill(fullSkill)
                      } catch (err) {
                        console.error('[SkillsPage] Failed to get skill details:', err)
                        message.error('获取技能详情失败')
                      }
                    }} />,
                    <EditOutlined key="edit" onClick={() => handleEdit(skill)} />,
                    <ExportOutlined key="export" onClick={() => handleExport(skill)} />,
                    <Popconfirm
                      key="delete"
                      title="确认删除"
                      description={`确定要删除技能「${skill.name}」吗？`}
                      onConfirm={() => handleDelete(skill)}
                      okText="确认"
                      cancelText="取消"
                    >
                      <DeleteOutlined />
                    </Popconfirm>,
                  ]}
                >
                  <Card.Meta
                    description={skill.description || '暂无描述'}
                  />
                </Card>
              </List.Item>
            )}
          />
        )}
      </Spin>

      {/* 编辑弹窗 */}
      <Modal
        title="编辑技能"
        open={editModalVisible}
        onOk={handleEditSubmit}
        onCancel={() => {
          setEditModalVisible(false)
          setEditingSkill(null)
        }}
        okText="保存"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <div style={{ marginBottom: 4 }}>技能名称</div>
            <Input
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              placeholder="请输入技能名称"
              maxLength={128}
            />
          </div>
          <div>
            <div style={{ marginBottom: 4 }}>技能描述</div>
            <TextArea
              value={editDescription}
              onChange={(e) => setEditDescription(e.target.value)}
              placeholder="请输入技能描述"
              rows={4}
            />
          </div>
        </Space>
      </Modal>

      {/* 技能执行面板弹窗 */}
      <Modal
        title={null}
        open={!!executingSkill}
        onCancel={() => setExecutingSkill(null)}
        footer={null}
        width={720}
        destroyOnClose
      >
        {executingSkill && (
          <SkillExecutionPanel
            skill={executingSkill}
            onClose={() => setExecutingSkill(null)}
          />
        )}
      </Modal>
    </div>
  )
}

export default SkillsPage
