// API 调用封装：所有后端接口集中管理
// 统一 request()：注入 Authorization、超时控制、401 全局拦截
const BASE = ''

// token 管理：localStorage 存储
export const tokenStore = {
  get: () => localStorage.getItem('auth_token') || '',
  set: (t) => localStorage.setItem('auth_token', t),
  clear: () => localStorage.removeItem('auth_token'),
}

// 构建 Authorization 头
function authHeaders(extra = {}) {
  const token = tokenStore.get()
  const h = { ...extra }
  if (token) h['Authorization'] = 'Bearer ' + token
  return h
}

// 统一请求入口：
// - 自动注入 Authorization 头
// - timeout 毫秒超时（外部传入 signal 时以 signal 为准）
// - 401 → 清除本地 token 并广播 auth:expired 事件，App 监听后回到登录页
async function request(path, { method = 'GET', body, isForm = false, timeout = 15000, signal } = {}) {
  let ctrl = null
  let timer = null
  if (signal == null && timeout > 0) {
    ctrl = new AbortController()
    timer = setTimeout(() => ctrl.abort(), timeout)
  }
  try {
    const headers = isForm
      ? authHeaders()
      : authHeaders(body !== undefined ? { 'Content-Type': 'application/json' } : {})
    const r = await fetch(BASE + path, {
      method,
      headers,
      body: isForm ? body : (body !== undefined ? JSON.stringify(body) : undefined),
      signal: signal != null ? signal : (ctrl ? ctrl.signal : undefined)
    })
    if (r.status === 401) {
      // 登录态失效（token 过期/被顶掉/未登录）：清 token + 广播，绝不静默吞掉
      tokenStore.clear()
      window.dispatchEvent(new CustomEvent('auth:expired', { detail: { path } }))
      return { error: '登录已过期，请重新登录', auth_expired: true }
    }
    return await r.json()
  } finally {
    if (timer) clearTimeout(timer)
  }
}

// 薄封装：保持原有函数签名，页面零改动
function postJSON(path, body, timeout = 120000) {
  return request(path, { method: 'POST', body, timeout })
}

function getJSON(path, timeout = 15000) {
  return request(path, { method: 'GET', timeout })
}

function deleteJSON(path, timeout = 15000) {
  return request(path, { method: 'DELETE', timeout })
}

// 带 Authorization 的 FormData 上传
function postForm(path, fd, timeout = 120000) {
  return request(path, { method: 'POST', body: fd, isForm: true, timeout })
}

export const api = {
  // 认证
  register: (username, password) => postJSON('/auth/register', { username, password }),
  login: (username, password) => postJSON('/auth/login', { username, password }),
  logout: () => postJSON('/auth/logout', {}),
  getMe: () => getJSON('/auth/me'),

  health: () => getJSON('/health'),
  ask: (query, sessionId, signal, imagePath = null) => {
    const body = { query, session_id: sessionId || null }
    if (imagePath) body.image_path = imagePath
    // 外部 signal 用于用户手动停止生成，不设超时
    return request('/ask', { method: 'POST', body, timeout: 0, signal })
  },
  // 流式问答（SSE）：onStage(msg) 接收阶段事件（工具调用进度）；
  // 返回最终 payload（与 /ask 相同结构）。服务端返回非 SSE（如会话校验失败）
  // 时直接解析 JSON 返回，调用方无须区分。
  askStream: async (query, sessionId, signal, imagePath = null, onStage = null) => {
    const body = { query, session_id: sessionId || null }
    if (imagePath) body.image_path = imagePath
    const r = await fetch(BASE + '/ask/stream', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
      signal,
    })
    if (r.status === 401) {
      tokenStore.clear()
      window.dispatchEvent(new CustomEvent('auth:expired', { detail: { path: '/ask/stream' } }))
      return { error: '登录已过期，请重新登录', auth_expired: true }
    }
    const ct = r.headers.get('content-type') || ''
    if (!r.ok || !ct.includes('text/event-stream')) {
      return await r.json()
    }
    const reader = r.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let finalData = null
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const parts = buf.split('\n\n')
      buf = parts.pop() || ''
      for (const part of parts) {
        const line = part.split('\n').find((l) => l.startsWith('data: '))
        if (!line) continue
        let item
        try {
          item = JSON.parse(line.slice(6))
        } catch {
          continue
        }
        if (item.type === 'stage') {
          if (onStage) onStage(item.msg)
        } else if (item.type === 'result') {
          finalData = item
        } else if (item.type === 'error') {
          finalData = { error: item.error || '服务异常' }
        }
      }
    }
    return finalData || { error: '连接中断' }
  },
  // 对话页上传商品图片，返回 image_path
  uploadChatImage: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return postForm('/chat/upload-image', fd, 60000)
  },
  listing: (body) => postJSON('/listing', body, 90000),
  tariff: (body) => postJSON('/tariff', body, 30000),
  currency: (body) => postJSON('/currency', body, 30000),
  stats: () => getJSON('/stats'),
  collectionStatus: () => getJSON('/collection/status'),
  // 会话管理（记忆模块）
  listSessions: () => getJSON('/sessions'),
  createSession: () => postJSON('/sessions', {}),
  getSession: (id) => getJSON('/sessions/' + id),
  deleteSession: (id) => deleteJSON('/sessions/' + id),
  // 知识库管理
  listKbDocs: () => getJSON('/kb/documents'),
  uploadKbDoc: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return postForm('/kb/upload', fd)
  },
  deleteKbDoc: (source) => deleteJSON('/kb/documents/' + encodeURIComponent(source)),
  // Agent 效果评估
  getTestset: () => getJSON('/eval/testset'),
  runEval: () => postJSON('/eval/run', {}, 300000),
  // 视频生成（图生视频）
  generateVideo: (file, prompt) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('prompt', prompt || '')
    return postForm('/video/generate', fd, 360000)
  },
  // 文生视频（纯文字描述生成视频）
  generateTextVideo: (prompt) => postJSON('/video/text-to-video', { prompt }, 360000),
  listVideoTasks: () => getJSON('/video/tasks'),
  getVideoTask: (taskId) => getJSON('/video/tasks/' + encodeURIComponent(taskId)),
  deleteVideoTask: (taskId) => deleteJSON('/video/tasks/' + encodeURIComponent(taskId)),
  // 卖点图生成（上传商品图+描述，生成4种电商营销图）
  generateSellingImages: (file, product, features) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('product', product || '')
    fd.append('features', features || '')
    return postForm('/image/generate-batch', fd, 360000)
  },
  listImageTasks: () => getJSON('/image/tasks'),
  deleteImageTask: (taskId) => deleteJSON('/image/tasks/' + encodeURIComponent(taskId)),
  // 智能客服
  supportAsk: (query, mode, sessionId) => postJSON('/support/ask', { query, mode, session_id: sessionId || null }, 120000),
  supportFaqTopics: () => getJSON('/support/faq/topics'),
  supportReview: (body) => postJSON('/support/review', body, 30000),
  supportTransfer: (sessionId) => postJSON('/support/transfer', { session_id: sessionId || null }, 30000)
}
