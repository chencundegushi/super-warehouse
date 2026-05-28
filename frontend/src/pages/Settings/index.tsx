/**
 * 系统设置页面
 * 展示系统配置信息，管理快捷问题标签。
 *
 * @module SettingsPage
 */
import { useState, useEffect, useCallback } from 'react'
import { Input, Button, Typography, Spin, message, Select } from 'antd'
import {
  PlusOutlined, DeleteOutlined, SaveOutlined, ReloadOutlined,
} from '@ant-design/icons'
import { getSystemSettings, getSuggestions, updateSuggestions } from '@/services/settingsApi'
import type { SystemSettings, SuggestionItem } from '@/services/settingsApi'
import styles from './index.module.css'

const { Title, Text } = Typography

/** 可选图标列表 */
const ICON_OPTIONS = [
  { value: 'DollarOutlined', label: '💰 收入' },
  { value: 'RiseOutlined', label: '📈 趋势' },
  { value: 'BarChartOutlined', label: '📊 图表' },
  { value: 'TeamOutlined', label: '👥 用户' },
  { value: 'ThunderboltOutlined', label: '⚡ 快速' },
  { value: 'SearchOutlined', label: '🔍 查询' },
  { value: 'DatabaseOutlined', label: '🗄️ 数据库' },
  { value: 'LineChartOutlined', label: '📉 折线' },
  { value: 'PieChartOutlined', label: '🥧 饼图' },
  { value: 'FundOutlined', label: '💹 基金' },
]

/**
 * 系统设置页面组件
 */
function SettingsPage() {
  // 系统配置
  const [systemInfo, setSystemInfo] = useState<SystemSettings | null>(null)
  const [loadingSystem, setLoadingSystem] = useState(true)

  // 快捷标签
  const [suggestions, setSuggestions] = useState<SuggestionItem[]>([])
  const [loadingSuggestions, setLoadingSuggestions] = useState(true)
  const [saving, setSaving] = useState(false)

  const [messageApi, contextHolder] = message.useMessage()

  // 加载系统配置
  useEffect(() => {
    const load = async () => {
      console.log('[SettingsPage] Loading system settings')
      try {
        const data = await getSystemSettings()
        setSystemInfo(data)
      } catch (err) {
        console.error('[SettingsPage] Failed to load system settings:', err)
      } finally {
        setLoadingSystem(false)
      }
    }
    load()
  }, [])

  // 加载快捷标签
  const loadSuggestions = useCallback(async () => {
    console.log('[SettingsPage] Loading suggestions')
    setLoadingSuggestions(true)
    try {
      const data = await getSuggestions()
      setSuggestions(data)
    } catch (err) {
      console.error('[SettingsPage] Failed to load suggestions:', err)
    } finally {
      setLoadingSuggestions(false)
    }
  }, [])

  useEffect(() => { loadSuggestions() }, [loadSuggestions])

  /** 添加一条标签 */
  const handleAdd = () => {
    setSuggestions(prev => [...prev, { icon: 'SearchOutlined', label: '', text: '' }])
  }

  /** 删除一条标签 */
  const handleDelete = (idx: number) => {
    setSuggestions(prev => prev.filter((_, i) => i !== idx))
  }

  /** 更新某条标签字段 */
  const handleChange = (idx: number, field: keyof SuggestionItem, value: string) => {
    setSuggestions(prev => prev.map((item, i) => i === idx ? { ...item, [field]: value } : item))
  }

  /** 保存标签配置 */
  const handleSave = async () => {
    // 校验：过滤空标签
    const valid = suggestions.filter(s => s.label.trim() && s.text.trim())
    if (valid.length === 0) {
      messageApi.warning('至少保留一条快捷标签')
      return
    }
    console.log('[SettingsPage] Saving suggestions, count:', valid.length)
    setSaving(true)
    try {
      await updateSuggestions(valid)
      setSuggestions(valid)
      messageApi.success('保存成功')
    } catch (err) {
      console.error('[SettingsPage] Failed to save suggestions:', err)
      messageApi.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={styles.settingsContainer}>
      {contextHolder}
      <Title level={4} className={styles.pageTitle}>系统设置</Title>

      {/* 系统配置信息 */}
      <div className={styles.section}>
        <div className={styles.sectionTitle}>系统配置</div>
        {loadingSystem ? (
          <Spin size="small" />
        ) : systemInfo ? (
          <div className={styles.infoGrid}>
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>应用名称</span>
              <span className={styles.infoValue}>{systemInfo.app_name}</span>
            </div>
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>版本</span>
              <span className={styles.infoValue}>{systemInfo.app_version}</span>
            </div>
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>LLM 模型</span>
              <span className={styles.infoValue}>{systemInfo.llm_model}</span>
            </div>
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>LLM 地址</span>
              <span className={styles.infoValue}>{systemInfo.llm_base_url}</span>
            </div>
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>Temperature</span>
              <span className={styles.infoValue}>{systemInfo.llm_temperature}</span>
            </div>
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>Max Tokens</span>
              <span className={styles.infoValue}>{systemInfo.llm_max_tokens}</span>
            </div>
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>Doris 地址</span>
              <span className={styles.infoValue}>{systemInfo.doris_host}:{systemInfo.doris_port}</span>
            </div>
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>Doris 数据库</span>
              <span className={styles.infoValue}>{systemInfo.doris_database}</span>
            </div>
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>查询超时</span>
              <span className={styles.infoValue}>{systemInfo.query_timeout_seconds}s</span>
            </div>
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>最大返回行数</span>
              <span className={styles.infoValue}>{systemInfo.query_max_rows}</span>
            </div>
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>对话最大轮次</span>
              <span className={styles.infoValue}>{systemInfo.conversation_max_turns}</span>
            </div>
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>指标匹配阈值</span>
              <span className={styles.infoValue}>{systemInfo.metric_match_threshold}</span>
            </div>
          </div>
        ) : (
          <Text type="secondary">加载失败</Text>
        )}
      </div>

      {/* 快捷标签管理 */}
      <div className={styles.section}>
        <div className={styles.sectionTitle}>快捷问题标签</div>
        {loadingSuggestions ? (
          <Spin size="small" />
        ) : (
          <>
            <div className={styles.suggestionList}>
              {suggestions.map((item, idx) => (
                <div key={idx} className={styles.suggestionRow}>
                  <span className={styles.suggestionIndex}>{idx + 1}</span>
                  <div className={styles.suggestionInputs}>
                    <Select
                      value={item.icon}
                      onChange={(val) => handleChange(idx, 'icon', val)}
                      options={ICON_OPTIONS}
                      style={{ width: 110 }}
                      size="small"
                    />
                    <Input
                      value={item.label}
                      onChange={(e) => handleChange(idx, 'label', e.target.value)}
                      placeholder="标签名称"
                      size="small"
                      style={{ width: 120 }}
                    />
                    <Input
                      value={item.text}
                      onChange={(e) => handleChange(idx, 'text', e.target.value)}
                      placeholder="点击后发送的问题内容"
                      size="small"
                      style={{ flex: 1 }}
                    />
                  </div>
                  <Button
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    size="small"
                    onClick={() => handleDelete(idx)}
                  />
                </div>
              ))}
            </div>
            <div className={styles.actionBar}>
              <Button icon={<PlusOutlined />} size="small" onClick={handleAdd}>添加</Button>
              <Button icon={<ReloadOutlined />} size="small" onClick={loadSuggestions}>重置</Button>
              <Button type="primary" icon={<SaveOutlined />} size="small" loading={saving} onClick={handleSave}>保存</Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default SettingsPage
