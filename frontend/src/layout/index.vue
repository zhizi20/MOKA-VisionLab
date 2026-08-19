<template>
  <el-container class="layout">
    <el-aside :width="collapse ? '64px' : '220px'" class="aside">
      <div class="logo">
        <div class="logo-badge">DL</div>
        <span v-show="!collapse" class="logo-text">AI-DetectLab</span>
      </div>
      <el-menu
        :default-active="route.path"
        :collapse="collapse"
        router
        background-color="transparent"
        text-color="#bcd0f5"
        active-text-color="#fff"
        class="side-menu"
      >
        <el-menu-item index="/index">
          <el-icon><HomeFilled /></el-icon>
          <template #title>工作台</template>
        </el-menu-item>
        <el-menu-item index="/models">
          <el-icon><Box /></el-icon>
          <template #title>模型管理</template>
        </el-menu-item>
        <el-menu-item index="/image">
          <el-icon><Picture /></el-icon>
          <template #title>图片检测</template>
        </el-menu-item>
        <el-menu-item index="/video">
          <el-icon><VideoCamera /></el-icon>
          <template #title>视频检测</template>
        </el-menu-item>
        <el-menu-item index="/datasets">
          <el-icon><FolderOpened /></el-icon>
          <template #title>数据集</template>
        </el-menu-item>
        <el-menu-item index="/annotate">
          <el-icon><EditPen /></el-icon>
          <template #title>数据标注</template>
        </el-menu-item>
        <el-menu-item index="/training">
          <el-icon><TrendCharts /></el-icon>
          <template #title>训练任务</template>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <div class="header-left">
          <el-icon class="collapse-btn" @click="collapse = !collapse"><Fold /></el-icon>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/index' }">工作台</el-breadcrumb-item>
            <el-breadcrumb-item v-if="route.meta.title && route.path !== '/index'">{{ route.meta.title }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <el-dropdown @command="onCommand">
          <span class="user">
            <el-avatar :size="30" class="avatar">{{ (store.nickname || 'A').charAt(0) }}</el-avatar>
            <span class="uname">{{ store.nickname }}</span>
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="home">工作台</el-dropdown-item>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main class="main">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useUserStore } from '../store/user'

const route = useRoute()
const router = useRouter()
const store = useUserStore()
const collapse = ref(false)

async function onCommand(cmd) {
  if (cmd === 'home') {
    router.push('/index')
    return
  }
  if (cmd === 'logout') {
    await ElMessageBox.confirm('确定退出登录？', '提示', { type: 'warning' })
    store.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout { height: 100vh; }
.aside {
  background: linear-gradient(180deg, #0c1733 0%, #0a1126 100%);
  border-right: 1px solid rgba(120, 170, 255, 0.12);
  overflow: hidden;
  transition: width 0.28s ease;
  height: 100vh;
  display: flex;
  flex-direction: column;
}
.logo {
  height: 60px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 18px;
  border-bottom: 1px solid rgba(120, 170, 255, 0.12);
}
.logo-badge {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(135deg, #409eff, #6a5acd);
}
.logo-text {
  color: #eaf2ff;
  font-weight: 700;
  font-size: 15px;
  letter-spacing: 0.4px;
  white-space: nowrap;
}
.side-menu { border-right: none; flex: 1; overflow-y: auto; overflow-x: hidden; }
.side-menu :deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(64, 158, 255, 0.25), transparent);
  border-right: 3px solid #409eff;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
}
.header-left { display: flex; align-items: center; gap: 12px; }
.collapse-btn { font-size: 18px; cursor: pointer; color: #606266; }
.user { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.avatar { background: #409eff; color: #fff; }
.uname { color: #303133; }
.main { background: #f4f7fb; }
</style>
