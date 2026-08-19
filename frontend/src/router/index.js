import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '../store/user'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('../views/Login.vue'), meta: { public: true } },
    {
      path: '/',
      component: () => import('../layout/index.vue'),
      redirect: '/index',
      children: [
        { path: 'index', component: () => import('../views/Dashboard.vue'), meta: { title: '工作台' } },
        { path: 'models', component: () => import('../views/Models.vue'), meta: { title: '模型管理' } },
        { path: 'image', component: () => import('../views/ImageDetect.vue'), meta: { title: '图片检测' } },
        { path: 'video', component: () => import('../views/VideoDetect.vue'), meta: { title: '视频检测' } },
        { path: 'datasets', component: () => import('../views/Datasets.vue'), meta: { title: '数据集' } },
        { path: 'annotate', component: () => import('../views/Annotate.vue'), meta: { title: '数据标注' } },
        { path: 'training', component: () => import('../views/Training.vue'), meta: { title: '训练任务' } },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const store = useUserStore()
  if (to.meta.public) {
    if (store.token && to.path === '/login') return { path: '/index' }
    return true
  }
  if (!store.token) return { path: '/login' }
  if (!store.user) {
    try {
      await store.loadInfo()
    } catch {
      store.logout()
      return { path: '/login' }
    }
  }
  return true
})

export default router
