<script setup>
/**
 * 控制台首页（概览）
 * --------------------------------------------------------------------------
 * 版面顺序（自上而下，全部走「大留白 + 分区标题」的日式极简排版）：
 *   1) Hero      —— 衬线大标题 + 一句话健康结论 + 元信息
 *   2) 关键指标  —— 4 张立体层叠卡片（Brand Appart 风）
 *   3) 网络拓扑 + AI 运维对话
 *   4) 流量监控
 *   5) 数据来源说明
 */
import { computed } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import ChatPanel from '@/components/ChatPanel.vue'
import StatCard from '@/components/StatCard.vue'
import TopologyGraph from '@/components/TopologyGraph.vue'
import TrafficChart from '@/components/TrafficChart.vue'
import { useConsoleStore } from '@/stores/console'

const store = useConsoleStore()

// 顶部 4 个数据卡片（渐变 + 数字滚动动画在 StatCard 内部实现）
const cards = computed(() => [
  {
    label: '纳管设备',
    value: store.stats.devices_total,
    icon: 'server',
    tone: 'blue',
    hint: `inventory.json · ${store.deviceNames.join(' / ') || '-'}`,
    delay: 0,
  },
  {
    label: '在线设备',
    value: store.stats.devices_online,
    icon: 'wifi',
    tone: 'green',
    hint: store.offlineDevices.length
      ? `离线：${store.offlineDevices.map((item) => item.name).join('、')}`
      : '全部在线',
    delay: 90,
  },
  {
    label: '未确认告警',
    value: store.stats.alerts_active,
    icon: 'alert',
    tone: 'rose',
    hint: `历史告警共 ${store.stats.alerts_total} 条`,
    delay: 180,
  },
  {
    label: '审计记录',
    value: store.stats.audit_total,
    icon: 'clipboard',
    tone: 'amber',
    hint: `失败 ${store.stats.audit_failed} 条 · 探测于 ${store.deviceMeta.checked_at || '-'}`,
    delay: 270,
  },
])

// Hero 的一句话结论：把「现在到底正不正常」直接写出来，不用看数字
const headline = computed(() => {
  if (!store.backendOnline) return '后端未连接，正在按 15s 节奏重试。请确认 FastAPI 已在 :8000 启动。'
  if (!store.mcp.connected) return '后端在线，但 MCP 客户端尚未连通，AI 工具链路暂不可用。'
  if (store.stats.alerts_active > 0) {
    return `系统在线，有 ${store.stats.alerts_active} 条告警待确认；可让右下角的看板娘或直接对话让 AI 给出处置建议。`
  }
  return '系统在线，设备、MCP 工具与审计链路均正常。'
})
</script>

<template>
  <div class="space-y-10">
    <!-- 1) Hero -->
    <section class="glass rise-in overflow-hidden">
      <div class="flex flex-wrap items-end gap-x-10 gap-y-6 p-6 lg:p-8">
        <div class="min-w-0 flex-1">
          <p class="kicker">Network Operations · 实时概览</p>
          <h1 class="display mt-3 text-3xl sm:text-4xl">网络运行概览</h1>
          <p class="mt-4 max-w-[54ch] text-sm leading-relaxed text-[var(--color-ink-soft)]">
            {{ headline }}
          </p>
        </div>

        <dl class="flex flex-wrap gap-x-10 gap-y-4 text-xs">
          <div>
            <dt class="kicker">Last Probe</dt>
            <dd class="mono mt-1.5">{{ store.deviceMeta.checked_at || '-' }}</dd>
          </div>
          <div>
            <dt class="kicker">Refresh</dt>
            <dd class="mono mt-1.5">设备 15s · 流量 5s</dd>
          </div>
          <div>
            <dt class="kicker">Transport</dt>
            <dd class="mono mt-1.5">MCP {{ store.mcp.transport || 'stdio' }}</dd>
          </div>
        </dl>
      </div>

      <div
        class="flex flex-wrap items-center gap-2 border-t border-[var(--hairline)] px-6 py-3 text-[11px] text-[var(--color-ink-soft)] lg:px-8"
      >
        <span class="dot" :class="store.backendOnline ? 'dot-online' : 'dot-offline'" />
        {{ store.deviceMeta.online }}/{{ store.deviceMeta.total }} 设备在线
        <span class="mx-1 opacity-40">|</span>
        <span class="mono">GET /api/devices · /api/stats · /api/traffic · POST /api/chat</span>
      </div>
    </section>

    <!-- 2) 关键指标 -->
    <section>
      <div class="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p class="kicker">Overview</p>
          <h2 class="display mt-1.5 text-xl">关键指标</h2>
        </div>
        <p class="text-[11px] text-[var(--color-ink-soft)]">数值变化时会滚动到新值，无需手动刷新</p>
      </div>
      <div class="grid grid-cols-2 gap-6 xl:grid-cols-4">
        <StatCard v-for="card in cards" :key="card.label" v-bind="card" />
      </div>
    </section>

    <!-- 3) 拓扑 + AI 对话 -->
    <section>
      <div class="mb-6">
        <p class="kicker">Live View</p>
        <h2 class="display mt-1.5 text-xl">拓扑与对话</h2>
      </div>
      <div class="grid gap-8 xl:grid-cols-2">
        <TopologyGraph />
        <ChatPanel />
      </div>
    </section>

    <!-- 4) 流量监控 -->
    <section>
      <div class="mb-6">
        <p class="kicker">Traffic</p>
        <h2 class="display mt-1.5 text-xl">接口流量</h2>
      </div>
      <TrafficChart />
    </section>

    <!-- 5) 数据来源 -->
    <div class="glass flex flex-wrap items-center gap-3 px-5 py-4 text-[11px] text-[var(--color-ink-soft)]">
      <span class="tile tile-tint h-8 w-8">
        <AppIcon name="database" :size="15" />
      </span>
      <span>
        数据来源：<span class="mono">GET /api/devices</span>、<span class="mono">/api/stats</span>、
        <span class="mono">/api/traffic</span>、<span class="mono">POST /api/chat</span> ·
        设备状态每 15s 刷新，流量每 5s 采样
      </span>
    </div>
  </div>
</template>
