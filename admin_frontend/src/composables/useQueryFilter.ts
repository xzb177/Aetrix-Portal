import { watch, type Ref } from 'vue'
import { useRoute } from 'vue-router'

/**
 * 深链筛选：把 URL 上的查询参数写进页面自己的筛选器
 *
 * 仪表盘的数字要能「一点直达明细」，就得能带筛选过去——例如
 * 「待处理工单 3」跳到 `/tickets?status=open`、「待支付订单」跳到
 * `/orders?status=pending`。这些页面本来就各自有筛选器（`statusFilter` 等），
 * 所以这里只做一件事：**query 变，筛选器跟着变**。
 *
 * 为什么用 watch 而不是 onMounted 读一次：
 * 命令面板、KPI 卡、待办条都可能在**已经在这个页面里**的时候带着新的 query 跳过来
 * （例如在工单页点仪表盘的「待处理工单」）。只在 onMounted 读一次的话，
 * 页面不会重新挂载，筛选器还是旧的，看着就像「点了没反应」。
 *
 * 页面自己改筛选器时不回写 URL：筛选器是页面内部状态，深链只是入口参数。
 * 参数非法时不在这里校验——各页的筛选下拉本来就会把不匹配的值显示成空结果，
 * 由页面自己决定接不接受（例如 MediaSeek 认不认 `status=expired`）。
 *
 * ``onChange``：**后续**变化时回调（用来重新拉数据）。首次（immediate）不回调——
 * 页面自己的 ``onMounted`` 本来就会带着已经写好的筛选器加载一次，不用多打一遍请求。
 * 漏掉这个回调的后果很隐蔽：在工单页上再点一次仪表盘的「待处理工单」，路由 query 变了、
 * 筛选器也变了，但列表还是旧的——看着就像「点了没反应」。
 */
export function useQueryFilter(target: Ref<string>, key: string, onChange?: () => void): void {
  const route = useRoute()
  let first = true
  watch(
    () => route.query[key],
    (value) => {
      const next = Array.isArray(value) ? (value[0] ?? '') : (value ?? '')
      const changed = target.value !== next
      target.value = next
      const isFirst = first
      first = false
      if (isFirst || !changed) return
      onChange?.()
    },
    { immediate: true },
  )
}
