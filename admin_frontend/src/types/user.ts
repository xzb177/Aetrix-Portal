// 用户相关类型
export interface User {
  tg_id: number
  username: string | null
  emby_account: string | null
  is_vip: boolean
  points: number
  bank_points: number
  attack: number
  total_watch_minutes: number
  total_checkin_days: number
  registered_date: string | null
  last_checkin_date: string | null
  watch_streak: number
}

export interface UserDetail extends User {
  // 魔力系统
  accumulated_interest: number
  total_earned: number
  total_spent: number

  // 战力系统
  weapon: string | null
  weapon_durability: number
  breakthrough_level: number

  // 签到系统
  consecutive_checkin: number

  // Emby 观影
  daily_watch_minutes: number
  total_watch_checkin_days: number
  max_watch_streak: number
  watch_checkin_today: boolean
  daily_mp_rewarded: number

  // 观影宝箱
  watch_boxes_opened: number
  early_bird_wins: number

  // 周挑战
  weekly_challenge_target: number
  weekly_challenge_progress: number
  weekly_challenge_reward_claimed: boolean
  weekly_challenge_completed: number

  // 成就
  achievements: string
  watch_achievements: string

  // 外观
  equipped_frame: string | null
  equipped_title: string | null
  owned_frames: string
  owned_titles: string

  // 公会
  guild_id: number | null
}

export interface UserStats {
  total_users: number
  vip_users: number
  new_users_today: number
  active_users_week: number
  total_watch_minutes: number
  total_checkin_days: number
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}
