/**
 * SQL 预览与确认组件
 * 使用 Monaco Editor 展示生成的 SQL（只读模式，SQL 语法高亮），
 * 提供确认执行和拒绝按钮，拒绝时展示反馈输入框供用户提供修改意见。
 *
 * @module SQLPreview
 */

import { useState } from 'react'
import { Button, Card, Input, Space, Typography } from 'antd'
import Editor from '@monaco-editor/react'

const { TextArea } = Input
const { Text } = Typography

/**
 * SQLPreview 组件 Props
 * @param sql - 待展示的 SQL 语句
 * @param explanation - SQL 解释说明文本
 * @param source - SQL 来源（metric/sql_generator）
 * @param onConfirm - 用户确认执行回调
 * @param onReject - 用户拒绝并提交反馈回调
 * @param loading - 确认操作是否正在处理中
 */
export interface SQLPreviewProps {
  sql: string
  explanation: string
  source: string
  onConfirm: () => void
  onReject: (feedback: string) => void
  loading?: boolean
}

/**
 * SQL 预览与确认组件
 * 展示 Agent 生成的 SQL，用户可确认执行或拒绝并提供修改意见。
 */
const SQLPreview: React.FC<SQLPreviewProps> = ({
  sql,
  explanation,
  source,
  onConfirm,
  onReject,
  loading = false,
}) => {
  // 1.是否显示拒绝反馈输入区域
  const [showFeedback, setShowFeedback] = useState(false)
  // 2.用户输入的修改意见
  const [feedback, setFeedback] = useState('')

  /**
   * 处理拒绝按钮点击
   * 展示反馈输入框
   */
  const handleRejectClick = () => {
    console.log('[SQLPreview] Reject button clicked, showing feedback input')
    setShowFeedback(true)
  }

  /**
   * 提交修改意见
   * 调用 onReject 回调并重置状态
   */
  const handleSubmitFeedback = () => {
    const trimmedFeedback = feedback.trim()
    if (!trimmedFeedback) {
      return
    }
    console.log('[SQLPreview] Submitting feedback, length:', trimmedFeedback.length)
    onReject(trimmedFeedback)
    setShowFeedback(false)
    setFeedback('')
  }

  return (
    <Card
      size="small"
      style={{ marginBottom: 12 }}
      styles={{ body: { padding: '12px 16px' } }}
    >
      {/* SQL 解释说明 */}
      <div style={{ marginBottom: 8 }}>
        <Text type="secondary" style={{ fontSize: 13 }}>
          {explanation}
        </Text>
        {source && (
          <Text
            type="secondary"
            style={{ fontSize: 12, marginLeft: 8, opacity: 0.6 }}
          >
            (来源: {source === 'metric' ? '指标匹配' : 'SQL生成器'})
          </Text>
        )}
      </div>

      {/* Monaco Editor - SQL 只读展示 */}
      <div style={{ border: '1px solid #303030', borderRadius: 4, overflow: 'hidden', marginBottom: 12 }}>
        <Editor
          height="200px"
          language="sql"
          theme="vs-dark"
          value={sql}
          options={{
            readOnly: true,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            fontSize: 13,
            lineNumbers: 'on',
            wordWrap: 'on',
            automaticLayout: true,
            domReadOnly: true,
          }}
        />
      </div>

      {/* 操作按钮区域 */}
      <Space direction="vertical" style={{ width: '100%' }}>
        <Space>
          <Button
            type="primary"
            onClick={onConfirm}
            loading={loading}
            disabled={showFeedback}
          >
            确认执行
          </Button>
          <Button
            onClick={handleRejectClick}
            disabled={loading || showFeedback}
          >
            拒绝
          </Button>
        </Space>

        {/* 拒绝反馈输入区域 */}
        {showFeedback && (
          <div style={{ marginTop: 8 }}>
            <TextArea
              placeholder="请输入修改意见，说明需要如何调整 SQL..."
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              rows={3}
              style={{ marginBottom: 8 }}
            />
            <Space>
              <Button
                type="primary"
                onClick={handleSubmitFeedback}
                disabled={!feedback.trim()}
              >
                提交修改意见
              </Button>
              <Button
                onClick={() => {
                  setShowFeedback(false)
                  setFeedback('')
                }}
              >
                取消
              </Button>
            </Space>
          </div>
        )}
      </Space>
    </Card>
  )
}

export default SQLPreview
