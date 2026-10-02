import { defineStore } from 'pinia'

import api, { BASE_URL } from '@/api'

const MAX_CHAT_HISTORY = 10          // 回传给后端的上下文条数
const MAX_TRAFFIC_POINTS = 30        // 折线图最多保留的点数
const TRAFFIC_POLL_MS = 5000         // 流量轮询间隔
const DEVICE_POLL_MS = 15000         // 设备状态轮询间隔

export const useConsoleStore = defineStore('console', {
  state: () => ({
    apiBase: BASE_URL,
    // 设备
    devices: [],
    deviceMeta: { total: 0, online: 0, offline: 0, checked_at: '', cached: false },
    devicesLoading: false,
    // 控制台统计
    stats: {
      devices_total: 0,
      devices_online: 0,
      alerts_active: 0,
      alerts_total: 0,
      audit_total: 0,
      audit_failed: 0,
    },
    // MCP / 后端状态
    mcp: { connected: false, tools: [], transport: 'stdio', last_error: '' },
    backendOnline: false,
    lastError: '',
    // 设备详情
    selected: '',
    detail: null,
    detailLoading: false,
    // 告警
    alerts: [],
    alertStats: {},
    // AI 对话
    messages: [],       // { role, content, tools?, pending?, error?, elapsed_ms? }
    asking: false,
    // 流量
    traffic: {
      device: '',
      interface: 'eth0',
      points: [],       // { time, rx, tx }
      live: false,
      loading: false,
      latest: null,     // 最近一次采样结果
      error: '',
    },
    _timers: { devices: null, traffic: null },
  }),

  getters: {
    onlineDevices: (state) => state.devices.filter((item) => item.online),
    offlineDevices: (state) => state.devices.filter((item) => !item.online),
    deviceNames: (state) => state.devices.map((item) => item.name),
    selectedDevice: (state) =>
      state.devices.find((item) => item.name === state.selected) || null,
    systemHealthy: (state) => state.backendOnline && state.mcp.connected,
    unacked: (state) => state.stats.alerts_active,
  },

  actions: {
    // ---------- 基础加载 ----------
    async loadDevices(refresh = false) {
      this.devicesLoading = true
      try {
        const data = await api.devices(refresh)
        this.devices = data.devices || []
        this.deviceMeta = {
          total: data.total,
          online: data.online,
          offline: data.offline,
          checked_at: data.checked_at,
          cached: data.cached,
        }
        this.backendOnline = true
        this.lastError = ''
        if (!this.traffic.device && this.devices.length) {
          this.traffic.device = (this.devices.find((d) => d.online) || this.devices[0]).name
        }
      } catch (error) {
        this.backendOnline = false
        this.lastError = error.message
      } finally {
        this.devicesLoading = false
      }
    },

    async loadStats() {
      try {
        this.stats = await api.stats()
      } catch (error) {
        this.lastError = error.message
      }
    },

    async loadMcp() {
      try {
        this.mcp = await api.mcpHealth()
      } catch (error) {
        this.mcp = { connected: false, tools: [], last_error: error.message }
      }
    },

    async loadAlerts(level = '') {
      try {
        const data = await api.alerts({ limit: 50, ...(level ? { level } : {}) })
        this.alerts = data.items || []
        this.alertStats = data.stats || {}
      } catch (error) {
        this.lastError = error.message
      }
    },

    // ---------- 设备详情 ----------
    async selectDevice(name) {
      this.selected = name
      this.detail = null
      await this.loadDetail(name)
    },

    clearSelection() {
      this.selected = ''
      this.detail = null
    },

    async loadDetail(name) {
      if (!name) return
      this.detailLoading = true
      try {
        this.detail = await api.deviceDetail(name)
      } catch (error) {
        this.detail = { name, online: false, error: error.message }
      } finally {
        this.detailLoading = false
      }
    },

    // ---------- 流量采样 ----------
    async sampleTraffic(push = true) {
      const device = this.traffic.device
      if (!device) return
      if (this.traffic.loading) return // 上一轮采样尚未返回（SSH 较慢）时跳过本次轮询
      this.traffic.loading = true
      try {
        const data = await api.traffic(device, this.traffic.interface, 1.0)
        this.traffic.latest = data
        this.traffic.error = data.online ? '' : data.message || '设备不可达'
        if (push) {
          const label = (data.timestamp || '').slice(11) || new Date().toLocaleTimeString()
          this.traffic.points.push({
            time: label,
            rx: Number(data.rx_mbps || 0),
            tx: Number(data.tx_mbps || 0),
          })
          if (this.traffic.points.length > MAX_TRAFFIC_POINTS) {
            this.traffic.points.splice(0, this.traffic.points.length - MAX_TRAFFIC_POINTS)
          }
        }
      } catch (error) {
        this.traffic.error = error.message
        this.traffic.latest = null
      } finally {
        this.traffic.loading = false
      }
    },

    setTrafficTarget(device, iface) {
      if (device) this.traffic.device = device
      if (iface) this.traffic.interface = iface
      this.traffic.points = []
      this.traffic.latest = null
    },

    toggleTrafficLive() {
      this.traffic.live = !this.traffic.live
      if (this.traffic.live) {
        this.sampleTraffic(true)
        this.startTrafficPolling()
      } else {
        this.stopTrafficPolling()
      }
    },

    startTrafficPolling() {
      this.stopTrafficPolling()
      this._timers.traffic = setInterval(() => {
        if (this.traffic.live) this.sampleTraffic(true)
      }, TRAFFIC_POLL_MS)
    },

    stopTrafficPolling() {
      if (this._timers.traffic) {
        clearInterval(this._timers.traffic)
        this._timers.traffic = null
      }
    },

    // ---------- AI 对话（核心链路）----------
    async ask(message) {
      const text = (message || '').trim()
      if (!text || this.asking) return null
      const history = this.messages
        .filter((item) => item.role !== 'system' && !item.error)
        .slice(-MAX_CHAT_HISTORY)
        .map((item) => ({ role: item.role, content: item.content }))

      this.messages.push({ role: 'user', content: text, ts: Date.now() })
      this.asking = true
      try {
        const data = await api.chat(text, history, 'web')
        const reply = {
          role: 'assistant',
          content: data.reply || '(空回复)',
          tools: data.tool_calls || [],
          pending: data.pending_approval || null,
          elapsed_ms: data.elapsed_ms || 0,
          ts: Date.now(),
        }
        this.messages.push(reply)
        return reply
      } catch (error) {
        const failure = {
          role: 'assistant',
          content: `调用失败：${error.message}`,
          error: true,
          ts: Date.now(),
        }
        this.messages.push(failure)
        return failure
      } finally {
        this.asking = false
      }
    },

    clearChat() {
      this.messages = []
    },

    // ---------- 轮询与启动 ----------
    startPolling() {
      this.stopPolling()
      this._timers.devices = setInterval(() => {
        this.loadDevices(false)
        this.loadStats()
        this.loadMcp()
      }, DEVICE_POLL_MS)
    },

    stopPolling() {
      if (this._timers.devices) {
        clearInterval(this._timers.devices)
        this._timers.devices = null
      }
      this.stopTrafficPolling()
    },

    async bootstrap() {
      await Promise.all([
        this.loadDevices(false),
        this.loadStats(),
        this.loadMcp(),
        this.loadAlerts(),
      ])
      this.startPolling()
    },
  },
})
