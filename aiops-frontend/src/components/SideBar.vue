<script setup>
/**
 * 设备清单（左侧栏）
 * --------------------------------------------------------------------------
 * 新增能力（本轮「更多功能」的一部分）：
 *   · 关键字搜索：设备名 / IP / 角色，输入即过滤，不需要等后端
 *   · 状态筛选：全部 / 在线 / 离线，便于快速聚焦异常设备
 * 视觉：纸片卡片 + 发丝分隔线，去掉厚重描边，列表项用左侧蓝色指示条表示选中。
 */
import { computed, ref } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { useConsoleStore } from '@/stores/console'

const store = useConsoleStore()

const keyword = ref('')
const only = ref('all') // all | online | offline

const filters = [
  { key: 'all', label: '全部' },
  { key: 'online', label: '在线' },
  { key: 'offline', label: '离线' },
]

const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  return (store.devices || []).filter((device) => {
    if (only.value === 'online' && !device.online) return false
    if (only.value === 'offline' && device.online) return false
    if (!text) return true
    return [device.name, device.ip, device.role].some((field) =>
      String(field || '').toLowerCase().includes(text),
    )
  })
})
</script>

<template>
  <aside class="glass sticky top-24 max-h-[calc(100vh-7rem)] overflow-hidden p-5">
    <div class="flex items-center justify-between">
      <div>
        <p class="kicker">Devices</p>
        <h2 class="display mt-1.5 text-lg">设备清单</h2>
      </div>
      <span class="glass-soft mono px-2.5 py-1 text-[11px] font-semibold text-[var(--color-ink-soft)]">
        {{ store.deviceMeta.online }}/{{ store.deviceMeta.total }}
      </span>
    </div>

    <!-- 搜索：设备名 / IP / 角色 -->
    <label class="mt-4 flex items-center gap-2 rounded-xl border border-[var(--control-border)] bg-[var(--control-bg)] px-3 py-2">
      <AppIcon name="search" :size="14" class="flex-none text-[var(--color-ink-faint)]" />
      <input
        v-model="keyword"
        class="min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-[var(--color-ink-faint)]"
        placeholder="搜索设备 / IP / 角色"
        aria-label="搜索设备"
      />
      <button
        v-if="keyword"
        class="flex-none text-[var(--color-ink-faint)] hover:text-[var(--color-ink)]"
        aria-label="清空搜索"
        @click="keyword = ''"
      >
        <AppIcon name="close" :size="13" />
      </button>
    </label>

    <!-- 状态筛选 -->
    <div class="mt-3 flex items-center gap-1.5">
      <button
        v-for="item in filters"
        :key="item.key"
        class="rounded-full px-3 py-1 text-[11px] font-semibold transition-colors duration-200"
        :class="
          only === item.key
            ? 'bg-[var(--pill-active-bg)] text-[var(--pill-active-fg)]'
            : 'text-[var(--color-ink-soft)] hover:bg-[var(--pill-hover-bg)]'
        "
        @click="only = item.key"
      >
        {{ item.label }}
      </button>
      <span v-if="keyword || only !== 'all'" class="mono ml-auto text-[10px] text-[var(--color-ink-faint)]">
        {{ filtered.length }} 条结果
      </span>
    </div>

    <!-- 设备列表：实时在线状态用彩色圆点表示 -->
    <ul class="mt-3 max-h-[calc(100vh-26rem)] overflow-y-auto pr-1">
      <li v-if="!filtered.length" class="px-1 py-8 text-center text-xs text-[var(--color-ink-soft)]">
        {{ store.devicesLoading ? '正在 SSH 探测设备…' : '没有匹配的设备' }}
      </li>
      <li v-for="device in filtered" :key="device.name" class="border-t border-[var(--hairline)] last:border-b">
        <button
          class="relative w-full px-3 py-3 text-left transition-colors duration-200 hover:bg-[var(--row-hover-bg)]"
          :class="store.selected === device.name ? 'bg-[var(--row-active-bg)]' : ''"
          @click="store.selectDevice(device.name)"
        >
          <span
            v-if="store.selected === device.name"
            class="absolute left-0 top-2 bottom-2 w-[3px] rounded-full bg-[var(--accent)]"
          />
          <div class="flex items-center gap-2">
            <span class="dot" :class="device.online ? 'dot-online' : 'dot-offline'" />
            <span class="text-sm font-bold">{{ device.name }}</span>
            <span class="mono ml-auto text-[11px] text-[var(--color-ink-soft)]">
              {{ device.online ? `${device.latency_ms ?? '-'}ms` : '离线' }}
            </span>
          </div>
          <p class="mono mt-1.5 truncate text-[11px] text-[var(--color-ink-soft)]">
            {{ device.ip }} · {{ device.role }}
          </p>
          <p
            class="mt-0.5 truncate text-[11px]"
            :class="device.online ? 'text-[var(--tone-ok)]' : 'text-[var(--tone-bad)]'"
          >
            {{ device.online ? device.version : device.error || '不可达' }}
          </p>
        </button>
      </li>
    </ul>

    <div class="mt-4 border-t border-[var(--hairline)] pt-4 text-[11px] text-[var(--color-ink-soft)]">
      <p class="flex items-center gap-1.5">
        <AppIcon name="gauge" :size="12" />
        探测于 <span class="mono">{{ store.deviceMeta.checked_at || '-' }}</span>
        <span v-if="store.deviceMeta.cached">（缓存）</span>
      </p>
      <p class="mt-1.5">点击设备查看详情 · 每 15s 自动刷新</p>
    </div>
  </aside>
</template>
