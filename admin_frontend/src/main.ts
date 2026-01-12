import { createApp } from 'vue'
import { createPinia } from 'pinia'

// Element Plus - 用于 ElMessage 等基础组件
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'

// Design System V2 Tokens
import './styles/tokens.css'
import './styles/index.css'

// V2 响应式样式和 Element Plus 主题覆盖
import './styles/responsive.css'
import './styles/element-plus-theme.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus)

app.mount('#app')
