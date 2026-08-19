<template>
  <div>
    <el-row :gutter="16" class="page-card">
      <el-col :span="6" v-for="c in cards" :key="c.label">
        <el-card shadow="hover">
          <div class="stat">
            <el-icon :size="28" :color="c.color"><component :is="c.icon" /></el-icon>
            <div>
              <div class="num">{{ c.value }}</div>
              <div class="lbl">{{ c.label }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
    <el-card>
      <template #header>推荐流程</template>
      <el-steps :active="5" align-center>
        <el-step title="登记模型" description="上传 .pt 或一键登记 YOLO11n" />
        <el-step title="建数据集" description="上传图片或视频抽帧" />
        <el-step title="标注" description="画框 / YOLO 预标 / SAM 点选" />
        <el-step title="构建并训练" description="划分 train/val 后启动" />
        <el-step title="图片 / 视频检测" description="用新模型验证效果" />
      </el-steps>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive } from 'vue'
import { datasetApi, jobApi, modelApi } from '../api'

const cards = reactive([
  { label: '模型', value: 0, icon: 'Box', color: '#409eff' },
  { label: '可用权重', value: 0, icon: 'CircleCheck', color: '#67c23a' },
  { label: '数据集', value: 0, icon: 'FolderOpened', color: '#1f6feb' },
  { label: '训练任务', value: 0, icon: 'TrendCharts', color: '#e6a23c' },
])

onMounted(async () => {
  const [m, d, j] = await Promise.all([modelApi.list(), datasetApi.list(), jobApi.list()])
  cards[0].value = m.data.total
  cards[1].value = (m.data.rows || []).filter((x) => x.hasWeight).length
  cards[2].value = d.data.total
  cards[3].value = j.data.total
})
</script>

<style scoped>
.stat { display: flex; gap: 12px; align-items: center; }
.num { font-size: 22px; font-weight: 700; }
.lbl { color: #909399; font-size: 13px; }
</style>
