<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { CreditCard, Save, TestTube, AlertCircle, CheckCircle2, ExternalLink } from 'lucide-vue-next'
import request from '@/utils/request'

interface PaymentConfig {
  is_configured: boolean
  gateway_url: string
  partner_id: string
  key: string
  notify_url: string
  return_url: string
}

const config = ref<PaymentConfig>({
  is_configured: false,
  gateway_url: '',
  partner_id: '',
  key: '',
  notify_url: '',
  return_url: ''
})

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const testResult = ref<{ success: boolean; message: string } | null>(null)

const form = ref({
  gateway_url: '',
  partner_id: '',
  key: '',
  notify_url: '',
  return_url: ''
})

const loadConfig = async () => {
  loading.value = true
  try {
    const res = await request.get<any>('/payment/config') as any
    config.value = res as PaymentConfig
    form.value = {
      gateway_url: res.gateway_url || '',
      partner_id: res.partner_id || '',
      key: '',  // 不回填密钥
      notify_url: res.notify_url || '',
      return_url: res.return_url || ''
    }
  } finally {
    loading.value = false
  }
}

const saveConfig = async () => {
  if (!form.value.gateway_url || !form.value.partner_id || !form.value.key) {
    testResult.value = { success: false, message: '请填写必填项：支付网关地址、商户ID、商户密钥' }
    return
  }

  saving.value = true
  try {
    await request.post('/payment/config', form.value)
    testResult.value = { success: true, message: '配置保存成功！' }
    await loadConfig()
  } catch (err: any) {
    testResult.value = { success: false, message: err.message || '保存失败' }
  } finally {
    saving.value = false
  }
}

const testConnection = async () => {
  testing.value = true
  testResult.value = null
  try {
    const res = await request.post<{ success: boolean; message: string }>('/payment/test') as any
    testResult.value = res
  } catch (err: any) {
    testResult.value = { success: false, message: err.message || '测试失败' }
  } finally {
    testing.value = false
  }
}

onMounted(() => {
  loadConfig()
})
</script>

<template>
  <div class="payment-config-page">
    <!-- 测试按钮 -->
    <div class="page-actions">
      <button
        class="test-btn"
        :class="{ testing }"
        :disabled="!config.is_configured || testing"
        @click="testConnection"
      >
        <TestTube :size="18" />
        {{ testing ? '测试中...' : '测试连接' }}
      </button>
    </div>

    <!-- 配置状态 -->
    <div v-if="config.is_configured" class="status-banner status-success">
      <CheckCircle2 :size="20" />
      <span>支付已配置，可以正常使用</span>
    </div>
    <div v-else class="status-banner status-warning">
      <AlertCircle :size="20" />
      <span>支付未配置，请先完成易支付配置</span>
    </div>

    <!-- 测试结果 -->
    <div v-if="testResult" class="test-result" :class="{ success: testResult.success, error: !testResult.success }">
      <CheckCircle2 v-if="testResult.success" :size="18" />
      <AlertCircle v-else :size="18" />
      <span>{{ testResult.message }}</span>
    </div>

    <!-- 配置表单 -->
    <div class="config-section">
      <h2 class="section-title">易支付配置</h2>

      <div class="info-box">
        <p><strong>易支付</strong> 是一个统一的支付接口平台，支持支付宝、微信支付、QQ支付等多种支付方式。</p>
        <p>配置完成后，用户在订阅套餐时可以选择对应的支付方式完成支付。</p>
      </div>

      <div class="form-grid">
        <!-- 支付网关地址 -->
        <div class="form-group">
          <label class="form-label required">
            <span>支付网关地址</span>
            <a href="https://www.yipay.cn/" target="_blank" class="help-link">
              <ExternalLink :size="14" />
              获取易支付
            </a>
          </label>
          <input
            v-model="form.gateway_url"
            type="url"
            class="form-input"
            placeholder="https://pay.example.com/submit.php"
          />
          <p class="form-hint">易支付网关的完整地址，包含 https://</p>
        </div>

        <!-- 商户ID -->
        <div class="form-group">
          <label class="form-label required">商户ID (Partner ID)</label>
          <input
            v-model="form.partner_id"
            type="text"
            class="form-input"
            placeholder="1000"
          />
          <p class="form-hint">易支付平台分配的商户ID</p>
        </div>

        <!-- 商户密钥 -->
        <div class="form-group">
          <label class="form-label required">商户密钥 (Key)</label>
          <input
            v-model="form.key"
            type="password"
            class="form-input"
            placeholder="请输入商户密钥"
          />
          <p class="form-hint">用于签名验证，请妥善保管</p>
        </div>

        <!-- 异步回调地址 -->
        <div class="form-group">
          <label class="form-label">异步回调地址</label>
          <input
            v-model="form.notify_url"
            type="url"
            class="form-input"
            placeholder="http://154.40.33.2:8001/payment/notify"
          />
          <p class="form-hint">支付成功后的异步通知地址</p>
        </div>

        <!-- 同步跳转地址 -->
        <div class="form-group">
          <label class="form-label">同步跳转地址</label>
          <input
            v-model="form.return_url"
            type="url"
            class="form-input"
            placeholder="http://154.40.33.2/payment/return"
          />
          <p class="form-hint">支付成功后的页面跳转地址</p>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="form-actions">
        <button
          class="save-btn"
          :class="{ loading: saving }"
          :disabled="saving"
          @click="saveConfig"
        >
          <Save :size="18" />
          {{ saving ? '保存中...' : '保存配置' }}
        </button>
      </div>
    </div>

    <!-- 支付流程说明 -->
    <div class="info-section">
      <h2 class="section-title">支付流程说明</h2>
      <div class="flow-steps">
        <div class="flow-step">
          <div class="step-number">1</div>
          <div class="step-content">
            <h4>用户选择套餐</h4>
            <p>用户在订阅页面选择VIP套餐，点击购买</p>
          </div>
        </div>
        <div class="flow-arrow">→</div>
        <div class="flow-step">
          <div class="step-number">2</div>
          <div class="step-content">
            <h4>创建支付订单</h4>
            <p>系统创建订单，跳转到易支付网关</p>
          </div>
        </div>
        <div class="flow-arrow">→</div>
        <div class="flow-step">
          <div class="step-number">3</div>
          <div class="step-content">
            <h4>用户完成支付</h4>
            <p>用户选择支付宝/微信等方式完成支付</p>
          </div>
        </div>
        <div class="flow-arrow">→</div>
        <div class="flow-step">
          <div class="step-number">4</div>
          <div class="step-content">
            <h4>异步回调激活</h4>
            <p>易支付通知系统，自动激活用户VIP</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.payment-config-page {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.page-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 1rem;
}

.test-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 1.25rem;
  background: #4CAF50;
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 0.875rem;
  cursor: pointer;
  white-space: nowrap;
}

.test-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.test-btn.testing svg { animation: spin 1s linear infinite; }

@keyframes spin { to { transform: rotate(360deg); } }

/* 状态横幅 */
.status-banner {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-radius: 12px;
  font-size: 0.9rem;
}

.status-success {
  background: rgba(76, 175, 80, 0.1);
  color: #4CAF50;
  border: 1px solid rgba(76, 175, 80, 0.2);
}

.status-warning {
  background: rgba(255, 152, 0, 0.1);
  color: #FF9800;
  border: 1px solid rgba(255, 152, 0, 0.2);
}

/* 测试结果 */
.test-result {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-radius: 12px;
  font-size: 0.9rem;
}

.test-result.success {
  background: rgba(76, 175, 80, 0.1);
  color: #4CAF50;
}

.test-result.error {
  background: rgba(244, 67, 54, 0.1);
  color: #F44336;
}

/* 配置区域 */
.config-section {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  border: 1px solid #e8edf3;
}

.section-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: #1a1a2e;
  margin: 0 0 1rem 0;
}

.info-box {
  background: linear-gradient(135deg, rgba(103, 58, 183, 0.05), rgba(76, 175, 80, 0.05));
  border: 1px solid rgba(103, 58, 183, 0.1);
  border-radius: 10px;
  padding: 1rem 1.25rem;
  margin-bottom: 1.5rem;
}

.info-box p {
  margin: 0.25rem 0;
  font-size: 0.875rem;
  color: #475569;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1.5rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-group.full-width {
  grid-column: 1 / -1;
}

.form-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.875rem;
  font-weight: 500;
  color: #475569;
}

.form-label.required::after {
  content: '*';
  color: #F44336;
  margin-left: 4px;
}

.help-link {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #673AB7;
  font-size: 0.75rem;
  text-decoration: none;
}

.help-link:hover {
  text-decoration: underline;
}

.form-input {
  padding: 0.625rem 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.875rem;
  color: #1a1a2e;
  transition: all 0.2s;
}

.form-input:focus {
  outline: none;
  border-color: #673AB7;
  box-shadow: 0 0 0 3px rgba(103, 58, 183, 0.1);
}

.form-hint {
  margin: 0;
  font-size: 0.75rem;
  color: #94a3b8;
}

.form-actions {
  margin-top: 1.5rem;
  padding-top: 1.5rem;
  border-top: 1px solid #f1f5f9;
}

.save-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 2rem;
  background: #673AB7;
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
}

.save-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.save-btn:hover:not(:disabled) {
  background: #552b9f;
}

/* 信息区域 */
.info-section {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  border: 1px solid #e8edf3;
}

.flow-steps {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.flow-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  flex: 1;
}

.step-number {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: linear-gradient(135deg, #673AB7, #4CAF50);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  margin-bottom: 0.75rem;
}

.step-content h4 {
  font-size: 0.9rem;
  font-weight: 500;
  color: #1a1a2e;
  margin: 0 0 0.25rem 0;
}

.step-content p {
  font-size: 0.75rem;
  color: #64748b;
  margin: 0;
}

.flow-arrow {
  font-size: 1.5rem;
  color: #cbd5e1;
}

/* 移动端适配 */
@media (max-width: 768px) {

  .test-btn {
    width: 100%;
    justify-content: center;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .flow-steps {
    flex-direction: column;
  }

  .flow-arrow {
    transform: rotate(90deg);
  }
}
</style>
