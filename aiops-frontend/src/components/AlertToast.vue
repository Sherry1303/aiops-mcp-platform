<script setup>
/**
 * 告警提醒（顶部浮层）
 * --------------------------------------------------------------------------
 * 只在「未确认告警数变多」时提示：首屏 bootstrap 拿到的统计只作为基线，不会误报。
 * 8 秒后自动消失，也可点 × 关闭，或点「去处理」跳到审计日志页。
 */
import { onBeforeUnmount, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import { useConsoleStore } from '@/stores/console'

const store = useConsoleStore()

const visible = ref(false)
const delta = ref(0)
const latest = ref('')

let timer = 0
let baseline = null // 首屏基线：避免把「页面刚加载」当成「新增告警」

function show() {
  visible.value = true
  clearTimeout(timer)
  timer = setTimeout(() => {
    visible.value = false
  }, 8000)
}

watch(
  () => store.stats.alerts_active,
  (now) => {
    const count = Number(now || 0)
    if (baseline === null) {
      baseline = count
      return
    }
    if (count > baseline) {
      delta.value = count - baseline
      const active = (store.alerts || []).find((item) => item.status === 'ACTIVE')
      latest.value = active
        ? `${active.level} · ${active.device_name} · ${active.message}`
        : '请前往「审计日志 → 告警中心」查看详情'
      show()
    }
    baseline = count
  },
)

onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <transition name="toast">
    <div v-if="visible" class="fixed left-1/2 top-24 z-40 w-full max-w-[620px] -translate-x-1/2 px-4">
      <div class="glass pop-in flex items-center gap-3 px-4 py-3">
        <span class="tile tile-rose h-9 w-9">
          <AppIcon name="alert" :size="18" />
        </span>
        <div class="min-w-0 flex-1">
          <p class="text-sm font-bold">新增 {{ delta }} 条未确认告警</p>
          <p class="truncate text-[11px] text-[var(--color-ink-soft)]">{{ latest }}</p>
        </div>
        <router-link
          to="/audit"
          class="btn-gradient px-3.5 py-1.5 text-[11px] font-bold"
          @click="visible = false"
        >
          去处理
        </router-link>
        <button
          class="btn-ghost grid h-7 w-7 place-items-center"
          aria-label="关闭告警提示"
          @click="visible = false"
        >
          <AppIcon name="close" :size="14" />
        </button>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.24s ease, transform 0.24s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translate(-50%, -10px);
}
</style>
