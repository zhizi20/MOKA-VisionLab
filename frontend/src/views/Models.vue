<template>
  <div>
    <div class="toolbar">
      <el-input v-model="name" placeholder="模型名称" clearable style="width:200px" @keyup.enter="load" />
      <el-button type="primary" @click="openEdit()">新增模型</el-button>
      <el-button type="success" plain :loading="regLoading" @click="registerYolo">一键登记 YOLO11n</el-button>
      <el-button @click="load">刷新</el-button>
    </div>
    <el-table :data="rows" v-loading="loading" border stripe>
      <el-table-column prop="id" label="ID" width="64" />
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="modelKey" label="标识" min-width="140" />
      <el-table-column prop="category" label="分类" width="110" />
      <el-table-column prop="version" label="版本" width="80" />
      <el-table-column label="权重" width="130">
        <template #default="{ row }">
          <el-tag :type="row.hasWeight ? 'success' : 'info'">{{ row.hasWeight ? (row.source === 'builtin' && !row.fileSize ? '内置' : fmt(row.fileSize)) : '未上传' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="source" label="来源" width="90" />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.status === '0' ? 'success' : 'info'">{{ row.status === '0' ? '启用' : '停用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <el-upload :show-file-list="false" :auto-upload="false" accept=".pt" :on-change="(f) => upload(row, f)">
            <el-button link type="warning">上传权重</el-button>
          </el-upload>
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
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { modelApi } from '../api'

const rows = ref([])
const loading = ref(false)
const name = ref('')
const dlg = ref(false)
const saving = ref(false)
const regLoading = ref(false)
const form = reactive({
  id: null, name: '', modelKey: '', version: '1.0', category: '目标检测', description: '', status: '0',
})

function fmt(n) {
  if (!n) return '0'
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
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
  regLoading.value = true
  try {
    const fd = new FormData()
    fd.append('name', 'YOLO11n')
    fd.append('weights', 'yolo11n.pt')
    await modelApi.registerBuiltin(fd)
    ElMessage.success('已登记，首次检测会自动下载权重')
    load()
  } finally {
    regLoading.value = false
  }
}

async function remove(row) {
  await ElMessageBox.confirm(`删除「${row.name}」？`, '提示', { type: 'warning' })
  await modelApi.remove(row.id)
  load()
}

onMounted(load)
</script>
