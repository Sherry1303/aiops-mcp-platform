<script setup>
import { computed, onMounted, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import api from '@/api'
import { useConsoleStore } from '@/stores/console'

const store = useConsoleStore()

const filters = ref({ status: '', device: '', keyword: '', limit: 20, offset: 0 })
const logs = ref([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const acking = ref(0)

const page = computed(() => Math.floor(filters.value.offset / filters.value.limit) + 1)
const pages = computed(() => Math.max(1, Math.ceil(total.value / filters.value.limit)))

function statusStyle(status) {
  if (status === 'SUCCESS') return 'bg-[var(--chip-ok-bg)] text-[var(--chip-ok-fg)]'
  if (status === 'FAILED') return 'bg-[var(--chip-bad-bg)] text-[var(--chip-bad-fg)]'
  return 'bg-[var(--chip-warn-bg)] text-[var(--chip-warn-fg)]'
}

function levelStyle(level) {
  if (level === 'P0') return 'bg-[var(--chip-bad-bg)] text-[var(--chip-bad-fg)]'
  if (level === 'P1') return 'bg-[var(--chip-warn-bg)] text-[var(--chip-warn-fg)]'
  return 'bg-[var(--chip-info-bg)] text-[var(--chip-info-fg)]'
}

async function load(offset = 0) {
  loading.value = true
  error.value = ''
  filters.value.offset = offset
  try {
    const params = { limit: filters.value.limit, offset }
    if (filters.value.status) params.status = filters.value.status
    if (filters.value.device) params.device = filters.value.device
    if (filters.value.keyword) params.keyword = filters.value.keyword
    const data = await api.auditLogs(params)
    logs.value = data.items || []
    total.value = data.total || 0
  } catch (exception) {
    error.value = exception.message
  } finally {
    loading.value = false
  }
}

async function ack(alert) {
  acking.value = alert.id
  try {
    await api.ackAlert(alert.id, 'Web 控制台确认')
    await Promise.all([store.loadAlerts(), store.loadStats()])
  } catch (exception) {
    error.value = exception.message
  } finally {
    acking.value = 0
  }
}

function exportCsv() {
  const header = 'timestamp,device,action,details,status\n'
  const rows = logs.value
    .map((row) =>
      [row.timestamp, row.device_name, row.action, row.details, row.status]
        .map((field) => `"${String(field ?? '').replace(/"/g, '""')}"`)
        .join(','),
    )
    .join('\n')
  const blob = new Blob([`\uFEFF${header}${rows}`], { type: 'text/csv;charset=utf-8' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `audit-logs-${Date.now()}.csv`
  link.click()
  URL.revokeObjectURL(link.href)
}

onMounted(() => {
  load(0)
  store.loadAlerts()
})
</script>

<template>
  <div class="space-y-8">
    <!-- 筛选栏 -->
    <div class="glass glass-hover p-5">
      <div class="flex flex-wrap items-center gap-3">
        <span class="tile tile-tint h-9 w-9">
          <AppIcon name="clipboard" :size="17" />
        </span>
        <div class="leading-tight">
          <h2 class="display text-lg">操作审计日志</h2>
          <p class="text-[11px] text-[var(--color-ink-soft)]">
            SQLite（audit.db）· 共 {{ total }} 条 · 第 {{ page }}/{{ pages }} 页
          </p>
        </div>

        <div class="ml-auto flex flex-wrap items-center gap-2">
          <select v-model="filters.status" class="input-soft w-28 py-1.5 text-xs" @change="load(0)">
            <option value="">全部状态</option>
            <option value="SUCCESS">SUCCESS</option>
            <option value="FAILED">FAILED</option>
          </select>
          <select v-model="filters.device" class="input-soft w-28 py-1.5 text-xs" @change="load(0)">
            <option value="">全部设备</option>
            <option v-for="name in store.deviceNames" :key="name" :value="name">{{ name }}</option>
          </select>
          <input
            v-model="filters.keyword"
            class="input-soft w-44 py-1.5 text-xs"
            placeholder="关键字（动作/详情）"
            @keyup.enter="load(0)"
          />
          <button class="btn-gradient px-4 py-1.5 text-xs font-bold" @click="load(0)">
            <AppIcon name="search" :size="13" class="mr-1 inline" />查询
          </button>
          <button class="btn-ghost px-3 py-1.5 text-xs font-semibold" @click="exportCsv">
            <AppIcon name="download" :size="13" class="mr-1 inline" />导出 CSV
          </button>
        </div>
      </div>

      <p v-if="error" class="mt-3 text-xs text-[var(--tone-bad)]">{{ error }}</p>

      <!-- 表格 -->
      <div class="mt-6 overflow-x-auto">
        <table class="w-full min-w-[720px] border-separate border-spacing-y-1.5 text-left text-xs">
          <thead class="text-[11px] uppercase tracking-wide text-[var(--color-ink-soft)]">
            <tr>
              <th class="px-3 py-1.5">时间</th>
              <th class="px-3 py-1.5">设备</th>
              <th class="px-3 py-1.5">动作</th>
              <th class="px-3 py-1.5">详情</th>
              <th class="px-3 py-1.5">状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading">
              <td colspan="5" class="px-3 py-6 text-center text-[var(--color-ink-soft)]">加载中…</td>
            </tr>
            <tr v-else-if="!logs.length">
              <td colspan="5" class="px-3 py-6 text-center text-[var(--color-ink-soft)]">暂无审计记录</td>
            </tr>
            <tr
              v-for="row in logs"
              :key="row.id"
              class="glass-soft transition-all duration-200 hover:-translate-y-0.5"
            >
              <td class="mono px-3 py-2 whitespace-nowrap">{{ row.timestamp }}</td>
              <td class="px-3 py-2 font-semibold">{{ row.device_name }}</td>
              <td class="px-3 py-2">{{ row.action }}</td>
              <td class="max-w-[420px] px-3 py-2 text-[var(--color-ink-soft)]">
                <span class="line-clamp-2">{{ row.details }}</span>
              </td>
              <td class="px-3 py-2">
                <span class="rounded-full px-2 py-0.5 text-[10px] font-bold" :class="statusStyle(row.status)">
                  {{ row.status }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 分页 -->
      <div class="mt-6 flex items-center justify-center gap-2 text-xs">
        <button class="btn-ghost px-3 py-1.5" :disabled="page <= 1" @click="load(0)">首页</button>
        <button
          class="btn-ghost px-3 py-1.5"
          :disabled="page <= 1"
          @click="load(Math.max(0, filters.offset - filters.limit))"
        >
          上一页
        </button>
        <span class="mono px-2 text-[var(--color-ink-soft)]">{{ page }} / {{ pages }}</span>
        <button
          class="btn-ghost px-3 py-1.5"
          :disabled="page >= pages"
          @click="load(filters.offset + filters.limit)"
        >
          下一页
        </button>
        <button class="btn-ghost px-3 py-1.5" :disabled="page >= pages" @click="load((pages - 1) * filters.limit)">
          末页
        </button>
        <select v-model.number="filters.limit" class="input-soft ml-2 w-24 py-1.5 text-xs" @change="load(0)">
          <option :value="20">20 条/页</option>
          <option :value="50">50 条/页</option>
          <option :value="100">100 条/页</option>
        </select>
      </div>
    </div>

    <!-- 告警中心 -->
    <div class="glass glass-hover p-5">
      <div class="flex flex-wrap items-center gap-3">
        <span class="tile tile-rose h-9 w-9">
          <AppIcon name="alert" :size="17" />
        </span>
        <div class="leading-tight">
          <h2 class="display text-lg">告警中心</h2>
          <p class="text-[11px] text-[var(--color-ink-soft)]">
            P0 设备不可达 · P1 指标异常 · P2 提示性告警
          </p>
        </div>
        <div class="ml-auto flex flex-wrap items-center gap-1.5 text-[11px]">
          <span
            v-for="level in ['P0', 'P1', 'P2']"
            :key="level"
            class="glass-soft px-2 py-1 font-semibold"
          >
            <span class="rounded-full px-1.5 py-0.5 text-[10px] font-bold" :class="levelStyle(level)">
              {{ level }}
            </span>
            未确认 {{ store.alertStats[level]?.ACTIVE ?? 0 }}
          </span>
        </div>
      </div>

      <ul class="mt-5 space-y-2">
        <li v-if="!store.alerts.length" class="glass-soft px-3 py-4 text-center text-xs text-[var(--color-ink-soft)]">
          暂无告警
        </li>
        <li
          v-for="alert in store.alerts"
          :key="alert.id"
          class="glass-soft flex flex-wrap items-center gap-2 px-3 py-2 text-xs"
        >
          <span class="rounded-full px-2 py-0.5 text-[10px] font-bold" :class="levelStyle(alert.level)">
            {{ alert.level }}
          </span>
          <span class="font-semibold">{{ alert.device_name }}</span>
          <span class="min-w-0 flex-1 truncate text-[var(--color-ink-soft)]">{{ alert.message }}</span>
          <span class="mono text-[10px] text-[var(--color-ink-soft)]">{{ alert.timestamp }}</span>
          <span
            class="rounded-full px-2 py-0.5 text-[10px] font-bold"
            :class="alert.status === 'ACTIVE' ? 'bg-[var(--chip-warn-bg)] text-[var(--chip-warn-fg)]' : 'bg-[var(--chip-ok-bg)] text-[var(--chip-ok-fg)]'"
          >
            {{ alert.status === 'ACTIVE' ? '未确认' : '已确认' }}
          </span>
          <button
            v-if="alert.status === 'ACTIVE'"
            class="btn-gradient px-3 py-1 text-[11px] font-bold"
            :disabled="acking === alert.id"
            @click="ack(alert)"
          >
            {{ acking === alert.id ? '处理中…' : '确认' }}
          </button>
          <span v-else-if="alert.note" class="text-[10px] text-[var(--color-ink-soft)]">备注：{{ alert.note }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>
