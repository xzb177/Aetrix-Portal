<script setup lang="ts">
/**
 * UI 组件使用示例
 *
 * 演示所有基础组件的用法
 */
import { ref } from 'vue'
import { Card, SectionHeader, StatCard, ListItem, Tag, Button, AppBar, TabBar } from './index'
import type { Tab } from './TabBar.vue'

// TabBar 数据
const activeTab = ref('home')
const tabs: Tab[] = [
  { key: 'home', label: '首页', icon: '/icons/home.svg' },
  { key: 'orders', label: '订单', icon: '/icons/orders.svg', badge: 3 },
  { key: 'profile', label: '我的', icon: '/icons/profile.svg' }
]

const handleTabChange = (key: string) => {
  activeTab.value = key
}

const handleBack = () => {
  console.log('Back clicked')
}

// 按钮加载状态
const loading = ref(false)
const handleClick = () => {
  loading.value = true
  setTimeout(() => {
    loading.value = false
  }, 2000)
}
</script>

<template>
  <div class="ui-examples">
    <!-- AppBar 示例 -->
    <AppBar title="组件示例" :show-back="true" @back="handleBack">
      <template #action>
        <button class="icon-btn">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <path d="M10 13C11.6569 13 13 11.6569 13 10C13 8.34315 11.6569 7 10 7C8.34315 7 7 8.34315 7 10C7 11.6569 8.34315 13 10 13Z" stroke="currentColor" stroke-width="1.5"/>
            <path d="M17 10C17 13.866 13.866 17 10 17C6.13401 17 3 13.866 3 10C3 6.13401 6.13401 3 10 3C13.866 3 17 6.13401 17 10Z" stroke="currentColor" stroke-width="1.5"/>
          </svg>
        </button>
      </template>
    </AppBar>

    <div class="ui-examples__content">
      <!-- SectionHeader 示例 -->
      <SectionHeader title="统计卡片" subtitle="展示关键数据指标" />

      <!-- StatCard 示例 -->
      <div class="ui-examples__row">
        <StatCard
          icon="/icons/users.svg"
          value="1,234"
          label="用户总数"
          trend="+12%"
          :trend-up="true"
          color="success"
        />
        <StatCard
          icon="/icons/orders.svg"
          value="567"
          label="今日订单"
          trend="-3%"
          :trend-up="false"
          color="warning"
        />
      </div>

      <SectionHeader title="按钮" />

      <!-- Button 示例 -->
      <Card padding="md">
        <div class="ui-examples__button-group">
          <Button variant="primary" :loading="loading" @click="handleClick">
            主按钮
          </Button>
          <Button variant="secondary">次按钮</Button>
          <Button variant="ghost">幽灵按钮</Button>
          <Button variant="danger">危险按钮</Button>
        </div>
        <div class="ui-examples__button-group">
          <Button variant="primary" size="sm">小号主按钮</Button>
          <Button variant="primary" size="md">中号主按钮</Button>
          <Button variant="primary" size="lg">大号主按钮</Button>
        </div>
        <Button variant="primary" block>块级按钮</Button>
        <Button variant="primary" disabled>禁用按钮</Button>
      </Card>

      <SectionHeader title="标签" />

      <!-- Tag 示例 -->
      <Card padding="md">
        <div class="ui-examples__tag-group">
          <Tag text="成功" variant="success" />
          <Tag text="警告" variant="warning" />
          <Tag text="危险" variant="danger" />
          <Tag text="信息" variant="info" />
          <Tag text="默认" variant="default" />
        </div>
        <div class="ui-examples__tag-group">
          <Tag text="激活" variant="success" dot />
          <Tag text="处理中" variant="warning" dot />
          <Tag text="已关闭" variant="default" dot />
        </div>
        <div class="ui-examples__tag-group">
          <Tag text="小标签" variant="info" size="sm" />
          <Tag text="中标签" variant="info" size="md" />
        </div>
      </Card>

      <SectionHeader title="列表项" />

      <!-- ListItem 示例 -->
      <Card padding="none">
        <ListItem
          icon="/icons/user.svg"
          title="用户设置"
          description="管理您的账户信息"
          clickable
          :divider="true"
        />
        <ListItem
          icon="/icons/bell.svg"
          title="通知设置"
          description="配置消息推送"
          value="已开启"
          clickable
          :divider="true"
        />
        <ListItem
          icon="/icons/shield.svg"
          title="隐私设置"
          description="控制数据分享"
          clickable
          :divider="true"
        />
        <ListItem
          icon="/icons/help.svg"
          title="帮助中心"
          description="常见问题解答"
          clickable
        />
      </Card>

      <SectionHeader title="卡片" />

      <!-- Card 示例 -->
      <Card padding="md" hover>
        <h3>悬停卡片</h3>
        <p>这是一个支持悬停效果的卡片，鼠标悬停或点击时背景会变化。</p>
      </Card>

      <Card padding="lg" clickable>
        <h3>可点击卡片</h3>
        <p>这是一个可点击的卡片，点击会触发相应操作。</p>
      </Card>

      <!-- 占位底部空间 -->
      <div class="ui-examples__spacer"></div>
    </div>

    <!-- TabBar 示例 -->
    <TabBar :tabs="tabs" :active="activeTab" @change="handleTabChange" />
  </div>
</template>

<style scoped>
.ui-examples {
  min-height: 100vh;
  background: var(--bg-primary);
}

.ui-examples__content {
  padding: calc(var(--appbar-height) + var(--space-md)) var(--space-md) var(--space-md);
  max-width: 600px;
  margin: 0 auto;
}

.ui-examples__row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-sm);
  margin-bottom: var(--space-md);
}

.ui-examples__button-group {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  margin-bottom: var(--space-md);
}

.ui-examples__button-group:last-child {
  margin-bottom: 0;
}

.ui-examples__tag-group {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  margin-bottom: var(--space-sm);
}

.ui-examples__spacer {
  height: calc(var(--tabbar-height) + var(--space-md));
}

.icon-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: var(--text-body-color);
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.icon-btn:active {
  background: rgba(255, 255, 255, 0.1);
}
</style>
