<script setup>
/**
 * 两横菜单（Studio Alphonse 的极简做法）
 * --------------------------------------------------------------------------
 * 顶部导航只留一个「两横」按钮，点击展开整屏菜单：
 *   · 左侧：巨大衬线导航（春水堂式的序号 + 英文小字 + 中文大字）
 *   · 右侧：系统信息与快捷键说明
 *   · 键盘：⌘/Ctrl + K 打开（由 NavBar 派发）、数字 1/2/3 直达、Esc 关闭
 * 菜单打开时锁定页面滚动，关闭/卸载时必定解锁，避免页面被「卡死」。
 */
import { onBeforeUnmount, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import { BASE_URL } from '@/api'
import { useConsoleStore } from '@/stores/console'

const props = defineProps({
  open: { type: Boolean, default: false },
})

const emit = defineEmits(['close'])

const store = useConsoleStore()
const router = useRouter()

const items = [
  { key: '1', index: '01', to: '/', label: '控制台', en: 'Dashboard', desc: '拓扑 · 流量 · AI 对话' },
  { key: '2', index: '02', to: '/audit', label: '审计日志', en: 'Audit Log', desc: '操作留痕 · 告警中心' },
  { key: '3', index: '03', to: '/about', label: '关于', en: 'About', desc: '架构分层 · 接口清单' },
]

const shortcuts = [
  { key: '⌘ / Ctrl + K', desc: '打开本菜单' },
  { key: '1 / 2 / 3', desc: '直达对应页面' },
  { key: 'Esc', desc: '关闭菜单' },
]

function go(to) {
  emit('close')
  router.push(to)
}

function onKeydown(event) {
  if (!props.open) return
  if (event.key === 'Escape') {
    emit('close')
    return
  }
  const hit = items.find((item) => item.key === event.key)
  if (hit) go(hit.to)
}

watch(
  () => props.open,
  (open) => {
    document.body.style.overflow = open ? 'hidden' : ''
  },
)

onMounted(() => window.addEventListener('keydown', onKeydown))

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <transition name="menu">
      <div
        v-if="open"
        class="fixed inset-0 z-50 overflow-y-auto"
        style="background: rgba(251, 250, 247, 0.97)"
        role="dialog"
        aria-modal="true"
        aria-label="站点菜单"
      >
        <div class="mx-auto flex min-h-full w-full max-w-[1680px] flex-col px-6 py-6 lg:px-10">
          <!-- 顶行：品牌 + 关闭（两横旋转成叉） -->
          <div class="flex items-center gap-3">
            <span class="tile tile-ink h-9 w-9 rounded-xl">
              <AppIcon name="activity" :size="18" />
            </span>
            <div class="leading-tight">
              <p class="display text-lg">AIOps 控制台</p>
              <p class="kicker">MENU INDEX</p>
            </div>
            <button
              class="btn-ghost ml-auto flex items-center gap-2 px-4 py-2 text-xs font-semibold"
              @click="emit('close')"
            >
              <span class="menu-lines rotate-45"><span /><span /></span>
              关闭
            </button>
          </div>

          <div class="mt-10 grid flex-1 gap-10 lg:grid-cols-[1.35fr_1fr] lg:gap-16">
            <nav class="flex flex-col">
              <p class="kicker mb-4">NAVIGATION / 站点导航</p>
              <button
                v-for="item in items"
                :key="item.to"
                class="group flex items-baseline gap-5 border-t border-[var(--hairline)] py-6 text-left last:border-b"
                @click="go(item.to)"
              >
                <span class="kicker w-6 pt-1">{{ item.index }}</span>
                <span class="display text-4xl transition-transform duration-300 group-hover:translate-x-2 sm:text-5xl">
                  {{ item.label }}
                </span>
                <span class="hidden flex-1 text-xs text-[var(--color-ink-soft)] sm:block">{{ item.desc }}</span>
                <span class="kicker hidden sm:block">{{ item.en }}</span>
                <AppIcon
                  name="chevron"
                  :size="18"
                  class="ml-auto flex-none text-[var(--color-ink-faint)] transition-transform duration-300 group-hover:translate-x-1"
                />
              </button>
            </nav>

            <aside class="flex flex-col gap-6">
              <section class="glass p-5">
                <p class="kicker">SYSTEM / 运行概况</p>
                <ul class="mt-3 space-y-2 text-xs">
                  <li class="flex items-center gap-2">
                    <span class="dot" :class="store.backendOnline ? 'dot-online' : 'dot-offline'" />
                    后端
                    <span class="mono ml-auto text-[var(--color-ink-soft)]">{{
                      store.backendOnline ? BASE_URL : '未连接'
                    }}</span>
                  </li>
                  <li class="flex items-center gap-2">
                    <span class="dot" :class="store.mcp.connected ? 'dot-online' : 'dot-unknown'" />
                    MCP 工具
                    <span class="mono ml-auto text-[var(--color-ink-soft)]">
                      {{ store.mcp.tools?.length || 0 }} 个
                    </span>
                  </li>
                  <li class="flex items-center gap-2">
                    <span class="dot dot-unknown" />
                    纳管设备
                    <span class="mono ml-auto text-[var(--color-ink-soft)]">
                      {{ store.deviceMeta.online }}/{{ store.deviceMeta.total }} 在线
                    </span>
                  </li>
                </ul>
              </section>

              <section class="glass p-5">
                <p class="kicker">SHORTCUTS / 快捷键</p>
                <ul class="mt-3 space-y-2 text-xs">
                  <li v-for="row in shortcuts" :key="row.key" class="flex items-center gap-3">
                    <span class="mono glass-soft px-2 py-1 text-[11px] font-semibold">{{ row.key }}</span>
                    <span class="text-[var(--color-ink-soft)]">{{ row.desc }}</span>
                  </li>
                </ul>
              </section>

              <p class="mt-auto text-[11px] text-[var(--color-ink-soft)]">
                Vue 3 + Vite + Tailwind CSS · FastAPI · MCP(stdio) · DeepSeek
              </p>
            </aside>
          </div>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<style scoped>
.menu-enter-active,
.menu-leave-active {
  transition: opacity 0.24s ease;
}

.menu-enter-active nav,
.menu-leave-active nav {
  transition: transform 0.36s cubic-bezier(0.22, 1, 0.36, 1);
}

.menu-enter-from,
.menu-leave-to {
  opacity: 0;
}

.menu-enter-from nav {
  transform: translateY(18px);
}
</style>
