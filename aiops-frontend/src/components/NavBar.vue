<script setup>
/**
 * 顶栏（纸感 sticky header）
 * --------------------------------------------------------------------------
 * 极简版：品牌 + 运行状态 + 三个文字导航 + 时钟/刷新倒计时 + 「两横」菜单按钮。
 * 导航不再用图标 + 彩色胶囊，避免与页面里的功能卡片抢视觉（见 style.css 设计说明）。
 * ⌘/Ctrl + K 与菜单按钮都能打开 AppMenu。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import AppMenu from '@/components/AppMenu.vue'
import { useConsoleStore } from '@/stores/console'

// 与 stores/console.js 的 DEVICE_POLL_MS 保持一致（15s 自动刷新）
const POLL_SECONDS = 15

const store = useConsoleStore()

const menuOpen = ref(false)
const clock = ref('')
const countdown = ref(POLL_SECONDS)

const links = [
  { to: '/', label: '控制台' },
  { to: '/audit', label: '审计日志' },
  { to: '/about', label: '关于' },
]

// 系统状态指示灯：后端 + MCP 都正常才是绿色
const status = computed(() => {
  if (!store.backendOnline) {
    return { cls: 'dot-offline', text: '后端离线', tone: 'text-[var(--tone-bad)]' }
  }
  if (!store.mcp.connected) {
    return { cls: 'dot-unknown', text: 'MCP 断开', tone: 'text-[var(--tone-warn)]' }
  }
  return {
    cls: 'dot-online',
    text: `系统正常 · MCP ${store.mcp.tools?.length || 0} 工具`,
    tone: 'text-[var(--tone-ok)]',
  }
})

let timer = 0

function tick() {
  clock.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  countdown.value = countdown.value > 1 ? countdown.value - 1 : POLL_SECONDS
}

function onHotkey(event) {
  // ⌘K / Ctrl+K：打开菜单（和大多数现代控制台一致）
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    menuOpen.value = true
  }
}

// 后端每完成一次设备探测（checked_at 变化）就重置倒计时，读数是真实的刷新节奏
watch(
  () => store.deviceMeta.checked_at,
  () => {
    countdown.value = POLL_SECONDS
  },
)

onMounted(() => {
  tick()
  timer = setInterval(tick, 1000)
  window.addEventListener('keydown', onHotkey)
})

onBeforeUnmount(() => {
  clearInterval(timer)
  window.removeEventListener('keydown', onHotkey)
})
</script>

<template>
  <header
    class="sticky top-0 z-30 border-b border-[var(--hairline)]"
    style="background: rgba(251, 250, 247, 0.92); backdrop-filter: blur(10px)"
  >
    <div class="mx-auto flex w-full max-w-[1680px] flex-wrap items-center gap-x-5 gap-y-3 px-6 py-4 lg:px-10">
      <!-- 品牌 -->
      <div class="flex items-center gap-3">
        <span class="tile tile-ink h-10 w-10 rounded-2xl">
          <AppIcon name="activity" :size="20" />
        </span>
        <div class="leading-tight">
          <p class="display text-xl">AIOps 控制台</p>
          <p class="kicker">MCP · VyOS · DeepSeek</p>
        </div>
      </div>

      <!-- 运行状态 -->
      <div class="glass-soft flex items-center gap-2 px-3 py-1.5">
        <span class="dot" :class="status.cls" />
        <span class="text-xs font-semibold" :class="status.tone">{{ status.text }}</span>
        <span class="mono hidden text-[11px] text-[var(--color-ink-soft)] sm:inline">
          {{ store.deviceMeta.online }}/{{ store.deviceMeta.total }} 在线
        </span>
      </div>

      <div class="ml-auto flex items-center gap-3">
        <!-- 文字导航（大屏）；小屏收纳进菜单 -->
        <nav class="hidden items-center gap-1 lg:flex">
          <router-link
            v-for="link in links"
            :key="link.to"
            :to="link.to"
            class="rounded-full px-3.5 py-1.5 text-sm font-semibold transition-colors duration-200"
            :class="
              $route.path === link.to
                ? 'bg-[var(--pill-active-bg)] text-[var(--pill-active-fg)]'
                : 'text-[var(--color-ink-soft)] hover:bg-[var(--pill-hover-bg)] hover:text-[var(--color-ink)]'
            "
          >
            {{ link.label }}
          </router-link>
        </nav>

        <!-- 时钟 + 刷新节奏 -->
        <div class="mono hidden items-center gap-3 text-[11px] text-[var(--color-ink-soft)] lg:flex">
          <span>{{ clock }}</span>
          <span class="h-3 w-px bg-[var(--hairline)]" />
          <span>{{ store.backendOnline ? `下次刷新 ${countdown}s` : '等待后端' }}</span>
        </div>

        <button
          class="btn-ghost flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-semibold"
          :disabled="store.devicesLoading"
          @click="store.loadDevices(true)"
        >
          <AppIcon name="refresh" :size="13" />
          <span class="hidden sm:inline">{{ store.devicesLoading ? '探测中' : '刷新' }}</span>
        </button>

        <!-- 两横菜单 -->
        <button
          class="btn-ghost flex items-center gap-2 px-3.5 py-2 text-xs font-semibold"
          aria-label="打开菜单"
          @click="menuOpen = true"
        >
          <span class="menu-lines"><span /><span /></span>
          <span class="hidden sm:inline">菜单</span>
        </button>
      </div>
    </div>

    <AppMenu :open="menuOpen" @close="menuOpen = false" />
  </header>
</template>
