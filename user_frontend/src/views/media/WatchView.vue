<script setup lang="ts">
/**
 * 网页播放页
 *
 * - 优先直连 stream（浏览器原生支持 MP4/WebM，Range 分段）
 * - 直连不可用时回退 HLS 转码（hls.js；Safari 原生支持）
 * - 播放进度节流上报（Sessions/Playing/Progress），与 Emby 客户端互通续播
 * - 自动从上次进度续播；播完（>=95%）自动标记已看
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import Hls from 'hls.js'
import {
  embyApi, posterUrl, ticksToSeconds, type EmbyItem, type EmbyMediaSource,
} from '@/api/emby'
import { useToast } from '@/composables/useToast'
import { useUserStore } from '@/stores/user'
import {
  Play, Pause, Volume2, VolumeX, Maximize, ChevronLeft, Film,
  Crown, Sparkles, CalendarCheck, Wallet,
} from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const toast = useToast()
const userStore = useUserStore()

const videoRef = ref<HTMLVideoElement | null>(null)
const containerRef = ref<HTMLDivElement | null>(null)

const item = ref<EmbyItem | null>(null)
const loading = ref(true)
const playError = ref('')
const playMethod = ref<'DirectStream' | 'HLS'>('DirectStream')
// 付费墙拦截：需要订阅才能播放
const paywalled = ref(false)
const paywallMessage = ref('')
// 服务端投递的文本字幕轨（外挂/内封抽取），由 MediaSource 的 DeliveryUrl 提供
const subtitleTrack = ref<{ url: string; label: string } | null>(null)

// 播放器状态
const isPlaying = ref(false)
const isPaused = ref(true)
const muted = ref(false)
const currentTime = ref(0)
const duration = ref(0)
const volume = ref(1)
const showControls = ref(true)

let hls: Hls | null = null
let controlsTimer: ReturnType<typeof setTimeout> | null = null
let progressTimer: ReturnType<typeof setInterval> | null = null
let reportedStart = false

const itemId = computed(() => route.params.id as string)
const poster = computed(() => (item.value ? posterUrl(item.value, 800) : ''))
const progressPct = computed(() =>
  duration.value > 0 ? (currentTime.value / duration.value) * 100 : 0,
)

const fmt = (s: number) => {
  if (!s || s < 0) s = 0
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.floor(s % 60)
  const mm = h > 0 ? String(m).padStart(2, '0') : String(m)
  return `${h > 0 ? h + ':' : ''}${mm}:${String(sec).padStart(2, '0')}`
}

// ==================== 播放源解析 ====================

function destroyHls() {
  if (hls) {
    hls.destroy()
    hls = null
  }
}

async function resolveAndPlay() {
  const video = videoRef.value
  if (!video) return
  playError.value = ''

  try {
    const info = await embyApi.getPlaybackInfo(itemId.value)
    const source: EmbyMediaSource | undefined = info.MediaSources?.[0]

    // 字幕：优先服务端标记的默认轨，否则取第一条可投递的文本字幕
    const subStreams = (source?.MediaStreams || []).filter(
      (s) => s.Type === 'Subtitle' && s.IsTextSubtitleStream && s.DeliveryUrl,
    )
    const chosenSub = subStreams.find((s) => s.IsDefault) || subStreams[0]
    subtitleTrack.value = chosenSub
      ? { url: chosenSub.DeliveryUrl as string, label: chosenSub.DisplayTitle || chosenSub.Language || '字幕' }
      : null

    // 1) 直连优先（服务器地址与页面同源，JWT 已附在 api_key）
    const directUrl = source?.DirectStreamUrl
    if (directUrl && (await tryDirect(directUrl))) {
      playMethod.value = 'DirectStream'
      return
    }

    // 2) HLS 回退
    const hlsUrl = source?.TranscodingUrl
    if (hlsUrl) {
      if (video.canPlayType('application/vnd.apple.mpegurl')) {
        // Safari 原生
        video.src = hlsUrl
        playMethod.value = 'HLS'
        await video.play().catch(() => {})
        return
      }
      if (Hls.isSupported()) {
        destroyHls()
        hls = new Hls({ enableWorker: true, lowLatencyMode: false, backBufferLength: 60 })
        hls.loadSource(hlsUrl)
        hls.attachMedia(video)
        hls.on(Hls.Events.MANIFEST_PARSED, () => video.play().catch(() => {}))
        hls.on(Hls.Events.ERROR, (_e, data) => {
          if (data.fatal) {
            playError.value = '转码流加载失败，请稍后重试或使用外部播放器'
          }
        })
        playMethod.value = 'HLS'
        return
      }
    }

    playError.value = '没有可用的播放方式（直连与转码均不可用）'
  } catch (err: any) {
    // 403 = 付费墙拦截（后端返回可读文案）
    if (err?.response?.status === 403) {
      paywalled.value = true
      paywallMessage.value = err?.response?.data?.detail || '需要有效的会员订阅才能播放'
      return
    }
    playError.value = err?.response?.data?.detail || '获取播放信息失败'
  }
}

/** 探测直连是否可用（HEAD 不被 Range 服务支持时用 GET Range 小段） */
function tryDirect(url: string): Promise<boolean> {
  return new Promise((resolve) => {
    const probe = new XMLHttpRequest()
    probe.open('GET', url, true)
    probe.setRequestHeader('Range', 'bytes=0-1')
    probe.timeout = 8000
    probe.onload = () => {
      if (probe.status >= 200 && probe.status < 300) {
        const video = videoRef.value
        if (video) video.src = url
        resolve(true)
      } else {
        resolve(false)
      }
    }
    probe.onerror = () => resolve(false)
    probe.ontimeout = () => resolve(false)
    probe.send()
  })
}

// ==================== 进度上报 ====================

function reportProgress() {
  const video = videoRef.value
  if (!video) return
  embyApi.reportProgress(itemId.value, video.currentTime, video.paused, playMethod.value).catch(() => {})
}

function startProgressLoop() {
  if (progressTimer) return
  // 每 10 秒上报一次进度
  progressTimer = setInterval(reportProgress, 10_000)
}

function stopProgressLoop() {
  if (progressTimer) {
    clearInterval(progressTimer)
    progressTimer = null
  }
}

// ==================== 播放器事件 ====================

function onLoadedMetadata() {
  const video = videoRef.value
  if (!video) return
  duration.value = video.duration || 0

  // 续播：仅当接近片头（避免覆盖已有会话）且服务端有进度
  const saved = item.value?.UserData?.PlaybackPositionTicks || 0
  const savedSec = ticksToSeconds(saved)
  if (savedSec > 10 && video.currentTime < 5) {
    video.currentTime = savedSec
    toast.success(`已从 ${fmt(savedSec)} 继续播放`)
  }
}

function onPlay() {
  isPlaying.value = true
  isPaused.value = false
  startProgressLoop()
  const video = videoRef.value
  if (video && !reportedStart) {
    reportedStart = true
    embyApi.reportPlaying(itemId.value, video.currentTime, playMethod.value).catch(() => {})
  }
}

function onPause() {
  isPlaying.value = false
  isPaused.value = true
  reportProgress()
}

function onEnded() {
  stopProgressLoop()
  reportProgress()
  // 播完自动标记已看
  embyApi.setPlayed(itemId.value, true).catch(() => {})
  toast.success('播放完成，已标记为看过')
}

function onTimeUpdate() {
  const video = videoRef.value
  if (video) currentTime.value = video.currentTime
}

function onVolumeChange() {
  const video = videoRef.value
  if (video) {
    volume.value = video.volume
    muted.value = video.muted
  }
}

function togglePlay() {
  const video = videoRef.value
  if (!video) return
  if (video.paused) video.play().catch(() => {})
  else video.pause()
}

function toggleMute() {
  const video = videoRef.value
  if (!video) return
  video.muted = !video.muted
}

function seekTo(e: Event) {
  const video = videoRef.value
  if (!video || !duration.value) return
  const target = e.target as HTMLElement
  const rect = target.getBoundingClientRect()
  const pct = (e as MouseEvent).clientX - rect.left
  video.currentTime = (pct / rect.width) * duration.value
}

function setVolume(e: Event) {
  const video = videoRef.value
  if (!video) return
  video.volume = parseFloat((e.target as HTMLInputElement).value)
}

function fullscreen() {
  const el = containerRef.value
  if (!el) return
  if (document.fullscreenElement) document.exitFullscreen()
  else el.requestFullscreen().catch(() => {})
}

function showControlsTemporarily() {
  showControls.value = true
  if (controlsTimer) clearTimeout(controlsTimer)
  controlsTimer = setTimeout(() => {
    if (isPlaying.value) showControls.value = false
  }, 3000)
}

// ==================== 生命周期 ====================

onMounted(async () => {
  try {
    item.value = await embyApi.getItem(itemId.value)
    document.title = `播放 ${item.value.Name} - Aetrix`
  } catch {
    toast.error('加载影片信息失败')
    loading.value = false
    return
  }
  loading.value = false
  await resolveAndPlay()
})

onBeforeUnmount(() => {
  const video = videoRef.value
  if (video && video.currentTime > 0) {
    embyApi.reportStopped(itemId.value, video.currentTime, playMethod.value).catch(() => {})
  }
  stopProgressLoop()
  destroyHls()
  if (controlsTimer) clearTimeout(controlsTimer)
  document.title = 'Aetrix'
})
</script>

<template>
  <div class="watch-view" :class="{ 'hide-cursor': !showControls && isPlaying }">
    <div ref="containerRef" class="player-container">
      <!-- 海报占位 -->
      <div v-if="loading" class="poster-layer" :style="poster ? { backgroundImage: `url(${poster})` } : {}">
        <div class="poster-shade">
          <Film :size="28" class="pulse" />
          <p>准备播放…</p>
        </div>
      </div>

      <video
        ref="videoRef"
        class="video"
        playsinline
        preload="metadata"
        @loadedmetadata="onLoadedMetadata"
        @play="onPlay"
        @pause="onPause"
        @ended="onEnded"
        @timeupdate="onTimeUpdate"
        @volumechange="onVolumeChange"
        @click="togglePlay"
      >
        <track
          v-if="subtitleTrack"
          :key="subtitleTrack.url"
          kind="subtitles"
          :src="subtitleTrack.url"
          :label="subtitleTrack.label"
          default
        />
      </video>

      <!-- 付费墙：未订阅时引导开通，而不是丢一个播放错误 -->
      <div v-if="paywalled" class="paywall-layer">
        <div class="paywall-card">
          <span class="paywall-icon">
            <Crown :size="24" />
          </span>
          <h2 class="paywall-title">会员专享内容</h2>
          <p class="paywall-text">{{ paywallMessage }}</p>
          <div class="paywall-perks">
            <span><Sparkles :size="13" /> 全库影视任意观看</span>
            <span><CalendarCheck :size="13" /> 多端同步进度与收藏</span>
            <span><Wallet :size="13" /> 支持积分与在线支付</span>
          </div>
          <div class="paywall-actions">
            <RouterLink to="/wallet?tab=plans" class="btn primary">
              <Crown :size="16" />
              开通会员
            </RouterLink>
            <RouterLink :to="`/media/${itemId}`" class="btn ghost">返回详情</RouterLink>
          </div>
        </div>
      </div>

      <!-- 错误 -->
      <div v-if="playError && !paywalled" class="error-layer">
        <p>{{ playError }}</p>
        <div class="error-actions">
          <button class="btn ghost" @click="resolveAndPlay">重试</button>
          <RouterLink :to="`/media/${itemId}`" class="btn ghost">返回详情</RouterLink>
        </div>
      </div>

      <!-- 返回 -->
      <RouterLink :to="`/media/${itemId}`" class="back-btn" :class="{ visible: showControls }">
        <ChevronLeft :size="18" />
      </RouterLink>

      <!-- 控制条 -->
      <div class="controls" :class="{ visible: showControls || !isPlaying }">
        <!-- 进度条 -->
        <div class="seek" @click="seekTo">
          <div class="seek-buffer"></div>
          <div class="seek-fill" :style="{ width: progressPct + '%' }"></div>
          <div class="seek-thumb" :style="{ left: progressPct + '%' }"></div>
        </div>

        <div class="controls-row">
          <button class="ctrl-btn" @click="togglePlay">
            <Pause v-if="isPlaying" :size="20" />
            <Play v-else :size="20" />
          </button>

          <div class="volume-wrap">
            <button class="ctrl-btn" @click="toggleMute">
              <VolumeX v-if="muted || volume === 0" :size="18" />
              <Volume2 v-else :size="18" />
            </button>
            <input
              class="volume-slider"
              type="range"
              min="0"
              max="1"
              step="0.05"
              :value="muted ? 0 : volume"
              @input="setVolume"
            />
          </div>

          <span class="time">{{ fmt(currentTime) }} / {{ fmt(duration) }}</span>

          <span class="method-badge">{{ playMethod === 'DirectStream' ? '直连' : '转码' }}</span>

          <button class="ctrl-btn fullscreen" @click="fullscreen">
            <Maximize :size="18" />
          </button>
        </div>
      </div>
    </div>

    <!-- 影片信息 -->
    <div v-if="item" class="container below">
      <h1 class="below-title">{{ item.Name }}</h1>
      <p class="below-meta">
        <span v-if="item.ProductionYear">{{ item.ProductionYear }}</span>
        <span v-if="item.SeriesName">{{ item.SeriesName }}</span>
      </p>
      <p v-if="item.Overview" class="below-overview">{{ item.Overview }}</p>
    </div>
  </div>
</template>

<style scoped>
.watch-view {
  min-height: 100vh;
  background: #000;
  color: #e5e7eb;
}

.watch-view.hide-cursor {
  cursor: none;
}

.player-container {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  max-height: calc(100vh - 0px);
  background: #000;
}

.video {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.poster-layer {
  position: absolute;
  inset: 0;
  background-size: cover;
  background-position: center;
  z-index: 5;
}

.poster-shade {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  color: rgba(255, 255, 255, 0.6);
  font-size: 0.875rem;
}

.pulse {
  animation: pulse 1.4s ease-in-out infinite;
}

@keyframes pulse {
  50% { opacity: 0.35; }
}

.error-layer {
  position: absolute;
  inset: 0;
  z-index: 6;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  background: rgba(0, 0, 0, 0.8);
  padding: 1.5rem;
  text-align: center;
}

.error-layer p {
  margin: 0;
  color: #f87171;
  font-size: 0.9375rem;
}

.error-actions {
  display: flex;
  gap: 0.625rem;
}

.btn {
  height: 38px;
  padding: 0 1rem;
  display: inline-flex;
  align-items: center;
  border-radius: 10px;
  font-size: 0.8125rem;
  font-weight: 500;
  text-decoration: none;
  border: none;
  cursor: pointer;
}

.btn.ghost {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.btn.ghost:hover {
  background: rgba(255, 255, 255, 0.14);
}

.btn.primary {
  gap: 0.4375rem;
  background: var(--au-gradient);
  color: #05141c;
  font-weight: 700;
  box-shadow: 0 4px 16px var(--au-primary-glow);
}

.btn.primary:hover {
  box-shadow: 0 6px 22px var(--au-primary-glow);
}

/* ==================== 付费墙 ==================== */

.paywall-layer {
  position: absolute;
  inset: 0;
  z-index: 7;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  background:
    radial-gradient(700px 380px at 50% 0%, rgba(167, 139, 250, 0.12), transparent 65%),
    rgba(4, 7, 12, 0.9);
  backdrop-filter: blur(8px);
}

.paywall-card {
  width: 100%;
  max-width: 420px;
  padding: 1.75rem 1.5rem;
  text-align: center;
  background: rgba(10, 16, 26, 0.9);
  border: 1px solid var(--au-primary-border);
  border-radius: var(--au-r-xl);
  box-shadow: var(--au-shadow-2);
}

.paywall-icon {
  width: 52px;
  height: 52px;
  margin: 0 auto 0.875rem;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--au-primary-soft);
  border: 1px solid var(--au-primary-border);
  border-radius: 50%;
  color: var(--au-primary);
}

.paywall-title {
  margin: 0 0 0.5rem;
  font-size: 1.125rem;
  font-weight: 700;
  color: var(--au-text);
}

.paywall-text {
  margin: 0 0 1rem;
  font-size: 0.8125rem;
  line-height: 1.6;
  color: var(--au-text-2);
}

.paywall-perks {
  display: grid;
  gap: 0.4375rem;
  margin-bottom: 1.25rem;
  text-align: left;
}

.paywall-perks span {
  display: flex;
  align-items: center;
  gap: 0.4375rem;
  font-size: 0.8125rem;
  color: var(--au-text-2);
}

.paywall-perks svg {
  color: var(--au-primary);
  flex-shrink: 0;
}

.paywall-actions {
  display: flex;
  gap: 0.625rem;
  justify-content: center;
  flex-wrap: wrap;
}

.back-btn {
  position: absolute;
  top: 1rem;
  left: 1rem;
  z-index: 10;
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 10px;
  color: #fff;
  opacity: 0;
  transition: opacity 0.2s ease;
  backdrop-filter: blur(6px);
}

.back-btn.visible {
  opacity: 1;
}

/* 控制条 */
.controls {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 10;
  padding: 1.75rem 1rem 0.75rem;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.85), transparent);
  opacity: 0;
  transform: translateY(8px);
  transition: all 0.25s ease;
  pointer-events: none;
}

.controls.visible {
  opacity: 1;
  transform: none;
  pointer-events: auto;
}

.seek {
  position: relative;
  height: 4px;
  background: rgba(255, 255, 255, 0.18);
  border-radius: 2px;
  cursor: pointer;
  margin-bottom: 0.625rem;
}

.seek:hover {
  height: 6px;
}

.seek-buffer {
  position: absolute;
  inset: 0;
  border-radius: 2px;
}

.seek-fill {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  background: #22d3ee;
  border-radius: 2px;
}

.seek-thumb {
  position: absolute;
  top: 50%;
  transform: translate(-50%, -50%);
  width: 12px;
  height: 12px;
  background: #22d3ee;
  border-radius: 50%;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.5);
}

.controls-row {
  display: flex;
  align-items: center;
  gap: 0.875rem;
}

.ctrl-btn {
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.85);
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.15s ease;
}

.ctrl-btn:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.1);
}

.volume-wrap {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.volume-slider {
  width: 80px;
  accent-color: var(--au-primary);
  cursor: pointer;
}

.time {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.7);
  font-variant-numeric: tabular-nums;
}

.method-badge {
  margin-left: auto;
  padding: 0.1875rem 0.5rem;
  background: var(--au-primary-soft);
  border-radius: var(--au-r-sm);
  color: var(--au-primary);
  font-size: 0.6875rem;
  font-weight: 600;
}

.fullscreen {
  margin-left: 0.5rem;
}

/* 播放器下方信息 */
/* 播放器下方的信息区：宽度与左右留白来自全局 .container（页面骨架），
   这里只管垂直节奏与文字层级 */
.below {
  padding-top: 1.25rem;
}

.below-title {
  margin: 0 0 0.375rem;
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--au-text);
}

.below-meta {
  margin: 0 0 0.75rem;
  display: flex;
  gap: 0.875rem;
  font-size: 0.8125rem;
  color: var(--au-text-3);
}

.below-overview {
  margin: 0;
  font-size: 0.875rem;
  line-height: 1.7;
  color: var(--au-text-2);
  max-width: 720px;
  padding-bottom: 2.5rem;
}
</style>
