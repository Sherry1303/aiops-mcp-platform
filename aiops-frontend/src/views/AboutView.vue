<script setup>
import { computed, onMounted, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { BASE_URL } from '@/api'
import { useConsoleStore } from '@/stores/console'

const store = useConsoleStore()
const health = ref(null)
const error = ref('')

const endpoints = [
  { method: 'GET', path: '/api/devices', desc: '设备清单 + SSH 实时在线状态（TTL 缓存）' },
  { method: 'GET', path: '/api/devices/{name}', desc: '单设备只读详情（版本/接口/CPU/内存）' },
  { method: 'POST', path: '/api/chat', desc: '自然语言 → DeepSeek 意图 → MCP 工具 → 中文结论' },
  { method: 'GET', path: '/api/audit-logs', desc: 'SQLite 审计日志（分页 / 设备 / 状态 / 关键字）' },
  { method: 'GET', path: '/api/alerts', desc: '告警列表与 P0/P1/P2 分级统计' },
  { method: 'POST', path: '/api/alerts/{id}/ack', desc: '确认告警（可附处置备注）' },
  { method: 'GET', path: '/api/traffic/{device}/{interface}', desc: '两次采样差值 → RX/TX Mbps' },
  { method: 'GET', path: '/api/stats', desc: '控制台数据卡聚合统计' },
  { method: 'GET', path: '/api/mcp/health', desc: 'MCP 客户端连接状态与已加载工具' },
]

const layers = [
  { name: '展示层', tech: 'Vue 3 + Vite + Tailwind CSS + ECharts', desc: '控制台 / 审计日志 / 关于，马卡龙渐变 + 毛玻璃卡片' },
  { name: '接口层', tech: 'FastAPI + Uvicorn（:8000，CORS 全放开）', desc: 'REST 接口、Pydantic 校验、线程池隔离阻塞式 SSH 探测' },
  { name: '智能层', tech: 'DeepSeek Function Calling', desc: '中文意图理解 → 工具选择与参数抽取 → 结论生成' },
  { name: '协议层', tech: 'MCP Client（stdio 子进程）', desc: 'JSON-RPC 握手、工具清单、call_tool 封装与超时兜底' },
  { name: '工具层', tech: 'MCP Server（FastMCP）', desc: 'get_topology / query_device / monitor_traffic / configure_interface' },
  { name: '设备层', tech: 'SSH（Paramiko）→ VyOS', desc: '只读命令白名单，写操作在 Agent 侧安全门拦截' },
]

const mcpTools = computed(() => store.mcp.tools || [])

onMounted(async () => {
  try {
    health.value = await (await import('@/api')).default.health()
  } catch (exception) {
    error.value = exception.message
  }
})
</script>

<template>
  <div class="space-y-8">
    <!-- 介绍 -->
    <section class="glass glass-hover rise-in relative overflow-hidden p-6 lg:p-8">
      <div class="relative flex flex-wrap items-center gap-5">
        <span class="tile tile-ink h-14 w-14 rounded-2xl">
          <AppIcon name="zap" :size="26" />
        </span>
        <div class="min-w-0">
          <p class="kicker">About · 系统说明</p>
          <h1 class="display mt-2 text-2xl">AIOps 智能运维控制台</h1>
          <p class="mt-1 text-xs leading-relaxed text-[var(--color-ink-soft)]">
            用中文对话完成网络巡检：前端 → FastAPI → MCP(stdio) → SSH → VyOS，由 DeepSeek 负责理解与总结。
            本页展示系统架构、接口清单与运行状态。
          </p>
        </div>
        <div class="ml-auto flex flex-col gap-1 text-[11px]">
          <span class="glass-soft px-3 py-1.5">
            后端地址 <span class="mono">{{ BASE_URL }}</span>
          </span>
          <span class="glass-soft px-3 py-1.5">
            MCP 工具 <span class="mono">{{ mcpTools.join(' / ') || '-' }}</span>
          </span>
          <span class="glass-soft px-3 py-1.5">
            健康检查 <span class="mono">{{ health?.status || (error ? '不可达' : '检查中…') }}</span>
          </span>
        </div>
      </div>
      <p v-if="error" class="relative mt-3 text-xs text-[var(--tone-bad)]">{{ error }}</p>
    </section>

    <!-- 架构分层 -->
    <section class="glass glass-hover p-6">
      <h2 class="display flex items-center gap-2 text-lg">
        <AppIcon name="layers" :size="17" />系统架构（自上而下 6 层）
      </h2>
      <div class="mt-3 space-y-2">
        <div
          v-for="(layer, index) in layers"
          :key="layer.name"
          class="glass-soft flex flex-wrap items-center gap-3 px-3 py-2.5 rise-in"
          :style="{ animationDelay: `${index * 70}ms` }"
        >
          <span
            class="mono grid h-7 w-7 flex-none place-items-center rounded-lg text-xs font-bold text-white"
            :style="{ background: `hsl(${214 + index * 5} 68% ${52 - index * 2}%)` }"
          >
            {{ index + 1 }}
          </span>
          <span class="w-16 flex-none text-xs font-bold">{{ layer.name }}</span>
          <span class="mono text-[11px] text-[var(--color-ink-soft)]">{{ layer.tech }}</span>
          <span class="ml-auto text-[11px] text-[var(--color-ink-soft)]">{{ layer.desc }}</span>
        </div>
      </div>
    </section>

    <!-- 接口清单 -->
    <section class="glass glass-hover p-6">
      <h2 class="display flex items-center gap-2 text-lg">
        <AppIcon name="terminal" :size="17" />REST 接口清单（FastAPI）
      </h2>
      <div class="mt-3 overflow-x-auto">
        <table class="w-full min-w-[640px] border-separate border-spacing-y-1.5 text-left text-xs">
          <tbody>
            <tr v-for="item in endpoints" :key="item.path" class="glass-soft">
              <td class="px-3 py-2">
                <span
                  class="mono rounded-md px-2 py-0.5 text-[10px] font-bold"
                  :class="item.method === 'POST' ? 'bg-[var(--chip-pink-bg)] text-[var(--chip-pink-fg)]' : 'bg-[var(--chip-info-bg)] text-[var(--chip-info-fg)]'"
                >
                  {{ item.method }}
                </span>
              </td>
              <td class="mono px-3 py-2 font-semibold">{{ item.path }}</td>
              <td class="px-3 py-2 text-[var(--color-ink-soft)]">{{ item.desc }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="mt-2 text-[11px] text-[var(--color-ink-soft)]">
        完整 OpenAPI 文档：<span class="mono">{{ BASE_URL }}/docs</span>
      </p>
    </section>

    <!-- 请求链路 -->
    <section class="glass glass-hover p-6">
      <h2 class="display flex items-center gap-2 text-lg">
        <AppIcon name="activity" :size="17" />「查一下 R1 的 eth0 流量」全链路
      </h2>
      <div class="mt-3 flex flex-wrap items-center gap-2 text-[11px]">
        <span v-for="(step, index) in ['前端输入', 'POST /api/chat', 'DeepSeek 选工具', 'MCP stdio 调用', 'SSH 到 VyOS', '原始回显', 'DeepSeek 生成结论', 'Markdown 渲染']" :key="step" class="flex items-center gap-2">
          <span class="glass-soft px-3 py-1.5 font-semibold">{{ step }}</span>
          <AppIcon v-if="index < 7" name="chevron" :size="12" class="text-[var(--color-ink-soft)]" />
        </span>
      </div>
      <ul class="mt-3 space-y-1 text-[11px] text-[var(--color-ink-soft)]">
        <li>· 只读工具：<span class="mono">get_topology</span> / <span class="mono">query_device</span> / <span class="mono">monitor_traffic</span>，设备侧仅执行 show 类命令。</li>
        <li>· 写操作（<span class="mono">configure_interface</span>）由 Agent 安全门拦截，返回待审批任务而不直接下发。</li>
        <li>· 每次工具调用都写入 SQLite 审计日志，可在「审计日志」页追溯。</li>
        <li>· CORS 开发阶段允许所有来源，且前端 <span class="mono">withCredentials=false</span>（与 <span class="mono">*</span> 搭配才合法）。</li>
      </ul>
    </section>
  </div>
</template>
