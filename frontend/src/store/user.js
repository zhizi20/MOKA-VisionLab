import { defineStore } from 'pinia'
import { authApi } from '../api'

const TOKEN_KEY = 'adl_token'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    user: null,
  }),
  getters: {
    nickname: (s) => s.user?.nickname || s.user?.username || '',
  },
  actions: {
    async login(username, password) {
      const res = await authApi.login({ username, password })
      this.token = res.data.token
      localStorage.setItem(TOKEN_KEY, this.token)
      await this.loadInfo()
    },
    async loadInfo() {
      const res = await authApi.info()
      this.user = res.data
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem(TOKEN_KEY)
    },
  },
})
