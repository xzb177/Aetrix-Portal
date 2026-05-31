/**
 * 创新功能 API
 * 登录自诊断 / 观影画像 / 家庭席位 / 阶梯邀请 / 权益包
 */
import api from './index'
import type {
  FamilyInfo, ViewingProfile, InviteProgress, AddOnPackage,
  LoginDiagnosis, ServerDiagnosis
} from './types'

// ==================== 登录自诊断 ====================
export const diagnosisApi = {
  login: (username: string) =>
    api.get<LoginDiagnosis>('/api/user/innovations/diagnosis/login', { params: { username } }),
  servers: () =>
    api.get<ServerDiagnosis>('/api/user/innovations/diagnosis/servers'),
}

// ==================== 观影画像 ====================
export const viewingApi = {
  getProfile: () =>
    api.get<ViewingProfile>('/api/user/innovations/viewing/profile'),
  getRecommendations: () =>
    api.get('/api/user/innovations/viewing/recommendations'),
}

// ==================== 家庭席位 ====================
export const familyApi = {
  getInfo: () =>
    api.get<FamilyInfo>('/api/user/innovations/family'),
  create: (planType: string = 'standard') =>
    api.post('/api/user/innovations/family/create', null, { params: { plan_type: planType } }),
  addMember: (username: string, nickname?: string) =>
    api.post('/api/user/innovations/family/add-member', null, { params: { username, nickname } }),
  removeMember: (memberId: number) =>
    api.post('/api/user/innovations/family/remove-member', null, { params: { member_id: memberId } }),
}

// ==================== 阶梯邀请 ====================
export const tieredInviteApi = {
  getTiers: () =>
    api.get<InviteProgress>('/api/user/innovations/invite/tiers'),
  checkRewards: () =>
    api.post('/api/user/innovations/invite/check-rewards'),
}

// ==================== 权益包 ====================
export const addOnApi = {
  getAvailable: () =>
    api.get<AddOnPackage[]>('/api/user/innovations/addons'),
  purchase: (packageId: number) =>
    api.post('/api/user/innovations/addons/purchase', null, { params: { package_id: packageId } }),
  getMyAddOns: () =>
    api.get('/api/user/innovations/addons/my'),
}
