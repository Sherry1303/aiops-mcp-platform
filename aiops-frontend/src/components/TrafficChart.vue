<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import * as echarts from 'echarts'

import AppIcon from '@/components/AppIcon.vue'
import { useConsoleStore } from '@/stores/console'
import { chartTheme } from '@/theme'

const store = useConsoleStore()
const chartRef = ref(null)

let chart = null
let resizeObserver = null

const latest = computed(() => store.traffic.latest || {})
const interfaces = ['eth0', 'eth1', 'eth2', 'lo']

function areaGradient(rgb) {
  return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: `rgba(${rgb},0.5)` },
    { offset: 1, color: `rgba(${rgb},0)` },
  ])
}

function buildOption() {
  const points = store.traffic.points
  // 坐标轴/浮层配色随全局主题（--chart-* 令牌）联动
  const theme = chartTheme()
  return {
    backgroundColor: 'transparent',
    grid: { left: 56, right: 20, top: 34, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText, fontSize: 12 },
      valueFormatter: (value) => `${value} Mbps`,
    },
    legend: {
      top: 0,
      right: 0,
      icon: 'roundRect',
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { color: theme.axis, fontSize: 11 },
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: points.map((point) => point.time),
      axisLine: { lineStyle: { color: theme.axisLine } },
      axisLabel: { color: theme.axis, fontSize: 10, fontFamily: 'JetBrains Mono' },
    },
    yAxis: {
      type: 'value',
      name: 'Mbps',
      nameTextStyle: { color: theme.axis, fontSize: 10 },
      splitLine: { lineStyle: { color: theme.split } },
      axisLabel: { color: theme.axis, fontSize: 10, fontFamily: 'JetBrains Mono' },
    },
    series: [
      {
        name: 'RX 入向',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        data: points.map((point) => point.rx),
        lineStyle: { width: 2.5, color: '#2f6fed' },
        itemStyle: { color: '#2f6fed' },
        areaStyle: { color: areaGradient('47,111,237') },
      },
      {
        name: 'TX 出向',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        data: points.map((point) => point.tx),
        lineStyle: { width: 2.5, color: '#c2417e' },
        itemStyle: { color: '#c2417e' },
        areaStyle: { color: areaGradient('194,65,126') },
      },
    ],
  }
}

function render() {
  if (chart) chart.setOption(buildOption(), true)
}

function onDeviceChange(event) {
  store.setTrafficTarget(event.target.value, store.traffic.interface)
  store.sampleTraffic(true)
}

function onInterfaceChange(event) {
  store.setTrafficTarget(store.traffic.device, event.target.value)
  store.sampleTraffic(true)
}

onMounted(() => {
  chart = echarts.init(chartRef.value)
  render()
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(chartRef.value)
  // 进入页面自动开始实时采样（5s 一次，每次经 MCP → SSH 采样两遍算速率）
  if (!store.traffic.live) store.toggleTrafficLive()
  else store.sampleTraffic(true)
})

watch(
  () => store.traffic.points,
  () => render(),
  { deep: true },
)

onBeforeUnmount(() => {
  store.stopTrafficPolling()
  resizeObserver?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="glass glass-hover p-4">
    <!-- 标题 + 控制 -->
    <div class="flex flex-wrap items-center gap-3">
      <span class="tile tile-tint h-9 w-9">
        <AppIcon name="chart" :size="17" />
      </span>
      <div class="leading-tight">
        <h2 class="display text-lg">流量监控</h2>
        <p class="text-[11px] text-[var(--color-ink-soft)]">
          两次采样差值换算 Mbps ·
          <span :class="store.traffic.live ? 'text-[var(--tone-ok)]' : ''">
            {{ store.traffic.live ? `实时采样中（5s）` : '已暂停' }}
          </span>
        </p>
      </div>

      <div class="ml-auto flex flex-wrap items-center gap-2">
        <select class="input-soft mono w-28 py-1.5 text-xs" :value="store.traffic.device" @change="onDeviceChange">
          <option v-for="name in store.deviceNames" :key="name" :value="name">{{ name }}</option>
        </select>
        <select class="input-soft mono w-24 py-1.5 text-xs" :value="store.traffic.interface" @change="onInterfaceChange">
          <option v-for="iface in interfaces" :key="iface" :value="iface">{{ iface }}</option>
        </select>
        <button
          class="btn-gradient flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold"
          :disabled="store.traffic.loading"
          @click="store.sampleTraffic(true)"
        >
          <AppIcon name="refresh" :size="13" />
          {{ store.traffic.loading ? '采集中…' : '立即采样' }}
        </button>
        <button class="btn-ghost flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold" @click="store.toggleTrafficLive()">
          <AppIcon :name="store.traffic.live ? 'pause' : 'play'" :size="13" />
          {{ store.traffic.live ? '暂停' : '实时' }}
        </button>
      </div>
    </div>

    <!-- 实时读数 -->
    <div class="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
      <div class="glass-soft px-3 py-2">
        <p class="text-[11px] text-[var(--color-ink-soft)]">RX 速率</p>
        <p class="mono text-lg font-bold text-[var(--tone-rx)]">
          {{ (latest.rx_mbps ?? 0).toFixed(3) }} <span class="text-xs font-normal">Mbps</span>
        </p>
      </div>
      <div class="glass-soft px-3 py-2">
        <p class="text-[11px] text-[var(--color-ink-soft)]">TX 速率</p>
        <p class="mono text-lg font-bold text-[var(--tone-tx)]">
          {{ (latest.tx_mbps ?? 0).toFixed(3) }} <span class="text-xs font-normal">Mbps</span>
        </p>
      </div>
      <div class="glass-soft px-3 py-2">
        <p class="text-[11px] text-[var(--color-ink-soft)]">累计 RX / TX</p>
        <p class="mono text-sm font-semibold">
          {{ (latest.rx_bytes ?? 0).toLocaleString('en-US') }} /
          {{ (latest.tx_bytes ?? 0).toLocaleString('en-US') }}
        </p>
      </div>
      <div class="glass-soft px-3 py-2">
        <p class="text-[11px] text-[var(--color-ink-soft)]">链路状态 · 错误包</p>
        <p class="mono text-sm font-semibold">
          <span :class="latest.state === 'UP' ? 'text-[var(--tone-ok)]' : 'text-[var(--tone-bad)]'">
            {{ latest.state || '-' }}
          </span>
          · {{ (latest.rx_errors ?? 0) + (latest.tx_errors ?? 0) }}
        </p>
      </div>
    </div>

    <div ref="chartRef" class="mt-2 h-[248px] w-full" />

    <p v-if="store.traffic.error" class="mt-1 text-center text-[11px] text-[var(--tone-bad)]">
      {{ store.traffic.error }}
    </p>
  </div>
</template>
