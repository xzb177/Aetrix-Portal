import './styles/aurora.css'
import './styles/neo-noir-tokens.css'
import './styles/index.css'
import './styles/mobile.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
// 站点品牌（能力：站点与品牌）：站名 / Logo / 主题色 / SEO 由后台配置，启动时读一次。
// 先挂载再拉取，不让一次额外的请求把首屏拖住；拉到之后主题色与标题会自己更新。
import { initBranding } from './composables/useBranding'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)

app.mount('#app')
void initBranding()
