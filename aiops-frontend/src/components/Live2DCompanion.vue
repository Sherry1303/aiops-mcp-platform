<script setup>
/**
 * Live2D 虚拟看板娘「小桃 Mao」（右下角陪伴型）
 * ============================================================================
 * 角色：Live2D 官方 Cubism 4 示例模型 Mao（更萌的 Q 版形象，自带 8 个表情 +
 *       Idle / TapBody 两组动作），按 Live2D Free Material License 随 SDK 示例分发，
 *       资源自托管在 public/live2d/mao/，不依赖任何外部 CDN。
 * 性能约束（页面已有 ECharts，绝不能更卡）：
 *   1) Canvas 全局 pointer-events: none；只有「鼠标真的落在看板娘身上」时，
 *      命中层才临时接管指针（命中判定复用 Live2D 的 hitTest），页面其它区域点击不受影响。
 *   2) PixiJS Ticker 限帧 30fps（prefers-reduced-motion 时 12fps）；标签页隐藏时停表。
 *   3) pixi / pixi-live2d-display（约 1MB JS）在浏览器空闲时才动态 import，
 *      不占首屏主包；窄屏（<1024px）直接不加载。
 *   4) 模型自行驱动（autoUpdate: false），不额外订阅全局 Ticker。
 *   5) 模型资源全部自托管在 public/live2d/（含 Cubism 4 Core 运行时）。
 *
 * 调试钩子（仅 DEV，生产构建会被摇树掉）：window.__aiopsLive2d 提供
 *   snapshot() 运行状态 / frame() 轮廓与缩放 / rect() 自身画布矩形 / motion() 当前动作 /
 *   focus() 指针与焦点控制器 / hitAt(x,y) 命中测试 /
 *   shiftProbe(x1,y1,x2,y2) 两个焦点之间的形变顶点最大位移。
 *   注意：参数数组在每帧末尾会被 loadParameters() 回滚成动作快照，事后读 ParamAngleX
 *   只能看到 Idle 动作的值，判断视线是否真的生效请用 shiftProbe()。
 */
import { nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'

import { pickGreeting } from '@/components/live2d/phrases'
import { useConsoleStore } from '@/stores/console'

const MODEL_URL = '/live2d/mao/Mao.model3.json'
const STAGE = { width: 320, height: 420 } // 画布尺寸（CSS px）
const MIN_VIEWPORT = 1024 // 窄屏不加载，避免和 ECharts 抢 GPU
const FPS_ACTIVE = 30 // 常规限帧
const FPS_CALM = 12 // prefers-reduced-motion 时的限帧
const BUBBLE_MS = 5200 // 气泡停留时长
const EXPRESSION_COUNT = 8 // Mao 自带 8 个表情（exp_01~exp_08，按下标调用）
const TAP_MOTION = 'TapBody' // Mao 的点击动作分组（Haru 叫 Tap，换模型时必须同步）
const CHARACTER_NAME = '小桃 Mao' // 角色铭牌文案

const store = useConsoleStore()

const enabled = ref(false) // 是否渲染容器（挂载时按视口宽度决定）
const canvas = ref(null)
const hitLayer = ref(null)
const bubble = ref('')
const ready = ref(false)
const failure = ref('')

const hitStyle = shallowRef({ pointerEvents: 'none' })

const stage = shallowRef({ app: null, model: null }) // pixi 实例（非响应式，避免深度代理）
const frameBox = shallowRef(null) // 轮廓框（stage 坐标），hitTest 不可用时的兜底

let destroyed = false
let bootTimer = 0
let bootIdle = 0
let bubbleTimer = 0
let frames = 0
let pointer = null // 最新指针（客户端坐标）
let pointerDirty = false
let overChar = false
let hitTestBroken = false

/** 播放一句台词 */
function say(text, ms = BUBBLE_MS) {
  if (!text) return
  bubble.value = text
  clearTimeout(bubbleTimer)
  bubbleTimer = setTimeout(() => {
    bubble.value = ''
  }, ms)
}

/** 命中层跟随悬停状态：只在真正点中看板娘时接管指针 */
function syncHitLayer() {
  hitStyle.value = overChar
    ? { pointerEvents: 'auto', cursor: 'pointer' }
    : { pointerEvents: 'none' }
}

/**
 * 测量当前姿态下的轮廓（模型局部坐标）。
 * Live2D 画布通常远大于人物本体，直接用画布尺寸缩放会导致人物过小，
 * 所以这里对所有可见 drawable 的包围盒求并集，得到真实轮廓。
 */
function measureSilhouette(PIXI, internal) {
  const core = internal.coreModel
  const count = typeof core?.getDrawableCount === 'function' ? core.getDrawableCount() : 0
  if (!count || typeof internal.getDrawableBounds !== 'function') return null

  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (let i = 0; i < count; i += 1) {
    try {
      if (typeof core.getDrawableOpacity === 'function' && core.getDrawableOpacity(i) <= 0.01) continue
      const box = internal.getDrawableBounds(i, new PIXI.Bounds())
      if (!box || !Number.isFinite(box.x) || !Number.isFinite(box.y)) continue
      if (!(box.width > 0) || !(box.height > 0) || box.width > 1e5 || box.height > 1e5) continue
      minX = Math.min(minX, box.x)
      minY = Math.min(minY, box.y)
      maxX = Math.max(maxX, box.x + box.width)
      maxY = Math.max(maxY, box.y + box.height)
    } catch (error) {
      // 单个 drawable 异常不影响整体测量
    }
  }
  if (!Number.isFinite(minX) || !Number.isFinite(minY)) return null
  return { minX, minY, maxX, maxY }
}

/** 按轮廓把模型摆到画布底部居中，并返回轮廓框的 stage 坐标（兜底命中框用） */
function frameModel(model, internal, silhouette) {
  const mW = internal.width
  const mH = internal.height
  const box = silhouette || { minX: 0, minY: 0, maxX: mW, maxY: mH }
  const boxW = Math.max(1, box.maxX - box.minX)
  const boxH = Math.max(1, box.maxY - box.minY)
  const scale = Math.min(STAGE.width / boxW, STAGE.height / boxH) * 0.98

  const anchor = { x: 0.5, y: 1 }
  model.anchor.set(anchor.x, anchor.y)
  model.scale.set(scale)

  const pivotX = anchor.x * mW
  const pivotY = anchor.y * mH
  const centerX = (box.minX + box.maxX) / 2
  model.x = STAGE.width / 2 - (centerX - pivotX) * scale
  model.y = STAGE.height - 4 - (box.maxY - pivotY) * scale

  return {
    scale,
    box: {
      x: model.x + (box.minX - pivotX) * scale,
      y: model.y + (box.minY - pivotY) * scale,
      width: boxW * scale,
      height: boxH * scale,
    },
  }
}

/** 指针是否落在看板娘身上：优先用 Live2D 自带的 hitTest（Head/Body 网格），失败则退回轮廓框 */
function isOverCharacter(model, sx, sy) {
  if (!hitTestBroken) {
    try {
      return model.hitTest(sx, sy).length > 0
    } catch (error) {
      hitTestBroken = true
      console.warn('[Live2D] hitTest 不可用，改用轮廓框判定：', error.message)
    }
  }
  const box = frameBox.value
  if (!box) return false
  return sx >= box.x && sx <= box.x + box.width && sy >= box.y && sy <= box.y + box.height
}

/** 每帧回调（受 ticker.maxFPS 限制） */
function onTick() {
  frames += 1
  const { app, model } = stage.value
  if (!app || !model || !app.view) return

  // 0) 喂时间：autoUpdate=false 时必须手动推进，库会在 _render 里用累计的
  //    deltaTime 调用 internalModel.update()，动作/物理/表情/视线都依赖它。
  model.update(app.ticker.deltaMS)

  const rect = app.view.getBoundingClientRect()

  // 1) 视线跟随：mousemove 只记录坐标，每帧最多消费一次
  if (pointerDirty) {
    pointerDirty = false
    if (pointer) model.focus(pointer.x - rect.left, pointer.y - rect.top)
    else model.focus(rect.width / 2, rect.height / 2) // 指针离开窗口 → 目视前方
  }

  // 2) 悬停判定：每 3 帧一次，先做矩形粗筛，避免无谓的顶点计算
  if (frames % 3 !== 0) return
  let over = false
  if (
    pointer &&
    pointer.x >= rect.left - 24 &&
    pointer.x <= rect.right + 24 &&
    pointer.y >= rect.top - 24 &&
    pointer.y <= rect.bottom + 24
  ) {
    over = isOverCharacter(model, pointer.x - rect.left, pointer.y - rect.top)
  }
  if (over !== overChar) {
    overChar = over
    if (over) say(pickGreeting(store, 'hover'))
    syncHitLayer()
  }
}

function onPointerMove(event) {
  pointer = { x: event.clientX, y: event.clientY }
  pointerDirty = true
}

function onPointerLeave() {
  pointer = null
  pointerDirty = true
}

/** 点击看板娘：换台词 + 随机点击动作 + 随机表情 */
function onTap() {
  say(pickGreeting(store, 'tap'))
  const { model } = stage.value
  if (!model) return
  try {
    model.motion(TAP_MOTION)
    model.expression(Math.floor(Math.random() * EXPRESSION_COUNT))
  } catch (error) {
    console.warn('[Live2D] 动作/表情播放失败：', error.message)
  }
}

function onVisibilityChange() {
  const { app } = stage.value
  if (!app) return
  if (document.hidden) app.ticker.stop()
  else app.ticker.start()
}

/** 加载模型（首次渲染后再执行，避免拖慢首屏） */
async function boot() {
  if (destroyed) return
  await nextTick()
  if (!canvas.value) return

  if (!window.Live2DCubismCore) {
    failure.value = '未加载 Cubism 4 Core'
    console.warn('[Live2D] 缺少 live2dcubismcore.js，已跳过着板娘。')
    return
  }

  const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches

  try {
    // 动态 import：pixi 与 pixi-live2d-display 单独分包，不阻塞首屏
    // 注意必须用 /cubism4 子入口：默认入口在模块顶层就要求 window.Live2D（Cubism 2 运行时），
    // 只跑 Cubism 4 模型时会直接抛 "Could not find Cubism 2 runtime"。
    const PIXI = await import('pixi.js')
    const { Live2DModel, MotionPriority } = await import('pixi-live2d-display/cubism4')
    if (destroyed) return

    const app = new PIXI.Application({
      view: canvas.value,
      width: STAGE.width,
      height: STAGE.height,
      backgroundAlpha: 0, // 透明背景，露出页面玻璃拟态
      antialias: true,
      autoDensity: true,
      resolution: Math.min(window.devicePixelRatio || 1, 2),
      autoStart: false, // 模型就绪后再启动，避免空跑
    })
    app.ticker.maxFPS = calm ? FPS_CALM : FPS_ACTIVE // 限帧

    const model = await Live2DModel.from(MODEL_URL, {
      autoInteract: false, // 画布不接收指针事件，交互由命中层负责
      autoUpdate: false, // 由本组件的 ticker 驱动，避免重复订阅全局 Ticker
      idleMotionGroup: 'Idle',
    })
    if (destroyed) {
      app.destroy(true)
      return
    }

    const internal = model.internalModel
    const fitted = frameModel(model, internal, measureSilhouette(PIXI, internal))
    frameBox.value = fitted.box
    app.stage.addChild(model)

    if (!calm) {
      // 待机动作必须用 IDLE 优先级：MotionState.reserve 会拒绝「同级或更低优先级」的动作请求，
      // 若用默认的 NORMAL 启动待机，之后点击触发的 Tap（同为 NORMAL）会被判为同级而静默丢弃。
      // 库自己的待机续播（MotionManager.update → startRandomMotion(idle, IDLE)）也是 IDLE 优先级。
      model.motion('Idle', undefined, MotionPriority.IDLE)
    }
    ready.value = true
    stage.value = { app, model, fitted, calm }

    app.ticker.add(onTick)
    app.ticker.start()

    window.addEventListener('mousemove', onPointerMove, { passive: true })
    document.documentElement.addEventListener('mouseleave', onPointerLeave)
    document.addEventListener('visibilitychange', onVisibilityChange)

    setTimeout(() => say(pickGreeting(store, 'boot')), 900)
  } catch (error) {
    failure.value = error.message
    console.warn('[Live2D] 看板娘加载失败：', error)
  }
}

/** 调试钩子：便于在浏览器控制台 / 自动化脚本里核对渲染与视线状态（仅开发环境暴露） */
function installDebugHook() {
  // 生产构建里 import.meta.env.DEV 为 false，整段会被摇树掉，页面上不留调试入口
  if (!import.meta.env.DEV) return
  window.__aiopsLive2d = {
    snapshot: () => ({
      ready: ready.value,
      failure: failure.value,
      frames,
      over: overChar,
      bubble: bubble.value,
      hitTestBroken,
      maxFPS: stage.value.app?.ticker?.maxFPS ?? 0,
      measuredFPS: stage.value.app?.ticker?.FPS ?? 0,
      canvasPointerEvents: canvas.value ? getComputedStyle(canvas.value).pointerEvents : '',
      hitPointerEvents: hitLayer.value ? getComputedStyle(hitLayer.value).pointerEvents : '',
    }),
    frame: () => ({
      box: frameBox.value,
      fitted: stage.value.fitted || null,
      model: stage.value.model
        ? {
            originalWidth: stage.value.model.internalModel.originalWidth,
            originalHeight: stage.value.model.internalModel.originalHeight,
            width: stage.value.model.internalModel.width,
            height: stage.value.model.internalModel.height,
            scale: stage.value.model.scale.x,
            x: stage.value.model.x,
            y: stage.value.model.y,
          }
        : null,
    }),
    hitAt: (x, y) => {
      const model = stage.value.model
      if (!model) return null
      try {
        return model.hitTest(x, y)
      } catch (error) {
        return `ERR:${error.message}`
      }
    },
    motion: () => {
      const manager = stage.value.model?.internalModel?.motionManager
      if (!manager) return null
      return {
        group: manager.state?.currentGroup ?? '',
        index: manager.state?.currentIndex ?? -1,
        reserved: manager.state?.reservedMotion?.group ?? '',
      }
    },
    /** 看板娘自己的 canvas 矩形（页面上可能有多个 canvas，不能靠 querySelector 猜） */
    rect: () => {
      const el = canvas.value
      if (!el) return null
      const r = el.getBoundingClientRect()
      return { left: r.left, top: r.top, width: r.width, height: r.height, pointerEvents: getComputedStyle(el).pointerEvents }
    },
    /** 当前指针状态与焦点控制器数值 */
    focus: () => {
      const internal = stage.value.model?.internalModel
      const controller = internal?.focusController
      return {
        pointer: pointer ? { x: pointer.x, y: pointer.y } : null,
        pointerDirty,
        controller: controller ? { x: controller.x, y: controller.y } : null,
      }
    },
    /** 画布 / 命中层的 DOM 节点（供自动化脚本做 identity 判断，别用 returnByValue 直接取） */
    canvasEl: () => canvas.value,
    hitLayerEl: () => hitLayer.value,
    /**
     * 诊断用：把焦点分别放到两个画布坐标，比较 Core 形变顶点的最大位移。
     * 参数数组在帧末会被 loadParameters() 回滚成动作快照，所以直接看参数值测不出视线效果，
     * 顶点位置（渲染真正使用的结果）才可信。
     */
    shiftProbe: async (x1, y1, x2, y2) => {
      const { model } = stage.value
      if (!model) return null
      const internal = model.internalModel
      const core = internal.coreModel
      const count = core.getDrawableCount()
      const snapshot = () => {
        const out = []
        for (let i = 0; i < count; i += 1) out.push(Array.from(internal.getDrawableVertices(i)))
        return out
      }
      const settle = () => new Promise((resolve) => setTimeout(resolve, 320))
      model.focus(x1, y1, true)
      await settle()
      const first = snapshot()
      model.focus(x2, y2, true)
      await settle()
      const second = snapshot()
      let max = 0
      let at = -1
      let total = 0
      for (let i = 0; i < count; i += 1) {
        let shift = 0
        for (let j = 0; j < first[i].length; j += 1) {
          shift = Math.max(shift, Math.abs(second[i][j] - first[i][j]))
        }
        total += shift
        if (shift > max) {
          max = shift
          at = i
        }
      }
      return { maxShift: Number(max.toFixed(3)), drawableIndex: at, totalShift: Number(total.toFixed(1)), drawables: count }
    },
  }
}

// 状态联动：AI 开始调用工具 / 新增离线设备时，看板娘主动播报
const stopAskingWatch = watch(
  () => store.asking,
  (asking) => {
    if (asking && ready.value) say(pickGreeting(store, 'hover'))
  },
)

const stopOfflineWatch = watch(
  () => store.offlineDevices.length,
  (now, before) => {
    if (now > before && ready.value) say(pickGreeting(store, 'hover'))
  },
)

onMounted(() => {
  installDebugHook()
  // 窄屏不加载：移动端优先保证 ECharts 与交互流畅
  if (window.innerWidth < MIN_VIEWPORT) return
  enabled.value = true

  // 等浏览器空闲再拉 1MB 级的 pixi + 模型，避免与首屏渲染抢资源
  if (typeof window.requestIdleCallback === 'function') {
    bootIdle = window.requestIdleCallback(() => boot(), { timeout: 3000 })
  } else {
    bootTimer = setTimeout(boot, 900)
  }
})

onBeforeUnmount(() => {
  destroyed = true
  clearTimeout(bubbleTimer)
  clearTimeout(bootTimer)
  if (bootIdle && typeof window.cancelIdleCallback === 'function') window.cancelIdleCallback(bootIdle)

  stopAskingWatch()
  stopOfflineWatch()
  window.removeEventListener('mousemove', onPointerMove)
  document.documentElement.removeEventListener('mouseleave', onPointerLeave)
  document.removeEventListener('visibilitychange', onVisibilityChange)

  const { app } = stage.value
  if (app) {
    try {
      app.ticker.remove(onTick)
      app.ticker.stop()
      app.destroy(true, { children: true, texture: true, baseTexture: true })
    } catch (error) {
      console.warn('[Live2D] 资源释放异常：', error.message)
    }
  }
  stage.value = { app: null, model: null }
  if (import.meta.env.DEV) delete window.__aiopsLive2d
})
</script>

<template>
  <!-- 整层 pointer-events: none（canvas 亦然），只有命中层在看板娘身上时临时接管指针 -->
  <div
    v-if="enabled"
    class="pointer-events-none fixed bottom-0 right-3 z-20 select-none"
    :style="{ width: `${STAGE.width}px`, height: `${STAGE.height}px` }"
    aria-hidden="true"
  >
    <canvas ref="canvas" class="block" style="pointer-events: none" />
    <div ref="hitLayer" class="absolute inset-0" :style="hitStyle" @click="onTap" />

    <!-- 台词气泡：贴纸样式（白底 + 淡蓝描边 + 右下角小尾巴），比毛玻璃更「萌」 -->
    <transition name="tip">
      <p
        v-if="bubble"
        class="l2d-bubble pop-in absolute bottom-[64%] right-1 max-w-[232px] px-3.5 py-2.5 text-xs leading-relaxed"
      >
        {{ bubble }}
      </p>
    </transition>

    <!-- 角色铭牌：让「看板娘是谁」一眼可见 -->
    <p v-if="ready" class="l2d-name absolute bottom-2 left-2 rounded-full px-2.5 py-1 text-[10px] font-semibold">
      {{ CHARACTER_NAME }}
    </p>

    <p
      v-if="!ready && !failure"
      class="absolute bottom-3 right-3 text-[10px] text-[var(--color-ink-soft)]"
    >
      看板娘加载中…
    </p>
  </div>
</template>

<style scoped>
.l2d-bubble {
  color: var(--color-ink);
  background: #ffffff;
  border: 1px solid #dbe7fb;
  border-radius: 16px 16px 4px 16px;
  box-shadow: 0 14px 30px -18px rgba(27, 36, 48, 0.55);
}

/* 尾巴：向右下角的小三角，指向看板娘头部 */
.l2d-bubble::after {
  content: '';
  position: absolute;
  right: 16px;
  bottom: -7px;
  width: 12px;
  height: 12px;
  background: #ffffff;
  border-right: 1px solid #dbe7fb;
  border-bottom: 1px solid #dbe7fb;
  border-radius: 0 0 4px 0;
  transform: rotate(45deg);
}

.l2d-name {
  color: var(--accent);
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid #dbe7fb;
  letter-spacing: 0.02em;
}

.tip-enter-active,
.tip-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.tip-enter-from,
.tip-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.96);
}
</style>
