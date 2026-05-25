/**
 * 数据表格组件
 * 使用 Ant Design Table 展示查询结果数据，支持分页浏览（单页≤1000行）和空数据状态提示。
 *
 * @module DataTable
 */

import { useMemo } from 'react'
import { Table, Empty, Typography } from 'antd'
import type { TableProps } from 'antd'
import type { QueryResult, ColumnInfo } from '../types'

const { Text } = Typography

/** 单页最大行数 */
const PAGE_SIZE_LIMIT = 1000

/** 默认每页行数 */
const DEFAULT_PAGE_SIZE = 50

/** 可选的每页行数选项 */
const PAGE_SIZE_OPTIONS = [20, 50, 100, 200, 500, 1000]

/**
 * DataTable 组件 Props
 * @param data - 查询结果数据（包含列定义和行数据）
 * @param loading - 是否正在加载中
 * @param pageSize - 自定义每页行数，默认50
 */
export interface DataTableProps {
  /** 查询结果数据 */
  data: QueryResult | null
  /** 是否正在加载 */
  loading?: boolean
  /** 自定义每页行数，默认50，最大1000 */
  pageSize?: number
}

/**
 * 将 ColumnInfo 转换为 Ant Design Table 的列配置
 * @param columns - 查询结果的列信息数组
 * @returns Ant Design Table 列配置数组
 */
function buildTableColumns(columns: ColumnInfo[]): TableProps['columns'] {
  return columns.map((col, index) => ({
    title: col.name,
    dataIndex: index.toString(),
    key: col.name,
    ellipsis: true,
    // 1.数值类型列右对齐
    align: col.isNumeric ? ('right' as const) : ('left' as const),
    sorter: col.isNumeric
      ? (a: Record<string, unknown>, b: Record<string, unknown>) => {
          const valA = Number(a[index.toString()] ?? 0)
          const valB = Number(b[index.toString()] ?? 0)
          return valA - valB
        }
      : undefined,
  }))
}

/**
 * 将二维数组行数据转换为 Ant Design Table 所需的对象数组格式
 * @param rows - 查询结果的行数据（二维数组）
 * @returns 对象数组，key 为列索引字符串
 */
function buildTableDataSource(rows: unknown[][]): Record<string, unknown>[] {
  return rows.map((row, rowIndex) => {
    const record: Record<string, unknown> = { key: rowIndex }
    row.forEach((cell, colIndex) => {
      record[colIndex.toString()] = cell
    })
    return record
  })
}

/**
 * 数据表格组件
 * 展示查询结果，支持分页浏览和空数据状态提示。
 */
const DataTable: React.FC<DataTableProps> = ({
  data,
  loading = false,
  pageSize = DEFAULT_PAGE_SIZE,
}) => {
  console.log('[DataTable] Rendering, loading:', loading, 'hasData:', !!data)

  // 2.确保 pageSize 不超过单页限制
  const effectivePageSize = Math.min(pageSize, PAGE_SIZE_LIMIT)

  // 3.构建列配置（使用 useMemo 避免重复计算）
  const columns = useMemo(() => {
    if (!data || data.columns.length === 0) return []
    return buildTableColumns(data.columns)
  }, [data])

  // 4.构建数据源
  const dataSource = useMemo(() => {
    if (!data || data.rows.length === 0) return []
    return buildTableDataSource(data.rows)
  }, [data])

  // 5.空数据状态：data 为 null 或行数为 0
  if (!loading && (!data || data.rows.length === 0)) {
    return (
      <Empty
        description={
          <Text type="secondary">
            当前查询无返回数据
          </Text>
        }
        style={{ padding: '48px 0' }}
      />
    )
  }

  return (
    <div style={{ width: '100%' }}>
      {/* 6.数据截断提示 */}
      {data?.truncated && (
        <div style={{ marginBottom: 8 }}>
          <Text type="warning" style={{ fontSize: 12 }}>
            查询结果已截断，仅展示前 {data.rowCount} 行数据
          </Text>
        </div>
      )}

      <Table
        columns={columns}
        dataSource={dataSource}
        loading={loading}
        size="small"
        scroll={{ x: 'max-content', y: 500 }}
        pagination={{
          pageSize: effectivePageSize,
          pageSizeOptions: PAGE_SIZE_OPTIONS.map(String),
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 条数据`,
          showQuickJumper: true,
        }}
        bordered
      />

      {/* 7.执行耗时信息 */}
      {data && (
        <div style={{ marginTop: 8, textAlign: 'right' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            执行耗时: {data.executionTime}ms | 共 {data.rowCount} 行
          </Text>
        </div>
      )}
    </div>
  )
}

export default DataTable
