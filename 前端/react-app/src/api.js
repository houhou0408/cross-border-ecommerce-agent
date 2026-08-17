// API 调用封装：所有后端接口集中管理
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

async function postJSON(path, body, timeout = 120000) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeout)
  try {
    const r = await fetch(BASE + path, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
      signal: ctrl.signal
    })
    return await r.json()
  } finally {
    clearTimeout(timer)
  }
}

async function getJSON(path, timeout = 15000) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeout)
  try {
    const r = await fetch(BASE + path, { headers: authHeaders(), signal: ctrl.signal })
    return await r.json()
  } finally {
    clearTimeout(timer)
  }
}

async function deleteJSON(path, timeout = 15000) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeout)
  try {
    const r = await fetch(BASE + path, { method: 'DELETE', headers: authHeaders(), signal: ctrl.signal })
    return await r.json()
  } finally {
    clearTimeout(timer)
  }
}

// 带 Authorization 的 FormData 上传
async function postForm(path, fd, timeout = 120000) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeout)
  try {
    const r = await fetch(BASE + path, { method: 'POST', headers: authHeaders(), body: fd, signal: ctrl.signal })
    return await r.json()
  } finally {
    clearTimeout(timer)
  }
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
    return fetch('/ask', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
      signal
    }).then((r) => r.json())
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
  deleteImageTask: (taskId) => deleteJSON('/image/tasks/' + encodeURIComponent(taskId))
}
