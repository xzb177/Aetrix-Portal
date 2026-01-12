import { http } from '@/utils/request'

// 获取转码队列
export const getTranscodeQueue = () => {
  return http.get('/stats/transcode')
}

// 获取播放热力图
export const getPlaybackHeatmap = (days: number = 30) => {
  return http.get('/stats/heatmap', { params: { days } })
}

// 获取热门内容
export const getPopularContent = (params?: { limit?: number; content_type?: string }) => {
  return http.get('/stats/popular-content', { params })
}

// 获取用户行为分析
export const getUserBehavior = (days: number = 7) => {
  return http.get('/stats/user-behavior', { params: { days } })
}
