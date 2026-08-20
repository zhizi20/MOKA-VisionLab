<template>
  <div class="ann">
    <div class="toolbar">
      <el-select v-model="datasetId" placeholder="选择数据集" style="width:240px" @change="onDatasetChange">
        <el-option v-for="d in datasets" :key="d.id" :label="`${d.name}（${d.classNames.join(', ')}）`" :value="d.id" />
      </el-select>
      <el-tag v-if="stats.total">共 {{ stats.total }}</el-tag>
      <el-tag v-if="stats.annotated" type="success">已标 {{ stats.annotated }}</el-tag>
      <el-select v-model="filterCls" placeholder="筛选" style="width:150px" @change="onFilter">
        <el-option label="全部图片" value="all" />
        <el-option label="未标注" value="unlabeled" />
        <el-option v-for="(c, i) in classNames" :key="c" :label="`含 ${c}`" :value="String(i)" />
      </el-select>
      <el-select v-model="clsId" placeholder="当前类别" style="width:140px">
        <el-option v-for="(c, i) in classNames" :key="c" :label="c" :value="i" />
      </el-select>
      <el-color-picker v-if="classNames.length" :model-value="classColors[clsId]" @change="onColorChange" />
      <el-radio-group v-model="mode" size="small">
        <el-radio-button value="draw">画框</el-radio-button>
        <el-radio-button value="pan">拖动图片</el-radio-button>
        <el-radio-button value="sam">SAM 点选</el-radio-button>
      </el-radio-group>
      <el-button-group>
        <el-button size="small" @click="nudgeZoom(1 / 1.25)">缩小</el-button>
        <el-button size="small" @click="zoomFit">{{ zoomLabel }}</el-button>
        <el-button size="small" @click="nudgeZoom(1.25)">放大</el-button>
      </el-button-group>
      <el-select v-model="preModelId" placeholder="预标模型" clearable style="width:180px">
        <el-option v-for="m in models" :key="m.id" :label="m.name" :value="m.id" />
      </el-select>
      <el-button :disabled="!preModelId || !current" :loading="preLoading" @click="prelabel(false)">预标本图</el-button>
      <el-button :disabled="!preModelId" :loading="preAllLoading" @click="prelabel(true)">预标全部</el-button>
      <el-button :disabled="!canUndo" @click="undo">撤销</el-button>
      <el-button :disabled="!canRedo" @click="redo">重做</el-button>
      <el-button :disabled="viewIdx<=0" @click="goto(viewIdx-1)">上一张</el-button>
      <el-button :disabled="viewIdx>=viewList.length-1" @click="goto(viewIdx+1)">下一张</el-button>
      <el-tag v-if="dirty" type="warning">未保存</el-tag>
      <el-button type="primary" :loading="saving" @click="save()">{{ dirty ? '保存*' : '保存' }}</el-button>
      <el-button type="danger" plain @click="clearBoxes">清空本图</el-button>
    </div>
    <el-empty v-if="!datasetId" description="请选择数据集。没有标注就无法训练。" />
    <el-empty v-else-if="!samples.length" description="暂无图片，请先上传或抽帧" />
    <el-empty v-else-if="!viewList.length" description="当前筛选没有图片" />
    <div v-else class="main">
      <div class="list">
        <div
          v-for="(s, i) in viewList"
          :key="s.stem"
          class="item"
          :class="{ active: i===viewIdx, done: s.annotated }"
          @click="goto(i)"
        >
          {{ s.name }}
          <el-tag size="small">{{ s.boxCount }}</el-tag>
          <el-tag v-if="dirty && s.stem === activeStem" size="small" type="warning">*</el-tag>
        </div>
      </div>
      <div
        class="canvas-wrap"
        ref="wrapRef"
        v-loading="samLoading"
        :style="{ cursor: hoverCursor }"
        @wheel.prevent="onWheel"
        @mousedown="wrapDown"
        @contextmenu.prevent
      >
        <div class="canvas-stage" :style="{ transform: `translate(${panX}px, ${panY}px)` }">
          <canvas
            ref="canvasRef"
            :class="mode"
            @mousedown.stop="down"
            @mousemove="hoverMove"
          />
        </div>
        <div class="hint">
          {{ hintText }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { datasetApi, modelApi } from '../api'
import { useUserStore } from '../store/user'

const DEFAULT_COLORS = ['#ff2d95', '#00e5ff', '#ffd400', '#7cff6b', '#ff8a00', '#c084fc', '#22d3ee', '#fb7185']
const HANDLE_NAMES = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']
const HANDLE_CURSOR = {
  nw: 'nwse-resize', se: 'nwse-resize',
  ne: 'nesw-resize', sw: 'nesw-resize',
  n: 'ns-resize', s: 'ns-resize',
  e: 'ew-resize', w: 'ew-resize',
}
const HANDLE_PX = 8
const CLICK_PX = 5
const route = useRoute()
const store = useUserStore()
const datasets = ref([])
const models = ref([])
const datasetId = ref(null)
const preModelId = ref(null)
const classNames = ref([])
const classColors = ref([])
const samples = ref([])
const stats = ref({})
const viewIdx = ref(0)
const clsId = ref(0)
const filterCls = ref('all')
const boxes = ref([])
const saving = ref(false)
const preLoading = ref(false)
const preAllLoading = ref(false)
const samLoading = ref(false)
const mode = ref('draw')
const canvasRef = ref(null)
const wrapRef = ref(null)
const img = ref(null)
const fitScale = ref(1)
const zoom = ref(1)
const panX = ref(0)
const panY = ref(0)
const drawing = ref(false)
const start = ref(null)
const draft = ref(null)
const selected = ref(-1)
const history = ref([])
const histIdx = ref(-1)
const action = ref(null)
const resizeHandle = ref('')
const origBox = ref(null)
const hoverCursor = ref('crosshair')
const spaceDown = ref(false)
const panOrigin = ref(null)
const lastDatasetId = ref(null)
const dirty = ref(false)
const activeStem = ref('')
const viewList = computed(() => {
  if (filterCls.value === 'all') return samples.value
  if (filterCls.value === 'unlabeled') return samples.value.filter((s) => !s.annotated)
  const id = Number(filterCls.value)
  return samples.value.filter((s) => (s.classIds || []).includes(id))
})
const current = computed(() => viewList.value[viewIdx.value])
const canUndo = computed(() => histIdx.value > 0)
const canRedo = computed(() => histIdx.value >= 0 && histIdx.value < history.value.length - 1)
const viewScale = computed(() => fitScale.value * zoom.value)
const zoomLabel = computed(() => `${Math.round(viewScale.value * 100)}%`)
const hintText = computed(() => {
  if (mode.value === 'pan') return '按住左键拖动图片 · 滚轮缩放 · 点「画框」继续标注'
  if (mode.value === 'sam') return '点击目标，MobileSAM 生成框 · 右键/中键/空格拖动图片 · 滚轮缩放'
  return '左键画框 · 右键或中键拖动图片 · 空格+拖动也可平移 · 滚轮缩放 · 单击选中 · 拖角点调大小'
})

let dragBound = false
let wrapObserver = null
let loadGen = 0
let switching = false

onMounted(async () => {
  const [dsRes, mRes] = await Promise.all([datasetApi.list(), modelApi.list()])
  datasets.value = dsRes.data.rows
  models.value = (mRes.data.rows || []).filter((m) => m.status === '0' && m.hasWeight)
  if (models.value[0]) preModelId.value = models.value[0].id
  const qid = Number(route.query.id)
  if (qid) datasetId.value = qid
  else if (datasets.value[0]) datasetId.value = datasets.value[0].id
  if (datasetId.value) {
    lastDatasetId.value = datasetId.value
    await loadSamples()
  }
  window.addEventListener('keydown', onKey)
  window.addEventListener('keyup', onKeyUp)
  window.addEventListener('beforeunload', onBeforeUnload)
  await nextTick()
  observeWrap()
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('keyup', onKeyUp)
  window.removeEventListener('beforeunload', onBeforeUnload)
  unbindDrag()
  wrapObserver?.disconnect()
})

function observeWrap() {
  wrapObserver?.disconnect()
  if (!wrapRef.value) return
  wrapObserver = new ResizeObserver(() => draw())
  wrapObserver.observe(wrapRef.value)
}

function boxColor(cls) {
  return classColors.value[cls] || DEFAULT_COLORS[cls % DEFAULT_COLORS.length]
}

function cloneBoxes(list = boxes.value) {
  return JSON.parse(JSON.stringify(list))
}

function resetHistory() {
  history.value = [cloneBoxes()]
  histIdx.value = 0
}

function commitHistory() {
  const copy = cloneBoxes()
  const last = history.value[histIdx.value]
  if (last && JSON.stringify(last) === JSON.stringify(copy)) return
  history.value = history.value.slice(0, histIdx.value + 1)
  history.value.push(copy)
  if (history.value.length > 80) history.value.shift()
  histIdx.value = history.value.length - 1
  dirty.value = true
}

function applyHistory() {
  boxes.value = cloneBoxes(history.value[histIdx.value] || [])
  selected.value = -1
  dirty.value = true
  draw()
}

function undo() {
  if (!canUndo.value) return
  histIdx.value -= 1
  applyHistory()
}

function redo() {
  if (!canRedo.value) return
  histIdx.value += 1
  applyHistory()
}

function clearBoxes() {
  boxes.value = []
  selected.value = -1
  commitHistory()
  draw()
}

async function onColorChange(val) {
  if (!val) return
  const next = [...classColors.value]
  next[clsId.value] = val
  classColors.value = next
  await datasetApi.saveColors(datasetId.value, { colors: next })
  draw()
}

async function onFilter() {
  if (!(await flushSave())) return
  viewIdx.value = 0
  await loadCurrent()
}

async function onDatasetChange(id) {
  if (dirty.value && lastDatasetId.value && activeStem.value) {
    try {
      await datasetApi.saveLabels(lastDatasetId.value, { stem: activeStem.value, boxes: cloneBoxes() })
    } catch {
      ElMessage.error('上一数据集未保存成功')
    }
    dirty.value = false
  }
  lastDatasetId.value = id
  await loadSamples()
}

async function loadSamples() {
  const ds = datasets.value.find((d) => d.id === datasetId.value)
  classNames.value = ds?.classNames || []
  clsId.value = 0
  filterCls.value = 'all'
  const [res, colorRes] = await Promise.all([
    datasetApi.samples(datasetId.value),
    datasetApi.colors(datasetId.value),
  ])
  samples.value = res.data.samples
  stats.value = res.data.stats
  classNames.value = res.data.classNames || classNames.value
  classColors.value = colorRes.data.colors || res.data.colors || []
  const qstem = route.query.stem
  const found = qstem ? samples.value.findIndex((s) => s.stem === qstem) : 0
  viewIdx.value = found >= 0 ? found : 0
  await loadCurrent()
  await nextTick()
  observeWrap()
}

async function loadCurrent() {
  const seq = ++loadGen
  selected.value = -1
  draft.value = null
  action.value = null
  zoom.value = 1
  panX.value = 0
  panY.value = 0
  const sample = current.value
  if (!sample) {
    boxes.value = []
    activeStem.value = ''
    resetHistory()
    dirty.value = false
    return
  }
  const stem = sample.stem
  activeStem.value = stem
  const imgRes = await fetch(datasetApi.imageUrl(datasetId.value, stem), {
    headers: { Authorization: `Bearer ${store.token}` },
  })
  if (seq !== loadGen) return
  const blob = await imgRes.blob()
  const url = URL.createObjectURL(blob)
  const image = new Image()
  image.onload = () => {
    if (seq !== loadGen) { URL.revokeObjectURL(url); return }
    img.value = image
    draw()
    centerImage()
    URL.revokeObjectURL(url)
  }
  image.src = url
  const lab = await datasetApi.labels(datasetId.value, stem)
  if (seq !== loadGen) return
  boxes.value = lab.data.boxes || []
  resetHistory()
  dirty.value = false
  await nextTick()
  draw()
  centerImage()
}

async function flushSave() {
  if (!dirty.value) return true
  return save({ quiet: true, stem: activeStem.value })
}

async function goto(i) {
  if (i === viewIdx.value || switching) return
  switching = true
  try {
    if (!(await flushSave())) return
    viewIdx.value = i
    await loadCurrent()
  } finally {
    switching = false
  }
}

function onBeforeUnload(e) {
  if (!dirty.value) return
  e.preventDefault()
  e.returnValue = ''
}

function centerImage() {
  const wrap = wrapRef.value
  const canvas = canvasRef.value
  if (!wrap || !canvas) return
  panX.value = (wrap.clientWidth - canvas.width) / 2
  panY.value = (wrap.clientHeight - canvas.height) / 2
}

function clampPan() {
  const wrap = wrapRef.value
  const canvas = canvasRef.value
  if (!wrap || !canvas) return
  panX.value = clamp(panX.value, 48 - canvas.width, wrap.clientWidth - 48)
  panY.value = clamp(panY.value, 48 - canvas.height, wrap.clientHeight - 48)
}

function wantsPan(e) {
  return mode.value === 'pan' || spaceDown.value || e.button === 1 || e.button === 2
}

function startPan(e) {
  e.preventDefault()
  action.value = 'pan'
  panOrigin.value = { x: e.clientX, y: e.clientY, px: panX.value, py: panY.value }
  hoverCursor.value = 'grabbing'
  bindDrag()
}

function wrapDown(e) {
  startPan(e)
}

function clamp(v, a = 0, b = 1) {
  return Math.min(b, Math.max(a, v))
}

function boxRect(b) {
  return {
    x1: b.cx - b.w / 2,
    y1: b.cy - b.h / 2,
    x2: b.cx + b.w / 2,
    y2: b.cy + b.h / 2,
  }
}

function toYolo(x1, y1, x2, y2, cls) {
  const nx1 = clamp(Math.min(x1, x2))
  const ny1 = clamp(Math.min(y1, y2))
  const nx2 = clamp(Math.max(x1, x2))
  const ny2 = clamp(Math.max(y1, y2))
  return {
    cls,
    cx: (nx1 + nx2) / 2,
    cy: (ny1 + ny2) / 2,
    w: Math.max(nx2 - nx1, 0.004),
    h: Math.max(ny2 - ny1, 0.004),
  }
}

function handlePoints(b) {
  const r = boxRect(b)
  return {
    nw: [r.x1, r.y1], n: [(r.x1 + r.x2) / 2, r.y1], ne: [r.x2, r.y1],
    e: [r.x2, (r.y1 + r.y2) / 2], se: [r.x2, r.y2], s: [(r.x1 + r.x2) / 2, r.y2],
    sw: [r.x1, r.y2], w: [r.x1, (r.y1 + r.y2) / 2],
  }
}

function hitHandle(p) {
  if (selected.value < 0 || !canvasRef.value) return ''
  const b = boxes.value[selected.value]
  if (!b) return ''
  const w = canvasRef.value.width
  const h = canvasRef.value.height
  const px = p.x * w
  const py = p.y * h
  for (const name of HANDLE_NAMES) {
    const [nx, ny] = handlePoints(b)[name]
    if (Math.abs(px - nx * w) <= HANDLE_PX && Math.abs(py - ny * h) <= HANDLE_PX) return name
  }
  return ''
}

function hitIndex(p) {
  for (let i = boxes.value.length - 1; i >= 0; i -= 1) {
    const b = boxes.value[i]
    if (Math.abs(p.x - b.cx) <= b.w / 2 && Math.abs(p.y - b.cy) <= b.h / 2) return i
  }
  return -1
}

function pixelDist(a, b) {
  const c = canvasRef.value
  if (!c) return 0
  return Math.hypot((a.x - b.x) * c.width, (a.y - b.y) * c.height)
}

function draw() {
  const canvas = canvasRef.value
  const wrap = wrapRef.value
  const image = img.value
  if (!canvas || !wrap || !image) return
  const maxW = Math.max(wrap.clientWidth - 16, 80)
  const maxH = Math.max(wrap.clientHeight - 16, 80)
  fitScale.value = Math.min(maxW / image.width, maxH / image.height, 1)
  const s = viewScale.value
  canvas.width = Math.max(1, Math.round(image.width * s))
  canvas.height = Math.max(1, Math.round(image.height * s))
  const ctx = canvas.getContext('2d')
  ctx.imageSmoothingEnabled = s < 1
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height)
  const all = [...boxes.value]
  if (draft.value) all.push(draft.value)
  all.forEach((b, i) => {
    const x = (b.cx - b.w / 2) * canvas.width
    const y = (b.cy - b.h / 2) * canvas.height
    const bw = b.w * canvas.width
    const bh = b.h * canvas.height
    const color = boxColor(b.cls)
    ctx.strokeStyle = color
    ctx.lineWidth = i === selected.value ? 3 : 2
    ctx.strokeRect(x, y, bw, bh)
    ctx.fillStyle = color
    ctx.font = '12px sans-serif'
    ctx.fillText(classNames.value[b.cls] || String(b.cls), x + 4, Math.max(14, y + 14))
    if (i === selected.value) {
      ctx.fillStyle = '#fff'
      ctx.strokeStyle = color
      ctx.lineWidth = 1
      HANDLE_NAMES.forEach((name) => {
        const [nx, ny] = handlePoints(b)[name]
        const hx = nx * canvas.width
        const hy = ny * canvas.height
        ctx.fillRect(hx - 4, hy - 4, 8, 8)
        ctx.strokeRect(hx - 4, hy - 4, 8, 8)
      })
    }
  })
}

function pos(e) {
  const c = canvasRef.value
  const r = c.getBoundingClientRect()
  const w = r.width || c.width || 1
  const h = r.height || c.height || 1
  return {
    x: clamp((e.clientX - r.left) / w),
    y: clamp((e.clientY - r.top) / h),
  }
}

function bindDrag() {
  if (dragBound) return
  dragBound = true
  window.addEventListener('mousemove', dragMove)
  window.addEventListener('mouseup', dragUp)
}

function unbindDrag() {
  if (!dragBound) return
  dragBound = false
  window.removeEventListener('mousemove', dragMove)
  window.removeEventListener('mouseup', dragUp)
}

function applyResize(p) {
  const orig = origBox.value
  const handle = resizeHandle.value
  if (!orig || !handle || selected.value < 0) return
  let { x1, y1, x2, y2 } = boxRect(orig)
  if (handle.includes('w')) x1 = p.x
  if (handle.includes('e')) x2 = p.x
  if (handle.includes('n')) y1 = p.y
  if (handle.includes('s')) y2 = p.y
  let next = handle
  if (x2 < x1) {
    [x1, x2] = [x2, x1]
    next = next.replace('w', '\0').replace('e', 'w').replace('\0', 'e')
  }
  if (y2 < y1) {
    [y1, y2] = [y2, y1]
    next = next.replace('n', '\0').replace('s', 'n').replace('\0', 's')
  }
  resizeHandle.value = next
  origBox.value = toYolo(x1, y1, x2, y2, orig.cls)
  boxes.value[selected.value] = origBox.value
}

function applyMove(p) {
  const orig = origBox.value
  const from = start.value
  if (!orig || !from || selected.value < 0) return
  const dx = p.x - from.x
  const dy = p.y - from.y
  let cx = orig.cx + dx
  let cy = orig.cy + dy
  cx = clamp(cx, orig.w / 2, 1 - orig.w / 2)
  cy = clamp(cy, orig.h / 2, 1 - orig.h / 2)
  boxes.value[selected.value] = { ...orig, cx, cy }
}

function down(e) {
  if (wantsPan(e)) {
    startPan(e)
    return
  }
  if (e.button !== 0) return
  const p = pos(e)
  start.value = p
  if (mode.value === 'sam') {
    action.value = 'sam'
    bindDrag()
    return
  }
  const handle = hitHandle(p)
  if (handle) {
    action.value = 'resize'
    resizeHandle.value = handle
    origBox.value = { ...boxes.value[selected.value] }
    bindDrag()
    return
  }
  if (e.shiftKey && selected.value >= 0 && hitIndex(p) === selected.value) {
    action.value = 'move'
    origBox.value = { ...boxes.value[selected.value] }
    bindDrag()
    return
  }
  action.value = 'draw'
  drawing.value = true
  draft.value = { cls: clsId.value, cx: p.x, cy: p.y, w: 0, h: 0 }
  bindDrag()
}

function hoverMove(e) {
  if (action.value) return
  updateCursor(pos(e), e)
}

function updateCursor(p, e) {
  if (mode.value === 'pan' || spaceDown.value) {
    hoverCursor.value = 'grab'
    return
  }
  if (mode.value === 'sam') {
    hoverCursor.value = 'pointer'
    return
  }
  const handle = hitHandle(p)
  if (handle) {
    hoverCursor.value = HANDLE_CURSOR[handle]
    return
  }
  if (e?.shiftKey && selected.value >= 0 && hitIndex(p) === selected.value) {
    hoverCursor.value = 'move'
    return
  }
  hoverCursor.value = 'crosshair'
}

function dragMove(e) {
  if (action.value === 'pan' && panOrigin.value) {
    panX.value = panOrigin.value.px + (e.clientX - panOrigin.value.x)
    panY.value = panOrigin.value.py + (e.clientY - panOrigin.value.y)
    clampPan()
    return
  }
  if (mode.value === 'sam' || !start.value) return
  const p = pos(e)
  if (action.value === 'resize') {
    applyResize(p)
    draw()
    return
  }
  if (action.value === 'move') {
    applyMove(p)
    draw()
    return
  }
  if (action.value !== 'draw' || !drawing.value) return
  const x1 = Math.min(start.value.x, p.x)
  const y1 = Math.min(start.value.y, p.y)
  const x2 = Math.max(start.value.x, p.x)
  const y2 = Math.max(start.value.y, p.y)
  draft.value = { cls: clsId.value, cx: (x1 + x2) / 2, cy: (y1 + y2) / 2, w: x2 - x1, h: y2 - y1 }
  draw()
}

async function dragUp(e) {
  unbindDrag()
  const p = pos(e)
  if (action.value === 'pan') {
    action.value = null
    panOrigin.value = null
    hoverCursor.value = (mode.value === 'pan' || spaceDown.value) ? 'grab' : 'crosshair'
    return
  }
  if (mode.value === 'sam' && action.value === 'sam' && start.value && current.value) {
    action.value = null
    start.value = null
    samLoading.value = true
    try {
      const res = await datasetApi.sam(datasetId.value, {
        stem: current.value.stem,
        x: p.x,
        y: p.y,
        cls: clsId.value,
      })
      if (res.data?.box) {
        boxes.value.push(res.data.box)
        commitHistory()
      }
    } finally {
      samLoading.value = false
      draw()
    }
    return
  }
  if (action.value === 'resize' || action.value === 'move') {
    commitHistory()
    action.value = null
    origBox.value = null
    resizeHandle.value = ''
    start.value = null
    draw()
    return
  }
  const moved = start.value ? pixelDist(start.value, p) >= CLICK_PX : false
  if (action.value === 'draw' && !moved) {
    const hit = hitIndex(start.value || p)
    selected.value = hit
    draft.value = null
    drawing.value = false
    action.value = null
    start.value = null
    draw()
    return
  }
  if (draft.value && draft.value.w > 0.006 && draft.value.h > 0.006) {
    boxes.value.push(draft.value)
    selected.value = boxes.value.length - 1
    commitHistory()
  }
  drawing.value = false
  draft.value = null
  action.value = null
  start.value = null
  draw()
}

function setZoom(next, clientX, clientY) {
  const wrap = wrapRef.value
  const canvas = canvasRef.value
  const z = clamp(next, 0.25, 8)
  if (!wrap || !canvas) {
    zoom.value = z
    draw()
    return
  }
  const rect = canvas.getBoundingClientRect()
  const ox = (clientX ?? (rect.left + rect.width / 2)) - rect.left
  const oy = (clientY ?? (rect.top + rect.height / 2)) - rect.top
  const old = viewScale.value
  zoom.value = z
  draw()
  const ratio = viewScale.value / (old || viewScale.value)
  panX.value += ox - ox * ratio
  panY.value += oy - oy * ratio
  clampPan()
}

function nudgeZoom(factor) {
  setZoom(zoom.value * factor)
}

function zoomFit() {
  zoom.value = 1
  draw()
  centerImage()
}

function onWheel(e) {
  const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12
  setZoom(zoom.value * factor, e.clientX, e.clientY)
}

async function save(opts = {}) {
  const stem = opts.stem || current.value?.stem || activeStem.value
  if (!stem) {
    if (!opts.quiet) ElMessage.warning('没有可保存的图片')
    return false
  }
  const payload = cloneBoxes()
  saving.value = true
  try {
    await datasetApi.saveLabels(datasetId.value, { stem, boxes: payload })
    dirty.value = false
    const sample = samples.value.find((s) => s.stem === stem)
    if (sample) {
      sample.annotated = payload.length > 0
      sample.boxCount = payload.length
      sample.classIds = [...new Set(payload.map((b) => b.cls))]
    }
    stats.value.annotated = samples.value.filter((s) => s.annotated).length
    if (!opts.quiet) ElMessage.success(`已保存 ${payload.length} 个框`)
    return true
  } catch {
    return false
  } finally {
    saving.value = false
  }
}

async function prelabel(applyAll) {
  if (!preModelId.value) return
  const loadingRef = applyAll ? preAllLoading : preLoading
  loadingRef.value = true
  try {
    const res = await datasetApi.prelabel(datasetId.value, {
      modelId: preModelId.value,
      stem: current.value?.stem,
      conf: 0.25,
      applyAll,
    })
    ElMessage.success(res.message)
    if (applyAll) await loadSamples()
    else {
      boxes.value = res.data.boxes || []
      if (current.value) {
        current.value.annotated = boxes.value.length > 0
        current.value.boxCount = boxes.value.length
        current.value.classIds = [...new Set(boxes.value.map((b) => b.cls))]
      }
      commitHistory()
      draw()
    }
  } finally {
    loadingRef.value = false
  }
}

function onKey(e) {
  const tag = (e.target && e.target.tagName) || ''
  if (['INPUT', 'TEXTAREA'].includes(tag)) return
  if (e.code === 'Space' && !e.repeat) {
    e.preventDefault()
    spaceDown.value = true
    hoverCursor.value = 'grab'
  }
  if (e.key === 'Delete' && selected.value >= 0) {
    boxes.value.splice(selected.value, 1)
    selected.value = -1
    commitHistory()
    draw()
  }
  if ((e.ctrlKey || e.metaKey) && (e.key === '=' || e.key === '+')) {
    e.preventDefault()
    nudgeZoom(1.25)
  }
  if ((e.ctrlKey || e.metaKey) && e.key === '-') {
    e.preventDefault()
    nudgeZoom(1 / 1.25)
  }
  if ((e.ctrlKey || e.metaKey) && e.key === '0') {
    e.preventDefault()
    zoomFit()
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
    e.preventDefault()
    if (e.shiftKey) redo()
    else undo()
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
    e.preventDefault()
    redo()
  }
  if (e.key === 'ArrowLeft' && viewIdx.value > 0) goto(viewIdx.value - 1)
  if (e.key === 'ArrowRight' && viewIdx.value < viewList.value.length - 1) goto(viewIdx.value + 1)
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); save() }
}

function onKeyUp(e) {
  if (e.code === 'Space') {
    spaceDown.value = false
    if (action.value !== 'pan') hoverCursor.value = (mode.value === 'pan') ? 'grab' : 'crosshair'
  }
}

watch(boxes, draw, { deep: true })
watch(clsId, draw)
watch(mode, () => {
  hoverCursor.value = mode.value === 'pan' ? 'grab' : (mode.value === 'sam' ? 'pointer' : 'crosshair')
})
</script>

<style scoped>
.ann { height: calc(100vh - 120px); display: flex; flex-direction: column; }
.main { flex: 1; display: flex; min-height: 0; gap: 12px; }
.list { width: 220px; overflow: auto; background: #fff; border: 1px solid #ebeef5; }
.item { padding: 8px 10px; cursor: pointer; display: flex; justify-content: space-between; font-size: 12px; }
.item.active { background: #ecf5ff; }
.item.done { color: #67c23a; }
.canvas-wrap {
  flex: 1; background: #111; position: relative; overflow: hidden; min-width: 0;
}
.canvas-stage {
  position: absolute;
  left: 0;
  top: 0;
  will-change: transform;
}
canvas { display: block; }
.hint {
  position: absolute; bottom: 0; left: 0; right: 0;
  color: #cbd5e1; font-size: 12px; padding: 6px 8px;
  background: linear-gradient(transparent, rgba(0,0,0,.65));
  pointer-events: none;
}
</style>
