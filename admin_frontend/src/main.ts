import { createApp } from 'vue'
import { createPinia } from 'pinia'

import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'

import './styles/tokens.css'
import './styles/base.css'
import './styles/index.css'
import './styles/element-plus-theme.css'
// 窄屏适配层必须最后引入（它要覆盖上面几层与各页面 scoped 样式）
import './styles/responsive.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus)

app.mount('#app')

// index.html 里的首屏加载提示挂在 #app.loading::before 上，挂载完成后必须摘掉类名，
// 否则「加载中...」会一直盖在界面上（它是一个固定定位的伪元素，不随内容变化消失）。
document.getElementById('app')?.classList.remove('loading')
