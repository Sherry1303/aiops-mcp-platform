<script setup>
import { computed } from 'vue'

import DOMPurify from 'dompurify'
import { marked } from 'marked'

const props = defineProps({
  content: { type: String, default: '' },
})

marked.setOptions({ gfm: true, breaks: true })

// AI 回复按 Markdown 渲染，并用 DOMPurify 过滤，避免 XSS
const html = computed(() => {
  try {
    return DOMPurify.sanitize(marked.parse(props.content || ''))
  } catch (error) {
    return `<p>${props.content}</p>`
  }
})
</script>

<template>
  <div class="md-body" v-html="html" />
</template>
