/**
 * 指标 SQL 编辑器组件
 * 集成 Monaco Editor 提供 SQL 语法高亮和编辑能力，
 * 支持调用后端接口自动生成参考 SQL，用户可手动修改后保存。
 *
 * @module MetricSQLEditor
 */

import { useState, useCallback } from 'react'
import { Button, Spin, message, Space } from 'antd'
import { ThunderboltOutlined } from '@ant-design/icons'
import Editor from '@monaco-editor/react'
import { generateSQL } from '@/services/metricApi'

/**
 * MetricSQLEditor 组件 Props
 * @param value - 当前 SQL 内容（由 Form.Item 自动注入或外部传入）
 * @param onChange - SQL 内容变更回调（由 Form.Item 自动注入或外部传入）
 * @param metricName - 指标名称，用于自动生成参考 SQL
 * @param metricDescription - 指标用途说明，用于自动生成参考 SQL
 */
export interface MetricSQLEditorProps {
  value?: string
  onChange?: (sql: string) => void
  metricName?: string
  metricDescription?: string
}

/**
 * 指标 SQL 编辑器组件
 * 提供 SQL 编辑（Monaco Editor）和自动生成参考 SQL 功能。
 * 可作为 Ant Design Form.Item 的受控子组件使用。
 */
const MetricSQLEditor: React.FC<MetricSQLEditorProps> = ({
  value = '',
  onChange,
  metricName,
  metricDescription,
}) => {
  // 1.加载状态：标记是否正在生成参考 SQL
  const [generating, setGenerating] = useState(false)

  /**
   * 处理自动生成参考 SQL
   * 调用后端 Agent 接口，根据指标名称和描述生成 SQL。
   */
  const handleGenerateSQL = useCallback(async () => {
    // 2.校验：指标名称和描述不能为空
    if (!metricName || !metricDescription) {
      message.warning('请先填写指标名称和用途说明')
      return
    }

    console.log('[MetricSQLEditor] Generating reference SQL, metricName:', metricName)
    setGenerating(true)
    try {
      // 3.调用后端接口生成参考 SQL
      const sql = await generateSQL(metricName, metricDescription)
      console.log('[MetricSQLEditor] SQL generated successfully, length:', sql.length)
      // 4.将生成的 SQL 设置到编辑器
      onChange?.(sql)
      message.success('参考 SQL 生成成功')
    } catch (error) {
      console.error('[MetricSQLEditor] Failed to generate SQL:', error)
      message.error('生成参考 SQL 失败，请稍后重试')
    } finally {
      setGenerating(false)
    }
  }, [metricName, metricDescription, onChange])

  /**
   * 处理编辑器内容变更
   * 用户手动修改 SQL 时触发。
   */
  const handleEditorChange = useCallback(
    (newValue: string | undefined) => {
      onChange?.(newValue ?? '')
    },
    [onChange]
  )

  return (
    <Spin spinning={generating} tip="正在生成参考 SQL...">
      <Space direction="vertical" style={{ width: '100%' }} size="small">
        {/* 操作按钮区域 */}
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            onClick={handleGenerateSQL}
            loading={generating}
            disabled={!metricName || !metricDescription}
          >
            自动生成参考SQL
          </Button>
        </div>

        {/* Monaco SQL 编辑器 */}
        <Editor
          height="300px"
          language="sql"
          theme="vs-dark"
          value={value}
          onChange={handleEditorChange}
          options={{
            minimap: { enabled: false },
            fontSize: 14,
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            wordWrap: 'on',
            automaticLayout: true,
          }}
        />
      </Space>
    </Spin>
  )
}

export default MetricSQLEditor
