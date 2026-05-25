/**
 * 基础 HTTP 请求封装
 * 提供统一的 GET/POST/PUT/DELETE 方法，基于 fetch API 实现。
 * 所有请求通过 Vite 代理转发到后端服务。
 */

/** API 错误类型 */
export class ApiError extends Error {
  /** HTTP 状态码 */
  status: number
  /** 后端返回的错误详情 */
  detail?: string

  constructor(status: number, message: string, detail?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** API 基础路径，由 Vite 代理转发到后端 */
const BASE_URL = '/api'

/**
 * 解析响应体，处理错误状态码
 * @param response - fetch 响应对象
 * @returns 解析后的 JSON 数据
 * @throws ApiError 当响应状态码非 2xx 时抛出
 */
async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail: string | undefined
    try {
      const errorBody = await response.json()
      detail = errorBody.detail || errorBody.message || JSON.stringify(errorBody)
    } catch {
      detail = await response.text().catch(() => undefined)
    }
    console.error('[API] Request failed, status:', response.status, 'detail:', detail)
    throw new ApiError(response.status, `HTTP ${response.status}`, detail)
  }

  // 1.处理 204 No Content 响应
  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

/**
 * 发送 GET 请求
 * @param path - 请求路径（相对于 /api）
 * @param params - 可选的查询参数
 * @returns 响应数据
 */
export async function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  // 1.构建查询字符串
  const url = new URL(`${BASE_URL}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined) {
        url.searchParams.append(key, String(value))
      }
    })
  }

  console.log('[API] GET', url.pathname + url.search)
  const response = await fetch(url.toString(), {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  })

  return handleResponse<T>(response)
}

/**
 * 发送 POST 请求
 * @param path - 请求路径（相对于 /api）
 * @param body - 请求体数据
 * @returns 响应数据
 */
export async function post<T>(path: string, body?: unknown): Promise<T> {
  console.log('[API] POST', `${BASE_URL}${path}`)
  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  return handleResponse<T>(response)
}

/**
 * 发送 PUT 请求
 * @param path - 请求路径（相对于 /api）
 * @param body - 请求体数据
 * @returns 响应数据
 */
export async function put<T>(path: string, body?: unknown): Promise<T> {
  console.log('[API] PUT', `${BASE_URL}${path}`)
  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  return handleResponse<T>(response)
}

/**
 * 发送 DELETE 请求
 * @param path - 请求路径（相对于 /api）
 * @returns 响应数据
 */
export async function del<T = void>(path: string): Promise<T> {
  console.log('[API] DELETE', `${BASE_URL}${path}`)
  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
  })

  return handleResponse<T>(response)
}
