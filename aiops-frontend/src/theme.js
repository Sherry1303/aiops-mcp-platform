// ECharts 配色统一从 CSS 令牌读取（见 src/style.css 的 :root）。
// 好处：换皮时图表自动跟随，组件里不需要写颜色分支。
const FALLBACK = {
  axis: '#6b7280',
  axisLine: 'rgba(27, 36, 48, 0.14)',
  split: 'rgba(27, 36, 48, 0.07)',
  tooltipBackground: 'rgba(255, 255, 255, 0.97)',
  tooltipBorder: 'rgba(47, 111, 237, 0.38)',
  tooltipText: '#1b2430',
  link: '#9db8de',
}

const VARIABLES = {
  axis: '--chart-axis',
  axisLine: '--chart-axis-line',
  split: '--chart-split',
  tooltipBackground: '--chart-tooltip-bg',
  tooltipBorder: '--chart-tooltip-border',
  tooltipText: '--chart-tooltip-fg',
  link: '--chart-link',
}

function readToken(name, fallback) {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

// 每次渲染时读取令牌，无需重启即可生效（setOption 时重新取色）
export function chartTheme() {
  const palette = {}
  Object.keys(VARIABLES).forEach((key) => {
    palette[key] = readToken(VARIABLES[key], FALLBACK[key])
  })
  return palette
}

// ECharts 浮层（tooltip）通用样式
export function tooltipStyle() {
  const palette = chartTheme()
  return {
    backgroundColor: palette.tooltipBackground,
    borderColor: palette.tooltipBorder,
    textStyle: { color: palette.tooltipText, fontSize: 12 },
  }
}
