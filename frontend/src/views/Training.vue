<template>
  <div>
    <div class="toolbar">
      <div class="tb-group">
        <div class="tb-label">任务</div>
        <div class="tb-row">
          <el-button type="primary" @click="open">新建任务</el-button>
          <el-button @click="load()">刷新</el-button>
        </div>
      </div>
    </div>
    <p class="howto">流程：选已「构建」的数据集 → 选基座模型 → 创建任务 → 点「启动」。每批张数越大越快、也越吃内存；有显卡请选 GPU 0。</p>
    <el-table :data="rows" v-loading="loading" border stripe>
      <el-table-column prop="jobName" label="任务" min-width="140" />
      <el-table-column prop="datasetName" label="数据集" min-width="120" />
      <el-table-column prop="baseModelLabel" label="基座" min-width="160">
        <template #default="{ row }">{{ row.baseModelLabel || row.baseModel }}</template>
      </el-table-column>
      <el-table-column label="进度" min-width="180">
        <template #default="{ row }">
          <el-progress :percentage="row.progress || 0" :status="row.status==='failed'?'exception':row.status==='done'?'success':undefined" />
          <span v-if="row.status==='running'" class="hint">{{ row.currentEpoch }} / {{ row.epochs }} epoch</span>
        </template>
      </el-table-column>
      <el-table-column label="mAP50" width="90">
        <template #default="{ row }">{{ fmtMap(row.metrics) }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="90" />
      <el-table-column label="操作" width="240">
        <template #default="{ row }">
          <el-button size="small" type="primary" v-if="row.status==='pending' || row.status==='failed'" @click="start(row)">启动</el-button>
          <el-button size="small" @click="detail(row)">详情</el-button>
          <el-button size="small" type="danger" v-if="row.status!=='running'" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dlg" title="新建训练任务" width="520px">
      <el-alert
        v-if="form.device==='cpu' && limits.cpuSafe"
        type="warning"
        :closable="false"
        show-icon
        title="当前是 CPU 保护模式（适合本机测试）。每批张数会被限制，避免把电脑卡死。更好的机器可在 backend/.env 设置 DETECTLAB_CPU_SAFE=0 后重启后端。"
        style="margin-bottom:12px"
      />
      <el-form label-width="100px">
        <el-form-item label="任务名" required><el-input v-model="form.jobName" placeholder="方便以后认出这次训练" /></el-form-item>
        <el-form-item label="数据集" required>
          <el-select v-model="form.datasetId" style="width:100%" placeholder="只显示已构建的数据集">
            <el-option v-for="d in readyDs" :key="d.id" :label="`${d.name} (${d.trainCount}/${d.valCount})`" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="基座模型">
          <el-select v-model="form.baseModel" filterable style="width:100%" placeholder="从哪个预训练权重开始学">
            <el-option-group v-for="g in baseGroups" :key="g.label" :label="g.label">
              <el-option v-for="b in g.options" :key="b.value" :label="b.label" :value="b.value" />
            </el-option-group>
          </el-select>
        </el-form-item>
        <el-form-item label="训练轮数">
          <el-input-number v-model="form.epochs" :min="1" :max="limits.maxEpochs" />
          <span class="hint">看完全部图片一遍算 1 轮</span>
        </el-form-item>
        <el-form-item label="每批张数">
          <el-input-number v-model="form.batch" :min="1" :max="batchMax" />
          <span class="hint">越大越快，也越吃内存</span>
        </el-form-item>
        <el-form-item label="图片边长">
          <el-input-number v-model="form.imgsz" :min="320" :max="imgMax" :step="32" />
          <span class="hint">输入尺寸，一般 640</span>
        </el-form-item>
        <el-form-item label="设备">
          <el-radio-group v-model="form.device">
            <el-radio value="cpu">CPU（本机没显卡）</el-radio>
            <el-radio value="0">GPU 0</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg=false">取消</el-button>
        <el-button type="primary" @click="save">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailDlg" title="训练详情" width="920px" top="6vh" @closed="revokePlots">
      <el-descriptions v-if="detailJob" :column="2" border size="small">
        <el-descriptions-item label="任务">{{ detailJob.jobName }}</el-descriptions-item>
        <el-descriptions-item label="数据集">{{ detailJob.datasetName }}</el-descriptions-item>
        <el-descriptions-item label="基座">{{ detailJob.baseModelLabel || detailJob.baseModel }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ detailJob.status }}</el-descriptions-item>
        <el-descriptions-item label="epochs">{{ detailJob.currentEpoch || 0 }} / {{ detailJob.epochs }}</el-descriptions-item>
        <el-descriptions-item label="batch">{{ detailJob.batch }}</el-descriptions-item>
        <el-descriptions-item label="imgsz">{{ detailJob.imgsz }}</el-descriptions-item>
        <el-descriptions-item label="设备">{{ detailJob.device }}</el-descriptions-item>
        <el-descriptions-item label="进度">{{ detailJob.progress || 0 }}%</el-descriptions-item>
        <el-descriptions-item label="mAP50">{{ fmtMap(detailJob.metrics) }}</el-descriptions-item>
        <el-descriptions-item label="创建时间" :span="2">{{ detailJob.createTime }}</el-descriptions-item>
      </el-descriptions>

      <el-alert v-if="detailJob?.error" type="error" :closable="false" :title="detailJob.error" style="margin-top:12px" />
      <p v-if="detailJob?.logTail" class="hint">{{ detailJob.logTail }}</p>

      <h4 v-if="history.length" class="sec">指标历史</h4>
      <el-table v-if="history.length" :data="history.slice(-20)" size="small" border max-height="240">
        <el-table-column label="epoch" width="80">
          <template #default="{ row }">{{ pick(row, ['epoch']) }}</template>
        </el-table-column>
        <el-table-column label="box_loss" min-width="100">
          <template #default="{ row }">{{ pick(row, ['train/box_loss', 'box_loss']) }}</template>
        </el-table-column>
        <el-table-column label="cls_loss" min-width="100">
          <template #default="{ row }">{{ pick(row, ['train/cls_loss', 'cls_loss']) }}</template>
        </el-table-column>
        <el-table-column label="mAP50" min-width="100">
          <template #default="{ row }">{{ pick(row, ['metrics/mAP50(B)', 'mAP50']) }}</template>
        </el-table-column>
        <el-table-column label="mAP50-95" min-width="110">
          <template #default="{ row }">{{ pick(row, ['metrics/mAP50-95(B)', 'mAP50-95']) }}</template>
        </el-table-column>
      </el-table>

      <h4 class="sec">训练图像</h4>
      <p v-if="classLegend" class="howto">框上的数字对应：{{ classLegend }}</p>
      <p v-if="!plotImages.length" class="hint">训练开始后会出现曲线和样例图；完成后会有混淆矩阵、PR 曲线等。</p>
      <div v-else class="plot-grid">
        <figure v-for="(im, idx) in plotImages" :key="im.key || im.name" class="plot-card">
          <button type="button" class="plot-hit" :title="im.label" @click="openPreview(idx)">
            <img :src="im.url" class="plot-img" :alt="im.label" />
          </button>
          <figcaption>{{ im.label }}</figcaption>
        </figure>
      </div>
    </el-dialog>
    <el-image-viewer
      v-if="previewVisible"
      :url-list="plotUrls"
      :initial-index="previewIndex"
      teleported
      :z-index="4000"
      hide-on-click-modal
      @close="previewVisible = false"
      @switch="onPreviewSwitch"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { datasetApi, jobApi } from '../api'

const rows = ref([])
const loading = ref(false)
const datasets = ref([])
const bases = ref([])
const dlg = ref(false)
const detailDlg = ref(false)
const detailJob = ref(null)
const history = ref([])
const plotImages = ref([])
const previewVisible = ref(false)
const previewIndex = ref(0)
const form = reactive({ jobName: '', datasetId: null, baseModel: 'yolo26n.pt', epochs: 20, batch: 8, imgsz: 640, device: 'cpu' })
const limits = reactive({ cpuSafe: false, cpuMaxBatch: 128, cpuMaxImgsz: 1280, gpuMaxBatch: 128, gpuMaxImgsz: 1280, maxEpochs: 300 })
const readyDs = computed(() => datasets.value.filter((d) => d.status === 'ready'))
const batchMax = computed(() => (form.device === 'cpu' ? limits.cpuMaxBatch : limits.gpuMaxBatch))
const imgMax = computed(() => (form.device === 'cpu' ? limits.cpuMaxImgsz : limits.gpuMaxImgsz))
const plotUrls = computed(() => plotImages.value.map((im) => im.url))
const classLegend = computed(() => {
  const names = detailJob.value?.classNames || []
  if (!names.length) return ''
  return names.map((name, i) => `${i} ${name}`).join('  ·  ')
})
const baseGroups = computed(() => {
  const map = new Map()
  for (const b of bases.value) {
    const key = b.group || '其他'
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(b)
  }
  return [...map.entries()].map(([label, options]) => ({ label, options }))
})
let timer = null

function fmtMap(m) {
  if (!m) return '-'
  const v = m['metrics/mAP50(B)'] ?? m.map50 ?? m.mAP50
  return v == null ? '-' : Number(v).toFixed(3)
}

function pick(row, keys) {
  for (const key of keys) {
    if (row[key] != null && row[key] !== '') return row[key]
  }
  const found = Object.keys(row).find((k) => keys.some((key) => k.includes(key)))
  return found ? row[found] : '-'
}

function revokePlots() {
  previewVisible.value = false
  for (const im of plotImages.value) {
    if (im.url) URL.revokeObjectURL(im.url)
  }
  plotImages.value = []
}

function openPreview(idx) {
  previewIndex.value = idx
  previewVisible.value = true
}

function onPreviewSwitch(idx) {
  previewIndex.value = idx
}

async function loadPlots(id) {
  const res = await jobApi.get(id)
  const data = res.data
  history.value = data.history || []
  detailJob.value = { ...detailJob.value, ...data }
  const incoming = data.plots || []
  const nextKey = incoming.map((p) => `${p.name}:${p.size || 0}:${p.mtime || 0}`).join('|')
  const haveKey = plotImages.value.map((p) => p.key).join('|')
  if (nextKey === haveKey) return
  revokePlots()
  const images = []
  for (const p of incoming) {
    try {
      const blob = await jobApi.plotFile(id, p.name)
      if (blob && blob.type && blob.type.includes('json')) continue
      images.push({
        name: p.name,
        label: p.label,
        key: `${p.name}:${p.size || 0}:${p.mtime || 0}`,
        url: URL.createObjectURL(blob),
      })
    } catch {
      /* skip missing plot */
    }
  }
  plotImages.value = images
}

async function load(opts = {}) {
  const silent = !!opts.silent
  if (!silent) loading.value = true
  try {
    const [j, d, b, lim] = await Promise.all([
      jobApi.list(),
      datasetApi.list(),
      jobApi.baseModels(),
      jobApi.limits().catch(() => ({ data: {} })),
    ])
    rows.value = j.data.rows
    datasets.value = d.data.rows
    bases.value = b.data
    Object.assign(limits, lim.data || {})
    if (detailDlg.value && detailJob.value?.id) {
      await loadPlots(detailJob.value.id)
    }
  } finally {
    if (!silent) loading.value = false
  }
}

watch(() => form.device, (d) => {
  if (d === 'cpu') {
    if (form.batch > limits.cpuMaxBatch) form.batch = limits.cpuMaxBatch
    if (form.imgsz > limits.cpuMaxImgsz) form.imgsz = limits.cpuMaxImgsz
  }
})

function open() {
  form.jobName = 'detect-v1'
  form.datasetId = readyDs.value[0]?.id || null
  form.epochs = 20
  form.batch = 8
  form.imgsz = 640
  dlg.value = true
}

async function save() {
  if (!form.jobName || !form.datasetId) {
    ElMessage.warning('请填写任务名并选择已构建的数据集')
    return
  }
  const res = await jobApi.add(form)
  ElMessage.success(res.message || '已创建')
  dlg.value = false
  load()
}

async function start(row) {
  const res = await jobApi.start(row.id)
  ElMessage.success(res.message || '已启动')
  load()
}

async function detail(row) {
  detailJob.value = row
  history.value = []
  revokePlots()
  detailDlg.value = true
  await loadPlots(row.id)
}

async function remove(row) {
  await ElMessageBox.confirm(`删除「${row.jobName}」？`, '提示', { type: 'warning' })
  await jobApi.remove(row.id)
  load()
}

onMounted(() => {
  load()
  timer = setInterval(() => load({ silent: true }), 4000)
})
onUnmounted(() => {
  timer && clearInterval(timer)
  revokePlots()
})
</script>

<style scoped>
.hint { color: #909399; font-size: 12px; margin: 10px 0 0; }
.sec { margin: 18px 0 8px; font-size: 14px; }
.plot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}
.plot-card { margin: 0; }
.plot-hit {
  display: block;
  width: 100%;
  padding: 0;
  border: 0;
  background: #0f1724;
  border-radius: 8px;
  cursor: zoom-in;
}
.plot-img {
  width: 100%;
  height: 180px;
  object-fit: contain;
  display: block;
  border-radius: 8px;
}
figure { margin: 0; }
figcaption { margin-top: 6px; font-size: 12px; color: #606266; text-align: center; }
</style>
