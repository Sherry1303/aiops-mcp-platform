<script setup>
/**
 * 指标卡片
 * --------------------------------------------------------------------------
 * 视觉参考 Brand Appart 的「立体层叠卡片」：底部两层错位色块（.stack 伪元素，
 * 颜色由 tone 决定，通过 CSS 变量注入）+ 白色纸片正面。
 * 数字保留 900ms ease-out 滚动动画，切页/刷新时都有「在跳」的活感。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'

const props = defineProps({
  label: { type: String, default: '' },
  value: { type: Number, default: 0 },
  unit: { type: String, default: '' },
  hint: { type: String, default: '' },
  icon: { type: String, default: 'server' },
  // 主题色：blue（纳管）/ green（在线）/ rose（告警）/ amber（审计）
  tone: { type: String, default: 'blue' },
  delay: { type: Number, default: 0 },
})

const TONES = {
  blue: { tile: 'tile-blue', num: '#2f6fed', stack: ['#cfe1fa', '#e9f0fb'] },
  green: { tile: 'tile-green', num: '#2f8a5b', stack: ['#cfe9db', '#e7f3ec'] },
  rose: { tile: 'tile-rose', num: '#d6455d', stack: ['#f8d5da', '#fbe9eb'] },
  amber: { tile: 'tile-amber', num: '#b5730a', stack: ['#f7e2bc', '#fdf3e3'] },
}

const theme = computed(() => TONES[props.tone] || TONES.blue)

const shown = ref(0)
let rafId = 0

// 数字滚动动画：ease-out 三次方，900ms
function animateTo(target) {
  cancelAnimationFrame(rafId)
  const from = Number(shown.value) || 0
  const delta = target - from
  const started = performance.now()
  const step = (now) => {
    const progress = Math.min((now - started) / 900, 1)
    const eased = 1 - Math.pow(1 - progress, 3)
    shown.value = Math.round(from + delta * eased)
    if (progress < 1) rafId = requestAnimationFrame(step)
  }
  rafId = requestAnimationFrame(step)
}

onMounted(() => {
  setTimeout(() => animateTo(Number(props.value) || 0), props.delay)
})

watch(
  () => props.value,
  (value) => animateTo(Number(value) || 0),
)

onBeforeUnmount(() => cancelAnimationFrame(rafId))
</script>

<template>
  <div
    class="stack rise-in pb-4"
    :style="{ '--stack-2': theme.stack[0], '--stack-3': theme.stack[1], animationDelay: `${delay}ms` }"
  >
    <div class="stack-face glass glass-hover flex h-full flex-col p-5">
      <div class="flex items-start justify-between gap-3">
        <p class="kicker">{{ label }}</p>
        <span class="tile h-9 w-9" :class="theme.tile">
          <AppIcon :name="icon" :size="17" />
        </span>
      </div>

      <p class="mt-3 flex items-baseline gap-1.5">
        <span class="display text-4xl leading-none" :style="{ color: theme.num }">{{ shown }}</span>
        <span v-if="unit" class="text-xs text-[var(--color-ink-soft)]">{{ unit }}</span>
      </p>

      <p v-if="hint" class="mt-3 line-clamp-2 text-[11px] leading-relaxed text-[var(--color-ink-soft)]">
        {{ hint }}
      </p>
    </div>
  </div>
</template>
