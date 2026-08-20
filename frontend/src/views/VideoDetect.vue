<template>
  <div>
    <el-card class="page-card">
      <el-form :inline="true">
        <el-form-item label="模型">
          <el-select v-model="modelId" placeholder="选择模型" style="width: 280px">
            <el-option v-for="m in models" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="`置信度 ${conf}`">
          <el-slider v-model="conf" :min="0.05" :max="0.95" :step="0.05" style="width: 140px" />
        </el-form-item>
        <el-form-item :label="`IoU ${iou}`">
          <el-slider v-model="iou" :min="0.1" :max="0.95" :step="0.05" style="width: 140px" />
        </el-form-item>
        <el-form-item>
          <el-upload :show-file-list="false" :auto-upload="false" accept="video/*" :on-change="onPick">
            <el-button>选择视频</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :disabled="!modelId || !file" :loading="starting" @click="run">开始检测</el-button>
        </el-form-item>
      </el-form>
      <div v-if="file" class="hint">已选 {{ file.name }}</div>
      <el-progress
        v-if="jobId"
        style="margin-top: 12px"
        :percentage="progress"
        :status="status === 'failed' ? 'exception' : status === 'done' ? 'success' : undefined"
      />
      <div v-if="error" class="hint" style="color:#f56c6c">{{ error }}</div>
      <el-button v-if="output" type="success" style="margin-top:12px" @click="download">下载结果视频</el-button>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { detectApi, modelApi } from '../api'

const models = ref([])
const modelId = ref(null)
const conf = ref(0.25)
const iou = ref(0.7)
const file = ref(null)
const starting = ref(false)
const jobId = ref('')
const progress = ref(0)
const status = ref('')
const error = ref('')
const output = ref('')
let timer = null

onMounted(async () => {
  const res = await modelApi.list()
  models.value = (res.data.rows || []).filter((m) => m.status === '0' && m.hasWeight)
  if (models.value[0]) modelId.value = models.value[0].id
})
onUnmounted(() => timer && clearInterval(timer))

function onPick(f) {
  file.value = f.raw
  jobId.value = ''
  output.value = ''
  error.value = ''
  progress.value = 0
}

async function run() {
  starting.value = true
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('conf', String(conf.value))
    fd.append('iou', String(iou.value))
    const res = await detectApi.video(modelId.value, fd)
    jobId.value = res.data.jobId
    poll()
  } finally {
    starting.value = false
  }
}

function poll() {
  timer && clearInterval(timer)
  timer = setInterval(async () => {
    const res = await detectApi.progress(modelId.value, jobId.value)
    progress.value = res.data.progress || 0
    status.value = res.data.status
    error.value = res.data.error || ''
    if (res.data.status === 'done' || res.data.status === 'failed') {
      clearInterval(timer)
      output.value = res.data.output || ''
      if (res.data.status === 'done') ElMessage.success('视频检测完成')
    }
  }, 1000)
}

async function download() {
  const blob = await detectApi.output(output.value)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = output.value
  a.click()
  URL.revokeObjectURL(url)
}
</script>
