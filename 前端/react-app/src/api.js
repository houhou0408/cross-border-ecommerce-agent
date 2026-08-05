// API 调用封装：所有后端接口集中管理
const BASE = ''

async function postJSON(path, body, timeout = 120000) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeout)
  try {
    const r = await fetch(BASE + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
    const r = await fetch(BASE + path, { signal: ctrl.signal })
    return await r.json()
  } finally {
    clearTimeout(timer)
  }
}

async function deleteJSON(path, timeout = 15000) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeout)
  try {
    const r = await fetch(BASE + path, { method: 'DELETE', signal: ctrl.signal })
    return await r.json()
  } finally {
    clearTimeout(timer)
  }
}

export const api = {
  health: () => getJSON('/health'),
  ask: (query, sessionId, signal) => {
    return fetch('/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, session_id: sessionId || null }),
      signal
    }).then((r) => r.json())
  },
  listing: (body) => postJSON('/listing', body, 90000),
  tariff: (body) => postJSON('/tariff', body, 30000),
  currency: (body) => postJSON('/currency', body, 30000),
  stats: () => getJSON('/stats'),
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
    return fetch('/kb/upload', { method: 'POST', body: fd }).then((r) => r.json())
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
    return fetch('/video/generate', { method: 'POST', body: fd }).then((r) => r.json())
  },
  listVideoTasks: () => getJSON('/video/tasks')
}
