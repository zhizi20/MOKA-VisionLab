import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useUserStore } from '../store/user'
import router from '../router'

const request = axios.create({ baseURL: '/api', timeout: 15000 })

request.interceptors.request.use((config) => {
  const store = useUserStore()
  if (store.token) config.headers.Authorization = `Bearer ${store.token}`
  return config
})

request.interceptors.response.use(
  (res) => {
    if (res.config.responseType === 'blob') return res.data
    const body = res.data
    if (body.code !== undefined && body.code !== 0) {
      ElMessage.error(body.message || '请求错误')
      return Promise.reject(new Error(body.message))
    }
    return body
  },
  (err) => {
    const status = err.response?.status
    const msg = err.response?.data?.message || err.message
    if (status === 401) {
      useUserStore().logout()
      router.push('/login')
    }
    ElMessage.error(msg || '网络错误')
    return Promise.reject(err)
  },
)

export default request
