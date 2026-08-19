<template>
  <div>
    <div class="toolbar">
      <el-button type="primary" @click="open">新建任务</el-button>
      <el-button @click="load">刷新</el-button>
    </div>
    <el-table :data="rows" v-loading="loading" border stripe>
      <el-table-column prop="jobName" label="任务" min-width="140" />
      <el-table-column prop="datasetName" label="数据集" min-width="120" />
      <el-table-column prop="baseModel" label="基座" width="110" />
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

    <el-dialog v-model="dlg" title="新建训练任务" width="480px">
      <el-form label-width="100px">
        <el-form-item label="任务名" required><el-input v-model="form.jobName" /></el-form-item>
        <el-form-item label="数据集" required>
          <el-select v-model="form.datasetId" style="width:100%">
            <el-option v-for="d in readyDs" :key="d.id" :label="`${d.name} (${d.trainCount}/${d.valCount})`" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="基座">
          <el-select v-model="form.baseModel" style="width:100%">
            <el-option v-for="b in bases" :key="b.value" :label="b.label" :value="b.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="epochs"><el-input-number v-model="form.epochs" :min="1" :max="300" /></el-form-item>
        <el-form-item label="batch"><el-input-number v-model="form.batch" :min="1" :max="32" /></el-form-item>
        <el-form-item label="imgsz"><el-input-number v-model="form.imgsz" :min="320" :max="1280" :step="32" /></el-form-item>
        <el-form-item label="设备">
          <el-radio-group v-model="form.device">
            <el-radio value="cpu">CPU</el-radio>
            <el-radio value="0">GPU 0</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg=false">取消</el-button>
        <el-button type="primary" @click="save">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailDlg" title="训练详情" width="560px">
      <pre class="log">{{ detailJob?.error || JSON.stringify(detailJob?.metrics, null, 2) || '暂无指标' }}</pre>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { datasetApi, jobApi } from '../api'

const rows = ref([])
const loading = ref(false)
const datasets = ref([])
const bases = ref([])
const dlg = ref(false)
const detailDlg = ref(false)
const detailJob = ref(null)
const form = reactive({ jobName: '', datasetId: null, baseModel: 'yolo11n.pt', epochs: 20, batch: 4, imgsz: 640, device: 'cpu' })
const readyDs = computed(() => datasets.value.filter((d) => d.status === 'ready'))
let timer = null

function fmtMap(m) {
  if (!m) return '-'
  const v = m['metrics/mAP50(B)'] ?? m.map50 ?? m.mAP50
  return v == null ? '-' : Number(v).toFixed(3)
}

async function load() {
  loading.value = true
  try {
    const [j, d, b] = await Promise.all([jobApi.list(), datasetApi.list(), jobApi.baseModels()])
    rows.value = j.data.rows
    datasets.value = d.data.rows
    bases.value = b.data
  } finally {
    loading.value = false
  }
}

function open() {
  form.jobName = 'detect-v1'
  form.datasetId = readyDs.value[0]?.id || null
  dlg.value = true
}

async function save() {
  if (!form.jobName || !form.datasetId) {
    ElMessage.warning('请填写任务名并选择已构建的数据集')
    return
  }
  await jobApi.add(form)
  dlg.value = false
  load()
}

async function start(row) {
  await jobApi.start(row.id)
  ElMessage.success('已启动，CPU 训练可能较慢')
  load()
}

function detail(row) {
  detailJob.value = row
  detailDlg.value = true
}

async function remove(row) {
  await ElMessageBox.confirm(`删除「${row.jobName}」？`, '提示', { type: 'warning' })
  await jobApi.remove(row.id)
  load()
}

onMounted(() => {
  load()
  timer = setInterval(load, 4000)
})
onUnmounted(() => timer && clearInterval(timer))
</script>

<style scoped>
.log { background: #0f1724; color: #d1e0ff; padding: 12px; min-height: 120px; overflow: auto; }
</style>
