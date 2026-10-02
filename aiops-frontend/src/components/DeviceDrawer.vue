<script setup>
import { computed } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { useConsoleStore } from '@/stores/console'

const store = useConsoleStore()

const open = computed(() => !!store.selected)
const device = computed(() => store.selectedDevice)
const detail = computed(() => store.detail || {})
const rawKeys = computed(() => Object.keys(detail.value.raw || {}))

const metrics = computed(() => {
  const d = detail.value
  if (!d || !Object.keys(d).length) return []
  return [
    { label: '系统版本', value: d.version || '-', mono: true },
    { label: '接口', value: `${d.interface || 'eth0'}` },
    { label: '链路状态', value: d.state || '-', tone: d.state === 'UP' ? 'ok' : 'bad' },
    { label: '接口地址', value: d.address || '-', mono: true },
    { label: 'RX 字节', value: formatNumber(d.rx_bytes) },
    { label: 'TX 字节', value: formatNumber(d.tx_bytes) },
    { label: '错误包', value: `${d.rx_errors || 0} / ${d.tx_errors || 0}`, tone: (d.rx_errors || d.tx_errors) ? 'bad' : 'ok' },
    { label: '运行时长', value: d.uptime || '-' },
    { label: 'CPU 负载', value: d.cpu_percent != null ? `${d.cpu_percent}%` : '-' },
    {
      label: '内存',
      value: d.memory_percent != null
        ? `${d.memory_percent}%（${formatNumber(d.memory_used_mb)}/${formatNumber(d.memory_total_mb)} MB）`
        : '-',
    },
  ]
})

function formatNumber(value) {
  if (value === null || value === undefined || value === '') return '-'
  return Number(value).toLocaleString('en-US')
}

function showInTrafficChart() {
  store.setTrafficTarget(store.selected, 'eth0')
  if (!store.traffic.live) store.toggleTrafficLive()
  store.clearSelection()
}
</script>

<template>
  <transition name="drawer">
    <div v-if="open" class="fixed inset-0 z-40 flex justify-end">
      <div class="absolute inset-0 bg-[var(--overlay-bg)] backdrop-blur-[2px]" @click="store.clearSelection()" />

      <aside class="glass pop-in relative h-full w-full max-w-[460px] overflow-y-auto rounded-l-[22px] p-6">
        <!-- 头部 -->
        <div class="flex items-start gap-3">
          <span class="tile tile-ink h-11 w-11 rounded-2xl">
            <AppIcon name="server" :size="22" />
          </span>
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <h3 class="display truncate text-xl">{{ store.selected }}</h3>
              <span class="dot" :class="device?.online ? 'dot-online' : 'dot-offline'" />
              <span class="text-xs font-semibold" :class="device?.online ? 'text-[var(--tone-ok)]' : 'text-[var(--tone-bad)]'">
                {{ device?.online ? '在线' : '离线' }}
              </span>
            </div>
            <p class="mono truncate text-xs text-[var(--color-ink-soft)]">
              {{ device?.ip }} · {{ device?.role }} · SSH {{ device?.port }}
            </p>
          </div>
          <button class="btn-ghost ml-auto px-2 py-1.5" @click="store.clearSelection()">
            <AppIcon name="close" :size="16" />
          </button>
        </div>

        <p v-if="device?.error" class="glass-soft mt-3 px-3 py-2 text-xs text-[var(--tone-bad)]">
          {{ device.error }}
        </p>

        <!-- 指标 -->
        <div v-if="store.detailLoading" class="mt-6 text-center text-sm text-[var(--color-ink-soft)]">
          正在经 MCP → SSH 采集只读指标…
        </div>
        <dl v-else class="mt-4 grid grid-cols-2 gap-2">
          <div v-for="item in metrics" :key="item.label" class="glass-soft px-3 py-2">
            <dt class="text-[11px] text-[var(--color-ink-soft)]">{{ item.label }}</dt>
            <dd
              class="truncate text-sm font-semibold"
              :class="[item.mono ? 'mono' : '', item.tone === 'ok' ? 'text-[var(--tone-ok)]' : item.tone === 'bad' ? 'text-[var(--tone-bad)]' : '']"
            >
              {{ item.value }}
            </dd>
          </div>
        </dl>

        <!-- 原始输出 -->
        <div v-if="rawKeys.length" class="mt-4 space-y-2">
          <p class="text-xs font-bold text-[var(--color-ink-soft)]">MCP 原始命令输出</p>
          <details v-for="key in rawKeys" :key="key" class="glass-soft px-3 py-2">
            <summary class="cursor-pointer text-xs font-semibold">{{ key }}</summary>
            <pre class="mono mt-2 max-h-60 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-[var(--color-ink-soft)]">{{ detail.raw[key] }}</pre>
          </details>
        </div>

        <!-- 操作 -->
        <div class="mt-5 flex gap-2">
          <button class="btn-gradient px-4 py-2 text-xs font-bold" @click="store.loadDetail(store.selected)">
            重新采集
          </button>
          <button class="btn-ghost px-4 py-2 text-xs font-semibold" @click="showInTrafficChart">
            在流量图查看 eth0
          </button>
        </div>
        <p class="mt-3 text-[11px] text-[var(--color-ink-soft)]">
          采集时间：<span class="mono">{{ detail.collected_at || '-' }}</span>
        </p>
      </aside>
    </div>
  </transition>
</template>

<style scoped>
.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 0.25s ease;
}

.drawer-enter-active aside,
.drawer-leave-active aside {
  transition: transform 0.3s cubic-bezier(0.22, 1, 0.36, 1);
}

.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}

.drawer-enter-from aside,
.drawer-leave-to aside {
  transform: translateX(40px);
}
</style>
