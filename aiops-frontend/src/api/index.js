import axios from 'axios'

// 所有 API 请求都指向 FastAPI 后端（可用 .env 里的 VITE_API_BASE 覆盖）
export const BASE_URL = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const http = axios.create({
  baseURL: BASE_URL,
  timeout: 180000, // AI 链路含 SSH + 两次 LLM 调用，超时给宽一些
  headers: { 'Content-Type': 'application/json' },
  // 后端 CORS 使用 allow_origins=['*']，此时携带 cookie 会被浏览器判定为非法请求，
  // 因此必须保持 withCredentials = false（这也是最常见的前端 CORS 报错原因）。
  withCredentials: false,
})

// 统一把后端的 {detail: "..."} 与网络错误转成可读的中文提示
http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    let message = error.message || '请求失败'
    if (error.response) {
      const detail = error.response.data?.detail
      message = `HTTP ${error.response.status}：${
        typeof detail === 'string' ? detail : JSON.stringify(detail ?? error.response.statusText)
      }`
    } else if (error.code === 'ECONNABORTED') {
      message = `请求超时（${BASE_URL} 响应过慢，AI 全链路建议 60s 以上超时）`
    } else {
      message = `无法连接后端 ${BASE_URL}（请确认已执行 uvicorn main:app --reload --port 8000）`
    }
    return Promise.reject(new Error(message))
  },
)

export const api = {
  health: () => http.get('/health'),
  mcpHealth: () => http.get('/api/mcp/health'),
  stats: () => http.get('/api/stats'),

  // 设备
  devices: (refresh = false) => http.get('/api/devices', { params: { refresh } }),
  deviceDetail: (name) => http.get(`/api/devices/${encodeURIComponent(name)}`),

  // AI 对话：{ message, history, session_id }
  chat: (message, history = [], sessionId = 'web') =>
    http.post('/api/chat', { message, history, session_id: sessionId }),

  // 审计与告警
  auditLogs: (params = {}) => http.get('/api/audit-logs', { params }),
  alerts: (params = {}) => http.get('/api/alerts', { params }),
  ackAlert: (id, note = '') => http.post(`/api/alerts/${id}/ack`, { note }),

  // 流量
  traffic: (device, iface = 'eth0', gap = 1.0) =>
    http.get(`/api/traffic/${encodeURIComponent(device)}/${encodeURIComponent(iface)}`, {
      params: { gap },
    }),
}

export default api
