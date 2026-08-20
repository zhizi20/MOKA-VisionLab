<template>
  <div>
    <div class="toolbar">
      <div class="tb-group">
        <div class="tb-label">搜索</div>
        <el-input v-model="name" placeholder="按名称筛选" clearable style="width:200px" @keyup.enter="load" />
      </div>
      <div class="tb-group">
        <div class="tb-label">内置 YOLO</div>
        <div class="tb-row">
          <el-select v-model="builtinWeights" placeholder="选一个现成权重" style="width: 240px" filterable>
            <el-option-group v-for="g in builtinGroups" :key="g.family" :label="g.family">
              <el-option v-for="b in g.items" :key="b.value" :label="b.hint ? `${b.label}（${b.hint}）` : b.label" :value="b.value" />
            </el-option-group>
          </el-select>
          <el-button type="success" plain :loading="regLoading" :disabled="!builtinWeights" title="下载权重并出现在下面列表里" @click="registerYolo">下载并登记</el-button>
        </div>
      </div>
      <div class="tb-group">
        <div class="tb-label">其他</div>
        <div class="tb-row">
          <el-button type="primary" @click="openEdit()">新增模型</el-button>
          <el-button @click="load">刷新</el-button>
        </div>
      </div>
    </div>
    <p class="howto">用法：选一个内置 YOLO 点「下载并登记」，下完才能用来检测、预标或当训练基座。名字里的 n/s/m/l/x 越大越准，也越慢、越占内存。</p>
    <el-alert v-if="dlHint" class="page-card" :type="dlStatus === 'failed' ? 'error' : 'info'" :closable="false" :title="dlHint" />
    <el-progress
      v-if="dlJobId"
      class="page-card"
      :percentage="dlPct"
      :status="dlStatus === 'failed' ? 'exception' : dlStatus === 'done' ? 'success' : undefined"
    />
    <el-table :data="rows" v-loading="loading" border stripe>
      <el-table-column prop="id" label="ID" width="64" />
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="modelKey" label="标识" min-width="140" />
      <el-table-column prop="category" label="分类" width="110" />
      <el-table-column prop="version" label="版本" width="80" />
      <el-table-column label="权重" width="130">
        <template #default="{ row }">
          <el-tag :type="row.hasWeight ? 'success' : 'info'">
            {{ row.hasWeight ? fmt(row.fileSize) : (row.source === 'builtin' ? '未下载' : '未上传') }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="source" label="来源" width="90" />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.status === '0' ? 'success' : 'info'">{{ row.status === '0' ? '启用' : '停用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="320" fixed="right">
        <template #default="{ row }">
          <el-upload :show-file-list="false" :auto-upload="false" accept=".pt" :on-change="(f) => upload(row, f)">
            <el-button link type="warning">上传权重</el-button>
          </el-upload>
          <el-button v-if="row.source === 'builtin' && !row.hasWeight" link type="success" :loading="row._dl" @click="downloadRow(row)">下载权重</el-button>
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dlg" :title="form.id ? '编辑模型' : '新增模型'" width="480px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="名称" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="标识"><el-input v-model="form.modelKey" :disabled="!!form.id" placeholder="可空，自动生成" /></el-form-item>
        <el-form-item label="版本"><el-input v-model="form.version" /></el-form-item>
        <el-form-item label="分类"><el-input v-model="form.category" /></el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status">
            <el-radio value="0">启用</el-radio>
            <el-radio value="1">停用</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="说明"><el-input v-model="form.description" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { modelApi } from '../api'

const rows = ref([])
const loading = ref(false)
const name = ref('')
const dlg = ref(false)
const saving = ref(false)
const regLoading = ref(false)
const builtins = ref([])
const builtinWeights = ref('yolo26n.pt')
const dlJobId = ref('')
const dlPct = ref(0)
const dlStatus = ref('')
const dlHint = ref('')
let dlTimer = null
const form = reactive({
  id: null, name: '', modelKey: '', version: '1.0', category: '目标检测', description: '', status: '0',
})
const builtinGroups = computed(() => {
  const map = new Map()
  for (const b of builtins.value) {
    if (!map.has(b.family)) map.set(b.family, [])
    map.get(b.family).push(b)
  }
  return [...map.entries()].map(([family, items]) => ({ family, items }))
})

function fmt(n) {
  if (!n) return '0'
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function pollDownload() {
  dlTimer && clearInterval(dlTimer)
  dlTimer = setInterval(async () => {
    const res = await modelApi.downloadProgress(dlJobId.value)
    dlPct.value = res.data.progress || 0
    dlStatus.value = res.data.status
    const got = fmt(res.data.downloaded || 0)
    const total = fmt(res.data.total || 0)
    dlHint.value = res.data.status === 'failed'
      ? (res.data.error || '下载失败')
      : `正在下载 ${res.data.filename || ''}（GitHub 超时会自动换镜像）：${got} / ${total}`
    if (res.data.status === 'done' || res.data.status === 'failed') {
      clearInterval(dlTimer)
      dlTimer = null
      if (res.data.status === 'done') ElMessage.success('权重下载完成')
      else ElMessage.error(res.data.error || '权重下载失败')
      load()
    }
  }, 800)
}

async function startDownload(jobId, message) {
  if (!jobId) {
    ElMessage.success(message || '权重已在本地')
    load()
    return
  }
  dlJobId.value = jobId
  dlPct.value = 0
  dlStatus.value = 'running'
  dlHint.value = message || '开始下载权重'
  pollDownload()
}

async function load() {
  loading.value = true
  try {
    const res = await modelApi.list({ name: name.value })
    rows.value = res.data.rows
  } finally {
    loading.value = false
  }
}

function openEdit(row) {
  Object.assign(form, row
    ? { id: row.id, name: row.name, modelKey: row.modelKey, version: row.version, category: row.category, description: row.description, status: row.status }
    : { id: null, name: '', modelKey: '', version: '1.0', category: '目标检测', description: '', status: '0' })
  dlg.value = true
}

async function save() {
  saving.value = true
  try {
    if (form.id) await modelApi.update(form.id, form)
    else await modelApi.add(form)
    ElMessage.success('已保存')
    dlg.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function upload(row, f) {
  const fd = new FormData()
  fd.append('file', f.raw)
  await modelApi.upload(row.id, fd)
  ElMessage.success('权重已上传')
  load()
}

async function registerYolo() {
  const item = builtins.value.find((b) => b.value === builtinWeights.value)
  if (!item) return
  regLoading.value = true
  try {
    const res = await modelApi.registerBuiltin({ name: item.label, weights: item.value })
    await startDownload(res.data.jobId, res.message)
  } finally {
    regLoading.value = false
  }
}

async function downloadRow(row) {
  row._dl = true
  try {
    const res = await modelApi.downloadWeight(row.id)
    await startDownload(res.data.jobId, res.message)
  } finally {
    row._dl = false
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`删除「${row.name}」？`, '提示', { type: 'warning' })
  await modelApi.remove(row.id)
  load()
}

onMounted(async () => {
  const res = await modelApi.builtins()
  builtins.value = res.data || []
  load()
})
onUnmounted(() => dlTimer && clearInterval(dlTimer))
</script>
