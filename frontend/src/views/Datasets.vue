<template>
  <div>
    <div class="toolbar">
      <div class="tb-group">
        <div class="tb-label">新建</div>
        <el-button type="primary" @click="open()">新建数据集</el-button>
      </div>
      <div class="tb-group">
        <div class="tb-label">导入现成标注</div>
        <el-upload :show-file-list="false" :auto-upload="false" accept=".ndjson" :on-change="onNdjson">
          <el-button type="success" plain :loading="importing" title="导入 Ultralytics 的 .ndjson 数据包">导入 NDJSON</el-button>
        </el-upload>
      </div>
      <div class="tb-group">
        <div class="tb-label">列表</div>
        <el-button @click="load">刷新</el-button>
      </div>
    </div>
    <p class="howto">流程：新建或导入 → 上传图片（或视频抽帧）→ 去「数据标注」画框 → 回来点「构建」划分训练/验证 → 再去「训练任务」。</p>
    <el-alert
      v-if="importHint"
      class="page-card"
      :type="importStatus === 'failed' || importFailures.length ? 'warning' : 'info'"
      :closable="false"
      :title="importHint"
    />
    <el-progress
      v-if="importJobId"
      class="page-card"
      :percentage="importPct"
      :status="importStatus === 'failed' ? 'exception' : (importStatus === 'done' && !importFailures.length) ? 'success' : undefined"
    />
    <el-table v-if="importFailures.length" :data="importFailures" size="small" border class="page-card" max-height="240">
      <el-table-column prop="file" label="失败图片" min-width="220" />
      <el-table-column prop="split" label="划分" width="80" />
      <el-table-column prop="error" label="原因" min-width="220" />
    </el-table>
    <el-table :data="rows" v-loading="loading" border stripe>
      <el-table-column prop="name" label="名称" min-width="120" />
      <el-table-column label="类别" min-width="160">
        <template #default="{ row }">
          <el-tag
            v-for="(c, i) in row.classNames"
            :key="c"
            size="small"
            style="margin:2px"
            :style="{ borderColor: row.colors?.[i], color: row.colors?.[i] }"
          >{{ c }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="图片" width="90">
        <template #default="{ row }">{{ row.imageCount || 0 }}</template>
      </el-table-column>
      <el-table-column label="已标注" width="110">
        <template #default="{ row }">{{ row.labeledCount || 0 }} / {{ row.imageCount || 0 }}</template>
      </el-table-column>
      <el-table-column label="训练划分" width="120">
        <template #default="{ row }">
          <span v-if="row.built">{{ row.trainCount }} / {{ row.valCount }}</span>
          <span v-else class="hint">未构建</span>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusType(row)">{{ statusText(row) }}</el-tag>
          <el-progress
            v-if="row.importJob"
            :percentage="row.importJob.progress || 0"
            :stroke-width="6"
            style="margin-top:6px"
          />
        </template>
      </el-table-column>
      <el-table-column label="操作" min-width="640" fixed="right">
        <template #default="{ row }">
          <div class="ops">
            <div class="ops-inline">
              <el-upload :show-file-list="false" :auto-upload="false" multiple accept="image/*" :on-change="(f) => upload(row, f)">
                <el-button size="small" title="把图片加进这个数据集">上传图片</el-button>
              </el-upload>
              <el-upload :show-file-list="false" :auto-upload="false" accept="video/*" :on-change="(f) => extract(row, f)">
                <el-button size="small" title="从视频里抽出图片当训练样本">视频抽帧</el-button>
              </el-upload>
            </div>
            <el-button size="small" type="primary" plain title="预览图片和磁盘路径" @click="browse(row)">打开</el-button>
            <el-button size="small" type="warning" title="给图片画检测框" @click="$router.push({ path: '/annotate', query: { id: row.id } })">标注</el-button>
            <el-button size="small" type="success" :disabled="row.status==='importing'" :loading="row._building" title="按训练比例划分 train/val，训练前必须点一次" @click="build(row)">构建</el-button>
            <el-button size="small" v-if="row.importJob && !row.importJob.paused" @click="pause(row)">暂停</el-button>
            <el-button size="small" type="primary" v-if="row.importJob?.paused" @click="resume(row)">继续</el-button>
            <el-button
              size="small"
              type="danger"
              plain
              v-if="row.hasImport && row.failedCount > 0 && !row.importJob"
              :loading="row._retrying"
              @click="retry(row)"
            >重试失败</el-button>
            <el-button size="small" @click="open(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dlg" :title="form.id ? '编辑数据集' : '新建数据集'" width="520px">
      <el-form label-width="90px">
        <el-form-item label="名称" required><el-input v-model="form.name" placeholder="例如：烟雾检测" /></el-form-item>
        <el-form-item label="类别" required>
          <el-select v-model="form.classNames" multiple filterable allow-create default-first-option placeholder="要识别的东西，如 fire、smoke，回车添加" style="width:100%" />
        </el-form-item>
        <el-form-item label="训练比例">
          <el-slider v-model="form.splitRatio" :min="0.5" :max="0.95" :step="0.05" show-input />
          <div class="hint">拿去训练的占比，剩下的用来验证。一般 0.8 即可。</div>
        </el-form-item>
        <el-form-item label="说明"><el-input v-model="form.description" type="textarea" placeholder="可选，方便以后认出这批数据" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="browseDlg" :title="browseTitle" width="860px" @closed="clearThumbs">
      <div class="browse-bar">
        <span class="hint">{{ browsePath }}</span>
        <el-button size="small" type="primary" :disabled="!browseRow" @click="openFolder">在资源管理器中打开</el-button>
        <el-button size="small" type="warning" :disabled="!browseRow" @click="goAnnotate()">去标注</el-button>
      </div>
      <el-empty v-if="!browseThumbs.length && !browseLoading" description="还没有图片，先上传或抽帧" />
      <div v-loading="browseLoading" class="thumb-grid">
        <div v-for="s in browseThumbs" :key="s.stem" class="thumb" @click="goAnnotate(s.stem)">
          <img v-if="s.src" :src="s.src" />
          <div class="thumb-name">{{ s.name }}</div>
          <el-tag size="small" :type="s.annotated ? 'success' : 'info'">{{ s.annotated ? `已标 ${s.boxCount}` : '未标' }}</el-tag>
        </div>
      </div>
      <div v-if="browseTotal > browseThumbs.length" class="hint">预览前 {{ browseThumbs.length }} 张，共 {{ browseTotal }} 张。完整检查请打开目录或进入标注。</div>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { datasetApi } from '../api'
import { useUserStore } from '../store/user'

const router = useRouter()
const store = useUserStore()
const rows = ref([])
const loading = ref(false)
const dlg = ref(false)
const importing = ref(false)
const importJobId = ref('')
const importPct = ref(0)
const importStatus = ref('')
const importHint = ref('')
const importFailures = ref([])
const form = reactive({ id: null, name: '', classNames: [], splitRatio: 0.8, description: '' })
const browseDlg = ref(false)
const browseRow = ref(null)
const browseThumbs = ref([])
const browseLoading = ref(false)
const browseTotal = ref(0)
const browsePath = ref('')
const browseTitle = ref('打开数据集')
let importTimer = null
let listTimer = null

function statusText(row) {
  if (row.importJob?.paused) return '已暂停'
  if (row.importJob || row.status === 'importing') return '下载中'
  if (row.status === 'incomplete') return `缺 ${row.failedCount} 张`
  if (row.status === 'ready') return '已构建'
  if (row.status === 'raw') return '未构建'
  return row.status
}

function statusType(row) {
  if (row.importJob?.paused) return 'info'
  if (row.importJob || row.status === 'importing') return 'warning'
  if (row.status === 'incomplete') return 'danger'
  if (row.status === 'ready') return 'success'
  return 'info'
}

function anyActive(list = rows.value) {
  return list.some((r) => r.importJob || r.status === 'importing')
}

function startListPoll() {
  listTimer && clearInterval(listTimer)
  listTimer = setInterval(async () => {
    const res = await datasetApi.list()
    rows.value = res.data.rows
    if (!anyActive(res.data.rows)) {
      clearInterval(listTimer)
      listTimer = null
    }
  }, 1500)
}

async function onNdjson(f) {
  const fd = new FormData()
  fd.append('file', f.raw)
  importing.value = true
  importHint.value = '正在解析索引并后台下载图片'
  try {
    const res = await datasetApi.importNdjson(fd)
    importJobId.value = res.data.jobId
    importPct.value = 0
    importStatus.value = 'running'
    importFailures.value = []
    ElMessage.success(res.message)
    pollImport()
    await load()
    startListPoll()
  } finally {
    importing.value = false
  }
}

function pollImport() {
  importTimer && clearInterval(importTimer)
  importTimer = setInterval(async () => {
    const res = await datasetApi.importProgress(importJobId.value)
    importPct.value = res.data.progress || 0
    importStatus.value = res.data.status
    const failed = res.data.failed || 0
    const okCount = res.data.processed || 0
    importFailures.value = res.data.failures || []
    if (res.data.status === 'paused') {
      importHint.value = `已暂停 ${okCount} / ${res.data.total || 0}，失败 ${failed}`
      return
    }
    importHint.value = `已下载 ${okCount} / ${res.data.total || 0}，失败 ${failed}`
    if (res.data.status === 'done' || res.data.status === 'failed') {
      clearInterval(importTimer)
      importTimer = null
      if (res.data.status === 'done' && failed) {
        ElMessage.warning(`导入未完整：成功 ${okCount} 张，失败 ${failed} 张，可点「重试失败」`)
      } else if (res.data.status === 'done') {
        ElMessage.success(`导入完成 train=${res.data.trainCount} val=${res.data.valCount}`)
      } else {
        ElMessage.error(res.data.error || '导入失败')
      }
      load()
    }
  }, 1500)
}

async function load() {
  loading.value = true
  try {
    const res = await datasetApi.list()
    rows.value = res.data.rows
    if (anyActive(res.data.rows)) startListPoll()
  } finally {
    loading.value = false
  }
}

function open(row) {
  Object.assign(form, row
    ? { id: row.id, name: row.name, classNames: [...row.classNames], splitRatio: row.splitRatio, description: row.description }
    : { id: null, name: '', classNames: [], splitRatio: 0.8, description: '' })
  dlg.value = true
}

async function save() {
  if (!form.name || !form.classNames.length) {
    ElMessage.warning('请填写名称和类别')
    return
  }
  if (form.id) await datasetApi.update(form.id, form)
  else await datasetApi.add(form)
  dlg.value = false
  load()
}

async function upload(row, f) {
  const fd = new FormData()
  fd.append('files', f.raw)
  await datasetApi.upload(row.id, fd)
  ElMessage.success(`已上传 ${f.name}`)
  load()
}

async function extract(row, f) {
  const fd = new FormData()
  fd.append('file', f.raw)
  fd.append('frameInterval', '10')
  fd.append('maxFrames', '60')
  ElMessage.info('正在抽帧…')
  await datasetApi.extract(row.id, fd)
  ElMessage.success('抽帧完成，可去标注')
  load()
}

async function retry(row) {
  if (!row.hasImport) {
    ElMessage.warning('该数据集没有绑定自己的 NDJSON，不能重试其它数据集的下载')
    return
  }
  row._retrying = true
  try {
    const res = await datasetApi.retryImport(row.id)
    if (!res.data.missing) {
      ElMessage.success(res.message)
      load()
      return
    }
    importJobId.value = res.data.jobId
    importPct.value = 0
    importStatus.value = 'running'
    importFailures.value = []
    importHint.value = res.message
    ElMessage.success(res.message)
    pollImport()
    await load()
    startListPoll()
  } finally {
    row._retrying = false
  }
}

async function pause(row) {
  await datasetApi.pauseImport(row.id)
  ElMessage.success('已暂停')
  load()
}

async function resume(row) {
  const res = await datasetApi.resumeImport(row.id)
  importJobId.value = res.data?.jobId || importJobId.value
  importStatus.value = 'running'
  importHint.value = '已继续下载'
  ElMessage.success('已继续')
  pollImport()
  startListPoll()
  load()
}

async function browse(row) {
  browseRow.value = row
  browseTitle.value = `打开数据集 · ${row.name}`
  browsePath.value = row.folderPath || ''
  browseDlg.value = true
  browseLoading.value = true
  browseTotal.value = row.imageCount || 0
  try {
    const res = await datasetApi.samples(row.id)
    browsePath.value = res.data.folderPath || browsePath.value
    const list = (res.data.samples || []).slice(0, 60)
    browseTotal.value = (res.data.samples || []).length
    const thumbs = []
    for (let i = 0; i < list.length; i += 8) {
      const part = list.slice(i, i + 8)
      const chunk = await Promise.all(part.map(async (s) => {
        const imgRes = await fetch(datasetApi.imageUrl(row.id, s.stem), {
          headers: { Authorization: `Bearer ${store.token}` },
        })
        const blob = await imgRes.blob()
        return { ...s, src: URL.createObjectURL(blob) }
      }))
      thumbs.push(...chunk)
      browseThumbs.value = [...thumbs]
    }
  } finally {
    browseLoading.value = false
  }
}

function clearThumbs() {
  browseThumbs.value.forEach((t) => t.src && URL.revokeObjectURL(t.src))
  browseThumbs.value = []
  browseRow.value = null
}

async function openFolder() {
  if (!browseRow.value) return
  const res = await datasetApi.openFolder(browseRow.value.id)
  ElMessage.success(res.message || '已打开')
}

function goAnnotate(stem) {
  const id = browseRow.value?.id
  if (!id) return
  browseDlg.value = false
  const query = { id }
  if (typeof stem === 'string' && stem) query.stem = stem
  router.push({ path: '/annotate', query })
}

async function build(row) {
  row._building = true
  try {
    const res = await datasetApi.build(row.id)
    ElMessage.success(res.message)
    load()
  } finally {
    row._building = false
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`删除「${row.name}」？`, '提示', { type: 'warning' })
  await datasetApi.remove(row.id)
  load()
}

onMounted(load)
onUnmounted(() => {
  importTimer && clearInterval(importTimer)
  listTimer && clearInterval(listTimer)
  clearThumbs()
})
</script>

<style scoped>
.ops { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; }
.ops-inline { display: inline-flex; flex-wrap: nowrap; align-items: center; gap: 4px; }
.ops :deep(.el-upload) { display: inline-flex; }
.browse-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.thumb-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; max-height: 520px; overflow: auto; }
.thumb { background: #f5f7fa; border: 1px solid #ebeef5; border-radius: 6px; padding: 6px; cursor: pointer; }
.thumb img { width: 100%; height: 100px; object-fit: cover; border-radius: 4px; display: block; }
.thumb-name { font-size: 12px; margin: 4px 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
