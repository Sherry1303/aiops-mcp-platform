<script setup>
import { onBeforeUnmount, onMounted } from 'vue'

import AlertToast from '@/components/AlertToast.vue'
import DeviceDrawer from '@/components/DeviceDrawer.vue'
import Live2DCompanion from '@/components/Live2DCompanion.vue'
import NavBar from '@/components/NavBar.vue'
import SideBar from '@/components/SideBar.vue'
import { useConsoleStore } from '@/stores/console'

const store = useConsoleStore()

onMounted(() => store.bootstrap())
onBeforeUnmount(() => store.stopPolling())
</script>

<template>
  <div class="flex min-h-screen flex-col">
    <NavBar />

    <!-- 后端不可达提示（含最常见的排查提示） -->
    <div v-if="!store.backendOnline && store.lastError" class="mx-auto w-full max-w-[1680px] px-6 pt-6 lg:px-10">
      <div class="glass pop-in flex flex-wrap items-center gap-2 px-5 py-3.5 text-sm">
        <span class="dot dot-offline" />
        <span class="font-semibold text-[var(--tone-bad)]">后端未连接</span>
        <span class="text-[var(--color-ink-soft)]">{{ store.lastError }}</span>
      </div>
    </div>

    <!-- 主区：外壳改成 1680 宽 + 大间距，让「功能区间隔」和「左右留白」都符合预期 -->
    <main class="mx-auto flex w-full max-w-[1680px] flex-1 items-start gap-8 px-6 py-8 lg:gap-10 lg:px-10">
      <SideBar class="hidden w-[300px] flex-none lg:block" />
      <section class="min-w-0 flex-1">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </section>
    </main>

    <footer class="mx-auto w-full max-w-[1680px] px-6 pb-10 lg:px-10">
      <hr class="rule" />
      <div class="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] text-[var(--color-ink-soft)]">
        <span class="kicker">AIOps Console</span>
        <span>Vue 3 + Vite + Tailwind CSS · FastAPI · MCP(stdio) · DeepSeek</span>
        <span class="mono ml-auto">{{ store.apiBase }}</span>
      </div>
    </footer>

    <!-- 设备详情抽屉 · 告警提醒 · Live2D 看板娘（右下角，窄屏自动不加载） -->
    <DeviceDrawer />
    <AlertToast />
    <Live2DCompanion />
  </div>
</template>

<style>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
