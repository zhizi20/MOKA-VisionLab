<template>
  <div class="ann">
    <div class="toolbar">
      <el-select v-model="datasetId" placeholder="选择数据集" style="width:240px" @change="loadSamples">
        <el-option v-for="d in datasets" :key="d.id" :label="`${d.name}（${d.classNames.join(', ')}）`" :value="d.id" />
      </el-select>
      <el-tag v-if="stats.total">共 {{ stats.total }}</el-tag>
      <el-tag v-if="stats.annotated" type="success">已标 {{ stats.annotated }}</el-tag>
      <el-select v-model="clsId" placeholder="当前类别" style="width:140px">
        <el-option v-for="(c, i) in classNames" :key="c" :label="c" :value="i" />
      </el-select>
      <el-radio-group v-model="mode" size="small">
        <el-radio-button value="draw">画框</el-radio-button>
        <el-radio-button value="sam">SAM 点选</el-radio-button>
      </el-radio-group>
      <el-select v-model="preModelId" placeholder="预标模型" clearable style="width:180px">
        <el-option v-for="m in models" :key="m.id" :label="m.name" :value="m.id" />
      </el-select>
      <el-button :disabled="!preModelId || !current" :loading="preLoading" @click="prelabel(false)">预标本图</el-button>
      <el-button :disabled="!preModelId" :loading="preAllLoading" @click="prelabel(true)">预标全部</el-button>
      <el-button :disabled="idx<=0" @click="goto(idx-1)">上一张</el-button>
      <el-button :disabled="idx>=samples.length-1" @click="goto(idx+1)">下一张</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      <el-button type="danger" plain @click="boxes=[]">清空本图</el-button>
    </div>
    <el-empty v-if="!datasetId" description="请选择数据集。没有标注就无法训练。" />
    <el-empty v-else-if="!samples.length" description="暂无图片，请先上传或抽帧" />
    <div v-else class="main">
      <div class="list">
        <div
          v-for="(s, i) in samples"
          :key="s.stem"
          class="item"
          :class="{ active: i===idx, done: s.annotated }"
          @click="goto(i)"
        >
          {{ s.name }} <el-tag size="small">{{ s.boxCount }}</el-tag>
        </div>
      </div>
      <div class="canvas-wrap" ref="wrapRef" v-loading="samLoading">
        <canvas
          ref="canvasRef"
          :class="mode"
          @mousedown="down"
          @mousemove="move"
          @mouseup="up"
          @mouseleave="cancelDraw"
        />
        <div class="hint">
          {{ mode === 'sam' ? '点击目标，MobileSAM 生成框' : '拖拽画框 · 单击选中 · Delete 删除 · ←/→ 切换 · Ctrl+S 保存' }}
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

const COLORS = ['#ff2d95', '#00e5ff', '#ffd400', '#7cff6b', '#ff8a00']
const route = useRoute()
const store = useUserStore()
const datasets = ref([])
const models = ref([])
const datasetId = ref(null)
const preModelId = ref(null)
const classNames = ref([])
const samples = ref([])
const stats = ref({})
const idx = ref(0)
const clsId = ref(0)
const boxes = ref([])
const saving = ref(false)
const preLoading = ref(false)
const preAllLoading = ref(false)
const samLoading = ref(false)
const mode = ref('draw')
const canvasRef = ref(null)
const wrapRef = ref(null)
const img = ref(null)
const scale = ref(1)
const drawing = ref(false)
const start = ref(null)
const draft = ref(null)
const selected = ref(-1)
const current = computed(() => samples.value[idx.value])

onMounted(async () => {
  const [dsRes, mRes] = await Promise.all([datasetApi.list(), modelApi.list()])
  datasets.value = dsRes.data.rows
  models.value = (mRes.data.rows || []).filter((m) => m.status === '0' && m.hasWeight)
  if (models.value[0]) preModelId.value = models.value[0].id
  const qid = Number(route.query.id)
  if (qid) datasetId.value = qid
  else if (datasets.value[0]) datasetId.value = datasets.value[0].id
  if (datasetId.value) await loadSamples()
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => window.removeEventListener('keydown', onKey))

async function loadSamples() {
  const ds = datasets.value.find((d) => d.id === datasetId.value)
  classNames.value = ds?.classNames || []
  clsId.value = 0
  const res = await datasetApi.samples(datasetId.value)
  samples.value = res.data.samples
  stats.value = res.data.stats
  classNames.value = res.data.classNames || classNames.value
  idx.value = 0
  await loadCurrent()
}

async function loadCurrent() {
  boxes.value = []
  selected.value = -1
  draft.value = null
  if (!current.value) return
  const imgRes = await fetch(datasetApi.imageUrl(datasetId.value, current.value.stem), {
    headers: { Authorization: `Bearer ${store.token}` },
  })
  const blob = await imgRes.blob()
  const url = URL.createObjectURL(blob)
  const image = new Image()
  image.onload = () => { img.value = image; draw(); URL.revokeObjectURL(url) }
  image.src = url
  const lab = await datasetApi.labels(datasetId.value, current.value.stem)
  boxes.value = lab.data.boxes || []
  await nextTick()
  draw()
}

function goto(i) {
  idx.value = i
  loadCurrent()
}

function draw() {
  const canvas = canvasRef.value
  const wrap = wrapRef.value
  const image = img.value
  if (!canvas || !wrap || !image) return
  const maxW = wrap.clientWidth - 8
  const maxH = wrap.clientHeight - 28
  scale.value = Math.min(maxW / image.width, maxH / image.height, 1)
  canvas.width = image.width * scale.value
  canvas.height = image.height * scale.value
  const ctx = canvas.getContext('2d')
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height)
  const all = [...boxes.value]
  if (draft.value) all.push(draft.value)
  all.forEach((b, i) => {
    const x = (b.cx - b.w / 2) * canvas.width
    const y = (b.cy - b.h / 2) * canvas.height
    const w = b.w * canvas.width
    const h = b.h * canvas.height
    ctx.strokeStyle = COLORS[b.cls % COLORS.length]
    ctx.lineWidth = i === selected.value ? 3 : 2
    ctx.strokeRect(x, y, w, h)
    ctx.fillStyle = COLORS[b.cls % COLORS.length]
    ctx.font = '12px sans-serif'
    ctx.fillText(classNames.value[b.cls] || String(b.cls), x + 4, Math.max(14, y + 14))
  })
}

function pos(e) {
  const r = canvasRef.value.getBoundingClientRect()
  return {
    x: (e.clientX - r.left) / canvasRef.value.width,
    y: (e.clientY - r.top) / canvasRef.value.height,
  }
}

function hitIndex(p) {
  for (let i = boxes.value.length - 1; i >= 0; i -= 1) {
    const b = boxes.value[i]
    if (Math.abs(p.x - b.cx) <= b.w / 2 && Math.abs(p.y - b.cy) <= b.h / 2) return i
  }
  return -1
}

function down(e) {
  const p = pos(e)
  start.value = p
  if (mode.value === 'sam') return
  const hit = hitIndex(p)
  if (hit >= 0) {
    selected.value = hit
    drawing.value = false
    draw()
    return
  }
  drawing.value = true
  selected.value = -1
  draft.value = { cls: clsId.value, cx: p.x, cy: p.y, w: 0, h: 0 }
}

function move(e) {
  if (mode.value === 'sam' || !drawing.value || !start.value) return
  const p = pos(e)
  const x1 = Math.min(start.value.x, p.x)
  const y1 = Math.min(start.value.y, p.y)
  const x2 = Math.max(start.value.x, p.x)
  const y2 = Math.max(start.value.y, p.y)
  draft.value = { cls: clsId.value, cx: (x1 + x2) / 2, cy: (y1 + y2) / 2, w: x2 - x1, h: y2 - y1 }
  draw()
}

function cancelDraw() {
  if (mode.value === 'sam') {
    start.value = null
    return
  }
  if (draft.value && draft.value.w > 0.01 && draft.value.h > 0.01) boxes.value.push(draft.value)
  drawing.value = false
  draft.value = null
  start.value = null
  draw()
}

async function up(e) {
  if (mode.value === 'sam' && start.value && current.value) {
    const p = pos(e)
    start.value = null
    samLoading.value = true
    try {
      const res = await datasetApi.sam(datasetId.value, {
        stem: current.value.stem,
        x: p.x,
        y: p.y,
        cls: clsId.value,
      })
      if (res.data?.box) boxes.value.push(res.data.box)
    } finally {
      samLoading.value = false
      draw()
    }
    return
  }
  if (draft.value && draft.value.w > 0.01 && draft.value.h > 0.01) boxes.value.push(draft.value)
  drawing.value = false
  draft.value = null
  start.value = null
  draw()
}

async function save() {
  if (!current.value) return
  saving.value = true
  try {
    await datasetApi.saveLabels(datasetId.value, current.value.stem, { boxes: boxes.value })
    ElMessage.success('已保存')
    current.value.annotated = boxes.value.length > 0
    current.value.boxCount = boxes.value.length
    stats.value.annotated = samples.value.filter((s) => s.annotated).length
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
      }
      draw()
    }
  } finally {
    loadingRef.value = false
  }
}

function onKey(e) {
  if (e.key === 'Delete' && selected.value >= 0) {
    boxes.value.splice(selected.value, 1)
    selected.value = -1
    draw()
  }
  if (e.key === 'ArrowLeft' && idx.value > 0) goto(idx.value - 1)
  if (e.key === 'ArrowRight' && idx.value < samples.value.length - 1) goto(idx.value + 1)
  if (e.ctrlKey && e.key === 's') { e.preventDefault(); save() }
}

watch(boxes, draw, { deep: true })
</script>

<style scoped>
.ann { height: calc(100vh - 120px); display: flex; flex-direction: column; }
.main { flex: 1; display: flex; min-height: 0; gap: 12px; }
.list { width: 220px; overflow: auto; background: #fff; border: 1px solid #ebeef5; }
.item { padding: 8px 10px; cursor: pointer; display: flex; justify-content: space-between; font-size: 12px; }
.item.active { background: #ecf5ff; }
.item.done { color: #67c23a; }
.canvas-wrap {
  flex: 1; background: #111; display: flex; flex-direction: column;
  align-items: center; justify-content: center; position: relative;
}
canvas { max-width: 100%; }
canvas.draw { cursor: crosshair; }
canvas.sam { cursor: pointer; }
</style>
