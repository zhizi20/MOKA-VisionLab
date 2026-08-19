<template>
  <div class="login">
    <el-card class="box" shadow="always">
      <div class="brand">
        <div class="badge">DL</div>
        <div>
          <h2>AI-DetectLab</h2>
          <p>视觉检测实验室</p>
        </div>
      </div>
      <el-form @submit.prevent="onSubmit">
        <el-form-item><el-input v-model="username" placeholder="账号" /></el-form-item>
        <el-form-item><el-input v-model="password" type="password" placeholder="密码" show-password /></el-form-item>
        <el-button type="primary" style="width:100%" :loading="loading" native-type="submit">登录</el-button>
      </el-form>
      <p class="tip">默认账号 admin / admin123</p>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '../store/user'

const router = useRouter()
const store = useUserStore()
const username = ref('admin')
const password = ref('admin123')
const loading = ref(false)

async function onSubmit() {
  loading.value = true
  try {
    await store.login(username.value, password.value)
    ElMessage.success('登录成功')
    router.push('/index')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login {
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: radial-gradient(1200px 600px at 20% 10%, #1d4ed8 0%, transparent 50%),
    linear-gradient(160deg, #0c1733, #111827);
}
.box { width: 400px; border-radius: 12px; }
.brand { display: flex; gap: 12px; align-items: center; margin-bottom: 18px; }
.badge {
  width: 42px; height: 42px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-weight: 800; color: #fff;
  background: linear-gradient(135deg, #409eff, #6a5acd);
}
h2 { margin: 0; font-size: 22px; }
p { color: #909399; margin: 4px 0 0; }
.tip { margin-top: 14px; font-size: 12px; color: #909399; }
</style>
