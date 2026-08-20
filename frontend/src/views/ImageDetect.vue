<template>
  <div>
    <el-card class="page-card">
      <el-form :inline="true">
        <el-form-item label="模型">
          <el-select v-model="modelId" placeholder="选择已启用且有权重的模型" style="width: 280px">
            <el-option v-for="m in models" :key="m.id" :label="`${m.name}（${m.source}）`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="`置信度 ${conf}`">
          <el-slider v-model="conf" :min="0.05" :max="0.95" :step="0.05" style="width: 140px" />
        </el-form-item>
        <el-form-item :label="`IoU ${iou}`">
          <el-slider v-model="iou" :min="0.1" :max="0.95" :step="0.05" style="width: 140px" />
        </el-form-item>
        <el-form-item>
          <el-upload :show-file-list="false" :auto-upload="false" accept="image/*" :on-change="onPick">
            <el-button>选择图片</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :disabled="!modelId || !file" :loading="loading" @click="run">开始检测</el-button>
        </el-form-item>
      </el-form>
      <div v-if="file" class="hint">已选 {{ file.name }}</div>
    </el-card>
    <el-row :gutter="16" v-if="result">
      <el-col :span="14">
        <el-card header="检测图"><img :src="result.image" class="preview" /></el-card>
      </el-col>
      <el-col :span="10">
        <el-card :header="`检出 ${result.count} 个目标`">
          <el-table :data="result.boxes" size="small" border>
            <el-table-column label="类别">
              <template #default="{ row }">
                <span class="dot" :style="{ background: row.color || '#00e5ff' }" />
                {{ row.cls }}
              </template>
            </el-table-column>
            <el-table-column prop="conf" label="置信度" width="90" />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { detectApi, modelApi } from '../api'

const models = ref([])
const modelId = ref(null)
const conf = ref(0.25)
const iou = ref(0.7)
const file = ref(null)
const loading = ref(false)
const result = ref(null)

onMounted(async () => {
  const res = await modelApi.list()
  models.value = (res.data.rows || []).filter((m) => m.status === '0' && m.hasWeight)
  if (models.value[0]) modelId.value = models.value[0].id
})

function onPick(f) {
  file.value = f.raw
  result.value = null
}

async function run() {
  loading.value = true
  try {
    const fd = new FormData()
    fd.append('file', file.value)
    fd.append('conf', String(conf.value))
    fd.append('iou', String(iou.value))
    const res = await detectApi.image(modelId.value, fd)
    result.value = res.data
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.preview { width: 100%; display: block; border-radius: 6px; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
</style>
