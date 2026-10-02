/**
 * 看板娘台词库
 * ----------------------------------------------------------------------------
 * 台词优先反映"真实运维状态"（后端失联 / 设备离线 / 告警未处理 / 工具调用中），
 * 只有一切正常时才播报随机问候语，避免看板娘说假话。
 * 所有台词均为中文，贴合 AIOps 语境；随机选取时会避免与上一句重复。
 */

// 固定台词
const LINES = {
  // 后端 / MCP 不可达（仅在确实拿到过错误信息时使用，避免启动瞬间误报）
  broken: [
    '后端好像没连上……看看 aiops-api（:8000）还在不在？',
    '咦，我连不上后端了，检查一下 uvicorn 进程吧。',
    '控制链路断了，我暂时看不到设备状态。',
  ],
  // AI 正在调用 MCP 工具
  busy: [
    '正在调用 MCP 工具，稍等一下下～',
    'DeepSeek 在思考中，先别催我啦。',
    'SSH 采集要几秒钟，我盯着进度条呢。',
  ],
  // 一切正常
  healthy: [
    '系统运行正常哦，各项指标都在安全区间～',
    '巡检完成！所有设备都在线，可以放心喝口水啦。',
    '一切正常，我在帮你盯着仪表盘呢。',
    '链路健康，MCP 工具随时待命。',
  ],
  // 首次登场
  boot: [
    '看板娘上线啦，点我可以看设备状态哦～',
    '你好呀，我是 AIOps 小助手，随时待命！',
    '小桃报到！网络这边交给我盯着就好～',
  ],
  // 点击看板娘
  tap: [
    '今天也要加油哦！',
    '需要我帮你查哪台设备？',
    '别戳我啦，我在认真看护网络呢。',
    '点我一下，我就一直在这儿陪着你～',
    '想知道哪台设备的状况？让右侧的 AI 对话帮我查查。',
    '我是小桃，有什么运维上的事都可以找我～',
  ],
}

// 需要拼接变量的台词
const OFFLINE_LINES = [
  (name) => `检测到 ${name} 离线啦，要我帮你看看吗？`,
  (name) => `${name} 好像掉线了，点它名字能看详情哦。`,
  (name) => `注意！${name} 不在线，需要我帮你排查吗？`,
]

const ALERT_LINES = [
  (count) => `还有 ${count} 条告警没处理哦，别忘了～`,
  (count) => `告警中心躺着 ${count} 条待处理，要我提醒你吗？`,
]

let previous = ''

/** 从候选池中随机取一句，尽量避免与上一句重复 */
function pick(pool) {
  if (!pool || !pool.length) return ''
  if (pool.length === 1) {
    previous = pool[0]
    return previous
  }
  let text = previous
  for (let i = 0; i < 8 && text === previous; i += 1) {
    text = pool[Math.floor(Math.random() * pool.length)]
  }
  previous = text
  return text
}

/**
 * 取一句看板娘台词
 * @param {object} store  Pinia 控制台 store（可缺省，缺省时只返回通用问候）
 * @param {'hover'|'tap'|'boot'} kind 触发场景
 */
export function pickGreeting(store = {}, kind = 'hover') {
  // 1) 后端确实报错了才提示，避免启动瞬间 backendOnline 仍为 false 时误报
  if (store.backendOnline === false && store.lastError) return pick(LINES.broken)

  // 2) 设备离线（例如「检测到 SW1 离线啦」）
  const offline = (store.devices || []).filter((item) => !item.online)
  if (offline.length) return pick(OFFLINE_LINES)(offline[0].name)

  // 3) 未处理告警
  const alerts = Number((store.stats || {}).alerts_active || 0)
  if (alerts > 0) return pick(ALERT_LINES)(alerts)

  // 4) 正在调用工具
  if (store.asking) return pick(LINES.busy)

  // 5) 纯问候
  if (kind === 'tap') return pick(LINES.tap)
  if (kind === 'boot') return pick(LINES.boot)
  return pick(LINES.healthy)
}

export default LINES
