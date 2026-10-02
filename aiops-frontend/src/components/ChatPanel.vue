<script setup>
import { computed, nextTick, ref, watch } from 'vue'

import AppIcon from '@/components/AppIcon.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import { useConsoleStore } from '@/stores/console'

const store = useConsoleStore()
const draft = ref('')
const scroller = ref(null)
const openTools = ref({})

const quickPrompts = [
  '查一下 R1 的 eth0 流量',
  '帮我看看 R1 的接口状态',
  'R1 的版本和运行时长是多少？',
]

const isEmpty = computed(() => store.messages.length === 0)

function scrollToBottom() {
  nextTick(() => {
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  })
}

async function send() {
  const text = draft.value.trim()
  if (!text || store.asking) return
  draft.value = ''
  scrollToBottom()
  await store.ask(text)
  scrollToBottom()
}

function onKeydown(event) {
  // Enter 发送，Shift + Enter 换行
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
  }
}

function toggleTool(key) {
  openTools.value[key] = !openTools.value[key]
}

watch(() => store.messages.length, scrollToBottom)
watch(() => store.asking, scrollToBottom)
</script>

<template>
  <div class="glass glass-hover flex h-full flex-col p-4">
    <!-- 标题 -->
    <div class="flex items-center gap-3">
      <span class="tile tile-tint h-9 w-9">
        <AppIcon name="message" :size="17" />
      </span>
      <div class="leading-tight">
        <h2 class="display text-lg">AI 运维对话</h2>
        <p class="text-[11px] text-[var(--color-ink-soft)]">
          DeepSeek 意图识别 → MCP 工具 → 设备回显
        </p>
      </div>
      <button
        v-if="store.messages.length"
        class="btn-ghost ml-auto px-2.5 py-1 text-[11px] font-semibold"
        @click="store.clearChat()"
      >
        清空
      </button>
    </div>

    <!-- 消息列表 -->
    <div ref="scroller" class="mt-4 h-[360px] space-y-3 overflow-y-auto pr-1">
      <div
        v-if="isEmpty"
        class="glass-soft px-3 py-4 text-xs leading-relaxed text-[var(--color-ink-soft)]"
      >
        <p class="font-semibold text-[var(--color-ink)]">试试这样问：</p>
        <ul class="mt-1.5 space-y-1">
          <li v-for="prompt in quickPrompts" :key="prompt">· {{ prompt }}</li>
        </ul>
        <p class="mt-2">
          链路：前端 → FastAPI → MCP(stdio) → SSH → 设备，再由 DeepSeek 生成结论。
        </p>
      </div>

      <div v-for="(message, index) in store.messages" :key="index" class="flex flex-col gap-1.5">
        <!-- 工具调用（可展开查看原始回显） -->
        <div v-if="message.tools?.length" class="space-y-1.5">
          <div
            v-for="(tool, toolIndex) in message.tools"
            :key="`${index}-${toolIndex}`"
            class="glass-soft pop-in px-3 py-2"
          >
            <button
              class="flex w-full items-center gap-2 text-left text-[11px] font-semibold"
              @click="toggleTool(`${index}-${toolIndex}`)"
            >
              <AppIcon name="terminal" :size="14" />
              <span class="mono">{{ tool.name }}</span>
              <span
                class="rounded-full px-2 py-0.5 text-[10px]"
                :class="
                  tool.status === 'SUCCESS'
                    ? 'bg-[var(--chip-ok-bg)] text-[var(--chip-ok-fg)]'
                    : 'bg-[var(--chip-bad-bg)] text-[var(--chip-bad-fg)]'
                "
              >
                {{ tool.status }}
              </span>
              <span class="mono truncate text-[10px] text-[var(--color-ink-soft)]">
                {{ JSON.stringify(tool.arguments) }}
              </span>
              <AppIcon
                name="chevron"
                :size="12"
                class="ml-auto flex-none transition-transform"
                :class="openTools[`${index}-${toolIndex}`] ? 'rotate-90' : ''"
              />
            </button>
            <pre
              v-if="openTools[`${index}-${toolIndex}`]"
              class="mono mt-2 max-h-48 overflow-auto whitespace-pre-wrap text-[10px] leading-relaxed text-[var(--color-ink-soft)]"
              >{{ tool.result }}</pre
            >
          </div>
        </div>

        <!-- 对话气泡 -->
        <div class="flex" :class="message.role === 'user' ? 'justify-end' : 'justify-start'">
          <div
            class="pop-in max-w-[92%] rounded-2xl px-3.5 py-2.5 text-sm shadow-sm"
            :class="
              message.role === 'user'
                ? 'text-white'
                : message.error
                  ? 'bg-[var(--chip-bad-bg)] text-[var(--tone-bad)]'
                  : 'bg-[var(--bubble-bg)] text-[var(--color-ink)]'
            "
            :style="
              message.role === 'user'
                ? { background: 'var(--accent)', boxShadow: '0 10px 22px -14px rgba(47,111,237,.9)' }
                : {}
            "
          >
            <MarkdownView v-if="message.role !== 'user'" :content="message.content" />
            <p v-else class="whitespace-pre-wrap">{{ message.content }}</p>
            <p
              v-if="message.elapsed_ms"
              class="mono mt-1 text-right text-[10px] text-[var(--color-ink-soft)]"
            >
              {{ (message.elapsed_ms / 1000).toFixed(1) }}s
            </p>
          </div>
        </div>
      </div>

      <div
        v-if="store.asking"
        class="flex items-center gap-2 px-2 text-xs text-[var(--color-ink-soft)]"
      >
        <span class="dot dot-online" />
        正在调用 DeepSeek 与 MCP 工具（SSH 采集约需数秒）…
      </div>
    </div>

    <!-- 快捷提问 -->
    <div class="mt-2 flex flex-wrap gap-1.5">
      <button
        v-for="prompt in quickPrompts"
        :key="prompt"
        class="btn-ghost px-2.5 py-1 text-[11px]"
        :disabled="store.asking"
        @click="draft = prompt; send()"
      >
        {{ prompt }}
      </button>
    </div>

    <!-- 输入区 -->
    <div class="mt-2 flex items-end gap-2">
      <textarea
        v-model="draft"
        rows="2"
        class="input-soft resize-none text-sm"
        placeholder="用中文描述运维需求，例如：查一下 R1 的 eth0 流量（Enter 发送 / Shift+Enter 换行）"
        @keydown="onKeydown"
      />
      <button
        class="btn-gradient flex h-10 w-10 flex-none items-center justify-center"
        :disabled="store.asking || !draft.trim()"
        @click="send"
      >
        <AppIcon :name="store.asking ? 'pause' : 'send'" :size="16" />
      </button>
    </div>
  </div>
</template>
