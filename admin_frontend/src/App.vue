<script setup lang="ts">
import { RouterView } from 'vue-router'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import Toast from '@/components/Toast.vue'
</script>

<template>
  <!--
    Element Plus 内置文案统一中文（v2.42.5）：分页的「Go to previous page / page 2」、
    表格与下拉的空态（No Data）、日期选择器等都是组件库自带的英文串。
    按需引入模式下不能 app.use(ElementPlus,{locale})（会全量打包），
    所以用 ConfigProvider 把 locale 注入组件树。
  -->
  <el-config-provider :locale="zhCn">
    <RouterView />
    <Toast />
  </el-config-provider>
</template>

<style>
html,
body {
  margin: 0;
  padding: 0;
  height: 100%;
  background: var(--color-bg-primary, #0a0a0a);
}

#app {
  height: 100%;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
  color: var(--color-text-primary, #fff);
}
</style>
