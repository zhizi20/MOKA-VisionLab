<template>
  <div>
    <div class="toolbar">
      <el-button type="primary" @click="open()">新建数据集</el-button>
      <el-button @click="load">刷新</el-button>
    </div>
    <el-table :data="rows" v-loading="loading" border stripe>
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column label="类别" min-width="180">
        <template #default="{ row }">
          <el-tag v-for="c in row.classNames" :key="c" size="small" style="margin:2px">{{ c }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="train / val" width="120">
        <template #default="{ row }">{{ row.trainCount }} / {{ row.valCount }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="90" />
      <el-table-column label="操作" width="460" fixed="right">
        <template #default="{ row }">
          <el-upload :show-file-list="false" :auto-upload="false" multiple accept="image/*" :on-change="(f) => upload(row, f)">
            <el-button size="small">上传图片</el-button>
          </el-upload>
          <el-upload :show-file-list="false" :auto-upload="false" accept="video/*" :on-change="(f) => extract(row, f)">
            <el-button size="small">视频抽帧</el-button>
          </el-upload>
          <el-button size="small" type="warning" @click="$router.push({ path: '/annotate', query: { id: row.id } })">标注</el-button>
          <el-button size="small" type="success" :loading="row._building" @click="build(row)">构建</el-button>
          <el-button size="small" @click="open(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dlg" :title="form.id ? '编辑数据集' : '新建数据集'" width="520px">
      <el-form label-width="90px">
        <el-form-item label="名称" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="类别" required>
          <el-select v-model="form.classNames" multiple filterable allow-create default-first-option placeholder="如 fire, smoke" style="width:100%" />
        </el-form-item>
        <el-form-item label="训练比例">
          <el-slider v-model="form.splitRatio" :min="0.5" :max="0.95" :step="0.05" show-input />
        </el-form-item>
        <el-form-item label="说明"><el-input v-model="form.description" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { datasetApi } from '../api'

const rows = ref([])
const loading = ref(false)
const dlg = ref(false)
const form = reactive({ id: null, name: '', classNames: [], splitRatio: 0.8, description: '' })

async function load() {
  loading.value = true
  try {
    const res = await datasetApi.list()
    rows.value = res.data.rows
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
}

async function extract(row, f) {
  const fd = new FormData()
  fd.append('file', f.raw)
  fd.append('frameInterval', '10')
  fd.append('maxFrames', '60')
  ElMessage.info('正在抽帧…')
  await datasetApi.extract(row.id, fd)
  ElMessage.success('抽帧完成，可去标注')
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
</script>
