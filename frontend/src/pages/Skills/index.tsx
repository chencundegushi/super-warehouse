/**
 * 技能管理页面
 * 支持文件型技能（目录导入）的管理，包括：
 * - 目录上传导入（webkitdirectory）
 * - 技能列表展示
 * - 技能详情查看（SKILL.md 内容 + 文件列表）
 * - 技能删除
 *
 * @module SkillsPage
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Card,
  List,
  Button,
  Modal,
  Popconfirm,
  message,
  Space,
  Typography,
  Empty,
  Spin,
  Tag,
  Tabs,
} from 'antd'
import {
  ThunderboltOutlined,
  FolderOpenOutlined,
  DeleteOutlined,
  FileTextOutlined,
  CodeOutlined,
  EyeOutlined,
} from '@ant-design/icons'
import {
  listSkillFiles,
  getSkillFileDetail,
  importSkillDirectory,
  deleteSkillFile,
  type SkillFileInfo,
  type SkillFileDetail,
} from '@/services/skillFileApi'

const { Title, Text, Paragraph } = Typography

/**
 * 技能管理页面组件
 */
function SkillsPage() {
  const [skills, setSkills] = useState<SkillFileInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [importing, setImporting] = useState(false)
  // 详情弹窗
  const [detailVisible, setDetailVisible] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailData, setDetailData] = useState<SkillFileDetail | null>(null)
  // 目录上传 input ref
  const dirInputRef = useRef<HTMLInputElement>(null)

  /** 加载技能列表 */
  const fetchSkills = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listSkillFiles()
      setSkills(data)
    } catch (err) {
      console.error('[SkillsPage] Failed to fetch skills:', err)
      message.error('加载技能列表失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchSkills() }, [fetchSkills])

  /** 处理目录选择上传 */
  const handleDirectorySelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    // 检查是否包含 SKILL.md
    const hasSkillMd = Array.from(files).some(f =>
      (f as any).webkitRelativePath?.endsWith('SKILL.md') || f.name === 'SKILL.md'
    )
    if (!hasSkillMd) {
      message.error('所选目录中缺少 SKILL.md 文件')
      e.target.value = ''
      return
    }

    setImporting(true)
    try {
      const result = await importSkillDirectory(files)
      message.success(`技能「${result.displayName}」导入成功`)
      fetchSkills()
    } catch (err: any) {
      console.error('[SkillsPage] Import failed:', err)
      message.error(err.message || '导入失败')
    } finally {
      setImporting(false)
      e.target.value = ''
    }
  }

  /** 查看技能详情 */
  const handleViewDetail = async (skill: SkillFileInfo) => {
    setDetailVisible(true)
    setDetailLoading(true)
    try {
      const detail = await getSkillFileDetail(skill.name)
      setDetailData(detail)
    } catch (err) {
      console.error('[SkillsPage] Failed to get detail:', err)
      message.error('获取技能详情失败')
    } finally {
      setDetailLoading(false)
    }
  }

  /** 删除技能 */
  const handleDelete = async (skill: SkillFileInfo) => {
    try {
      await deleteSkillFile(skill.name)
      message.success('技能删除成功')
      fetchSkills()
    } catch (err) {
      console.error('[SkillsPage] Delete failed:', err)
      message.error('删除失败')
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
        <Space>
          <Button
            type="primary"
            icon={<FolderOpenOutlined />}
            loading={importing}
            onClick={() => dirInputRef.current?.click()}
          >
            导入技能目录
          </Button>
          {/* 隐藏的目录选择 input */}
          <input
            ref={dirInputRef}
            type="file"
            // @ts-ignore webkitdirectory is non-standard
            webkitdirectory=""
            directory=""
            multiple
            style={{ display: 'none' }}
            onChange={handleDirectorySelect}
          />
        </Space>
      </div>

      {/* 技能列表 */}
      <Spin spinning={loading}>
        {skills.length === 0 && !loading ? (
          <Empty description="暂无技能，点击「导入技能目录」选择包含 SKILL.md 的目录导入" />
        ) : (
          <List
            grid={{ gutter: 16, xs: 1, sm: 1, md: 2, lg: 3, xl: 3, xxl: 4 }}
            dataSource={skills}
            renderItem={(skill) => (
              <List.Item>
                <Card
                  title={
                    <Space>
                      <span>{skill.displayName}</span>
                      {skill.hasScript && <Tag color="blue" style={{ fontSize: 11 }}>含脚本</Tag>}
                    </Space>
                  }
                  hoverable
                  actions={[
                    <EyeOutlined key="view" onClick={() => handleViewDetail(skill)} />,
                    <Popconfirm
                      key="delete"
                      title="确认删除"
                      description={`确定要删除技能「${skill.displayName}」吗？`}
                      onConfirm={() => handleDelete(skill)}
                      okText="确认"
                      cancelText="取消"
                    >
                      <DeleteOutlined />
                    </Popconfirm>,
                  ]}
                >
                  <Card.Meta
                    description={
                      <div>
                        <Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 8, color: '#999' }}>
                          {skill.description || '暂无描述'}
                        </Paragraph>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          <FileTextOutlined style={{ marginRight: 4 }} />
                          {skill.files.length} 个文件
                        </Text>
                      </div>
                    }
                  />
                </Card>
              </List.Item>
            )}
          />
        )}
      </Spin>

      {/* 详情弹窗 */}
      <Modal
        title={detailData ? `技能详情 — ${detailData.displayName}` : '技能详情'}
        open={detailVisible}
        onCancel={() => { setDetailVisible(false); setDetailData(null) }}
        footer={null}
        width={800}
        destroyOnClose
      >
        {detailLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : detailData ? (
          <div>
            {/* 基本信息 */}
            <div style={{ marginBottom: 16 }}>
              <Text strong>描述：</Text>
              <Text>{detailData.description || '无'}</Text>
            </div>

            {/* 文件内容 Tabs */}
            <Tabs
              defaultActiveKey="skill_md"
              items={detailData.files.map((file) => ({
                key: file.name,
                label: (
                  <span>
                    {file.name.endsWith('.py') ? <CodeOutlined style={{ marginRight: 4 }} /> : <FileTextOutlined style={{ marginRight: 4 }} />}
                    {file.name}
                  </span>
                ),
                children: (
                  <pre style={{
                    background: '#1a1a1a',
                    padding: 16,
                    borderRadius: 8,
                    overflow: 'auto',
                    maxHeight: 500,
                    fontSize: 13,
                    lineHeight: 1.5,
                    color: '#e0e0e0',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}>
                    {file.content || '(无法读取内容)'}
                  </pre>
                ),
              }))}
            />
          </div>
        ) : null}
      </Modal>
    </div>
  )
}

export default SkillsPage
