import './styles/neo-noir-tokens.css'
import './styles/index.css'
import './styles/mobile.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)

app.mount('#app')

// 初始化线路配置 Store
// 在应用挂载后执行，确保 Pinia 已就绪
import { useRouteStore } from './stores/route'
import { useUserStore } from './stores/user'

// 延迟初始化以避免在应用挂载前执行
setTimeout(() => {
  try {
    const userStore = useUserStore()
    userStore.init() // 确保用户 store 已初始化

    const routeStore = useRouteStore()
    routeStore.init() // 初始化线路配置
  } catch (error) {
    console.error('Failed to initialize stores:', error)
  }
}, 0)
