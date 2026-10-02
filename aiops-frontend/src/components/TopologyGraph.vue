<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import * as echarts from 'echarts'

import AppIcon from '@/components/AppIcon.vue'
import { useConsoleStore } from '@/stores/console'
import { chartTheme } from '@/theme'

const store = useConsoleStore()
const chartRef = ref(null)

let chart = null
let resizeObserver = null

// 依据角色划分层级：0 核心/路由 → 1 汇聚 → 2 接入（用于上下分层布局）
function tier(role = '') {
  if (/路由|核心|core|router/i.test(role)) return 0
  if (/汇聚|agg/i.test(role)) return 1
  if (/接入|access/i.test(role)) return 2
  return 1
}

function nodeGradient(online) {
  // 在线=抹茶绿、离线=樱红；两层同色系叠出一点体积感，但不再是荧光色渐变
  return online
    ? new echarts.graphic.LinearGradient(0, 0, 1, 1, [
        { offset: 0, color: '#4aa87a' },
        { offset: 1, color: '#2f8a5b' },
      ])
    : new echarts.graphic.LinearGradient(0, 0, 1, 1, [
        { offset: 0, color: '#e27084' },
        { offset: 1, color: '#c93a52' },
      ])
}

function buildOption() {
  const devices = store.devices
  // 坐标轴/浮层/连线配色随全局主题（--chart-* 令牌）联动
  const theme = chartTheme()
  const grouped = new Map()
  devices.forEach((device) => {
    const level = tier(device.role)
    if (!grouped.has(level)) grouped.set(level, [])
    grouped.get(level).push(device)
  })

  // 布局：同层横向居中排布，层间纵向间隔 200px（layout: 'none' 手动坐标）
  const nodes = []
  ;[...grouped.keys()].sort((a, b) => a - b).forEach((level) => {
    const list = grouped.get(level)
    list.forEach((device, index) => {
      nodes.push({
        name: device.name,
        x: (index - (list.length - 1) / 2) * 260,
        y: level * 200,
        symbol: 'roundRect',
        symbolSize: [124, 50],
        category: device.role,
        itemStyle: {
          color: nodeGradient(device.online),
          borderColor: 'rgba(255,255,255,0.9)',
          borderWidth: 1.5,
          shadowBlur: 18,
          shadowColor: device.online ? 'rgba(47,138,91,0.32)' : 'rgba(201,58,82,0.3)',
        },
        label: {
          show: true,
          position: 'inside',
          formatter: `{name|${device.name}}\n{meta|${device.ip}}`,
          rich: {
            name: { color: '#fff', fontSize: 13, fontWeight: 'bold', lineHeight: 19 },
            meta: { color: 'rgba(255,255,255,0.88)', fontSize: 10, fontFamily: 'JetBrains Mono' },
          },
        },
        device,
      })
    })
  })

  // 连线：按层级自上而下串联（inventory.json 未定义链路，这里按角色层级推断）
  const ordered = [...devices].sort(
    (a, b) => tier(a.role) - tier(b.role) || a.name.localeCompare(b.name),
  )
  const links = ordered.slice(0, -1).map((node, index) => ({
    source: node.name,
    target: ordered[index + 1].name,
  }))

  const categories = [...new Set(devices.map((device) => device.role))].map((role) => ({
    name: role,
    itemStyle: {
      color: devices.find((device) => device.role === role)?.online ? '#2f8a5b' : '#c93a52',
    },
  }))

  return {
    backgroundColor: 'transparent',
    tooltip: {
      backgroundColor: theme.tooltipBackground,
      borderColor: theme.tooltipBorder,
      borderWidth: 1,
      textStyle: { color: theme.tooltipText, fontSize: 12 },
      formatter: (params) => {
        if (params.dataType !== 'node') return `${params.data.source} → ${params.data.target}`
        const device = params.data.device || {}
        return [
          `<b>${device.name}</b> ${device.online ? '🟢 在线' : '🔴 离线'}`,
          `IP：${device.ip}`,
          `角色：${device.role}`,
          `版本：${device.version || '-'}`,
          `延迟：${device.online ? `${device.latency_ms ?? '-'} ms` : '-'}`,
        ].join('<br/>')
      },
    },
    legend: {
      bottom: 0,
      icon: 'circle',
      textStyle: { color: theme.axis, fontSize: 11 },
      data: categories.map((category) => category.name),
    },
    series: [
      {
        type: 'graph',
        layout: 'none',
        roam: true,
        draggable: true,
        symbol: 'roundRect',
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: 8,
        categories,
        lineStyle: { color: theme.link, width: 2, opacity: 0.65, curveness: 0.1 },
        emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
        data: nodes,
        links,
      },
    ],
  }
}

function render() {
  if (!chart) return
  chart.setOption(buildOption(), true)
}

onMounted(() => {
  chart = echarts.init(chartRef.value)
  chart.on('click', (params) => {
    if (params.dataType === 'node' && params.data?.name) {
      store.selectDevice(params.data.name)
    }
  })
  render()
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(chartRef.value)
})

watch(() => store.devices, render, { deep: true })

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="glass glass-hover flex h-full flex-col p-4">
    <div class="flex items-center gap-3">
      <span class="tile tile-tint h-9 w-9">
        <AppIcon name="topology" :size="17" />
      </span>
      <div class="leading-tight">
        <h2 class="display text-lg">网络拓扑</h2>
        <p class="text-[11px] text-[var(--color-ink-soft)]">
          在线绿色 · 离线红色 · 点击节点查看详情
        </p>
      </div>
      <span class="glass-soft ml-auto px-2 py-0.5 text-[11px] font-semibold text-[var(--color-ink-soft)]">
        {{ store.deviceMeta.online }}/{{ store.deviceMeta.total }} 在线
      </span>
    </div>

    <div ref="chartRef" class="mt-2 h-[390px] w-full" />

    <p class="mt-1 text-center text-[11px] text-[var(--color-ink-soft)]">
      inventory.json 未声明链路关系，连线按角色层级（核心 → 汇聚 → 接入）推断
    </p>
  </div>
</template>

