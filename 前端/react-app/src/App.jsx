import { useState, useEffect, useCallback } from 'react'
import ChatPage from './pages/ChatPage.jsx'
import ListingPage from './pages/ListingPage.jsx'
import TariffPage from './pages/TariffPage.jsx'
import CurrencyPage from './pages/CurrencyPage.jsx'
import StatsPage from './pages/StatsPage.jsx'
import KbPage from './pages/KbPage.jsx'
import EvalPage from './pages/EvalPage.jsx'
import VideoPage from './pages/VideoPage.jsx'
import SupportPage from './pages/SupportPage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import { api, tokenStore } from './api.js'

// 顶部水平导航（极简 B 端：纯文字，无图标）
const NAV = [
  { key: 'chat', label: '智能对话', desc: 'ReAct 多任务编排' },
  { key: 'support', label: '智能客服', desc: '买家接待与卖家话术' },
  { key: 'kb', label: '知识库管理', desc: '文档上传与检索配置' },
  { key: 'video', label: '素材生成', desc: '视频与卖点图生成' },
  { key: 'listing', label: 'Listing 生成', desc: '产品文案生成' },
  { key: 'tariff', label: '关税查询', desc: '跨境关税计算' },
  { key: 'currency', label: '汇率换算', desc: '多币种转换' },
  { key: 'stats', label: '运行统计', desc: '调用与可观测' },
  { key: 'eval', label: '效果评估', desc: 'Agent 质量评估' }
]

export default function App() {
  const [user, setUser] = useState(null)
  const [authChecked, setAuthChecked] = useState(false)
  const [active, setActive] = useState('chat')
  const [health, setHealth] = useState('连接中')
  const [stats, setStats] = useState(null)
  const [statsVersion, setStatsVersion] = useState(0)
  const [chatResetKey, setChatResetKey] = useState(0)
  const [toast, setToast] = useState(null)
  // 会话管理（真实化，从后端加载）
  const [sessions, setSessions] = useState([])
  const [activeSessionId, setActiveSessionId] = useState(null)

  const refreshStats = useCallback(async () => {
    try {
      const d = await api.stats()
      setStats(d)
    } catch {
      /* 静默 */
    }
  }, [])

  const refreshSessions = useCallback(async () => {
    try {
      const d = await api.listSessions()
      setSessions(d.sessions || [])
    } catch {
      /* 静默 */
    }
  }, [])

  const checkHealth = useCallback(async () => {
    try {
      const d = await api.health()
      setHealth(d.service || '服务正常')
    } catch {
      setHealth('未连接')
    }
  }, [])

  // 页面加载时检查 token 是否有效
  useEffect(() => {
    const token = tokenStore.get()
    if (!token) {
      setAuthChecked(true)
      return
    }
    api.getMe()
      .then((d) => {
        if (d.ok) setUser(d.user)
        else tokenStore.clear()
      })
      .catch(() => tokenStore.clear())
      .finally(() => setAuthChecked(true))
  }, [])

  // 任意接口返回 401（token 过期/失效）→ api.js 已清 token 并广播，
  // 此处回到登录页（已有的 if (!user) 门控自动展示 LoginPage）
  useEffect(() => {
    const onAuthExpired = () => {
      setUser(null)
      setActive('chat')
      setSessions([])
      setActiveSessionId(null)
    }
    window.addEventListener('auth:expired', onAuthExpired)
    return () => window.removeEventListener('auth:expired', onAuthExpired)
  }, [])

  // 退出登录
  const onLogout = useCallback(async () => {
    try {
      await api.logout()
    } catch {
      /* 静默 */
    }
    tokenStore.clear()
    setUser(null)
    setActive('chat')
    setSessions([])
    setActiveSessionId(null)
  }, [])

  useEffect(() => {
    if (!user) return
    checkHealth()
    refreshStats()
    refreshSessions()
    const t = setInterval(refreshStats, 15000)
    return () => clearInterval(t)
  }, [checkHealth, refreshStats, refreshSessions, user])

  const onDataChanged = useCallback(() => {
    refreshStats()
    setStatsVersion((v) => v + 1)
  }, [refreshStats])

  // 新建对话：调后端创建会话，刷新列表，激活新会话，重置聊天页
  const onNewChat = useCallback(async () => {
    try {
      const sess = await api.createSession()
      setActiveSessionId(sess.id)
      setChatResetKey((k) => k + 1)
      refreshSessions()
      const t = Date.now()
      setToast({ msg: '已新建对话', ts: t })
      setTimeout(() => setToast((cur) => (cur && cur.ts === t ? null : cur)), 2000)
    } catch (e) {
      const t = Date.now()
      setToast({ msg: '新建失败：' + e.message, ts: t })
      setTimeout(() => setToast((cur) => (cur && cur.ts === t ? null : cur)), 2000)
    }
  }, [refreshSessions])

  // 删除会话
  const onDeleteSession = useCallback(async (sid) => {
    try {
      await api.deleteSession(sid)
      if (activeSessionId === sid) {
        setActiveSessionId(null)
        setChatResetKey((k) => k + 1)
      }
      refreshSessions()
    } catch {
      /* 静默 */
    }
  }, [activeSessionId, refreshSessions])

  // 切换会话
  const onSelectSession = useCallback((sid) => {
    setActiveSessionId(sid)
    setChatResetKey((k) => k + 1)
  }, [])

  const renderPage = () => {
    switch (active) {
      case 'chat':
        return (
          <ChatPage
            key={chatResetKey}
            onDataChanged={onDataChanged}
            onNewChat={onNewChat}
            sessionId={activeSessionId}
            onSessionChange={refreshSessions}
          />
        )
      case 'support':
        return <SupportPage />
      case 'kb':
        return <KbPage />
      case 'listing':
        return <ListingPage onDataChanged={onDataChanged} />
      case 'tariff':
        return <TariffPage onDataChanged={onDataChanged} />
      case 'currency':
        return <CurrencyPage onDataChanged={onDataChanged} />
      case 'stats':
        return <StatsPage stats={stats} version={statsVersion} onRefresh={refreshStats} />
      case 'eval':
        return <EvalPage />
      case 'video':
        return <VideoPage />
      default:
        return null
    }
  }

  const activeNav = NAV.find((n) => n.key === active)

  // 未登录或正在检查 token 时，显示登录页 / 加载中
  if (!authChecked) {
    return <div className="auth-loading"><span className="spinner" /> 正在验证登录状态...</div>
  }
  if (!user) {
    return <LoginPage onLogin={setUser} />
  }

  return (
    <div className="shell">
      {/* 顶部水平导航栏（上导航 + 下内容） */}
      <header className="topbar">
        <div className="topbar-brand">跨境电商 AI Agent</div>
        <nav className="topbar-nav">
          {NAV.map((item) => (
            <button
              key={item.key}
              className={`topbar-tab ${active === item.key ? 'active' : ''}`}
              onClick={() => setActive(item.key)}
              title={item.desc}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="topbar-user">
          <span className="topbar-username">{user.username}</span>
          <button className="topbar-logout" onClick={onLogout}>退出</button>
        </div>
      </header>

      {/* 主内容区：对话页时左侧带会话列表 */}
      <div className="main-wrap">
        {active === 'chat' && (
          <aside className="sess-sidebar">
            <div className="sess-head">
              <span className="sess-title">会话列表</span>
              <button className="sess-new" onClick={onNewChat} title="新建会话">
                <span className="plus">+</span>
              </button>
            </div>
            <div className="sess-list">
              {sessions.length === 0 && (
                <div className="sess-empty">暂无会话，点击 + 新建</div>
              )}
              {sessions.map((s) => (
                <div
                  key={s.id}
                  className={`sess-item ${activeSessionId === s.id ? 'active' : ''}`}
                  onClick={() => onSelectSession(s.id)}
                >
                  <span className="sess-avatar" style={{ background: _colorOf(s.id) }}>
                    {(s.title || '新').charAt(0)}
                  </span>
                  <span className="sess-info">
                    <span className="sess-name">{s.title || '新对话'}</span>
                    <span className="sess-time">{(s.updated_at || '').slice(5, 16)}</span>
                  </span>
                  <span
                    className="sess-del"
                    title="删除"
                    onClick={(e) => { e.stopPropagation(); onDeleteSession(s.id) }}
                  >
                    ×
                  </span>
                </div>
              ))}
            </div>
          </aside>
        )}

        <main className="main">
          <div className="page-body">{renderPage()}</div>
          {toast && (
            <div className="toast">
              <span className="toast-icon">✓</span>
              <span>{toast.msg}</span>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

// 根据会话ID生成稳定颜色
function _colorOf(id) {
  const colors = ['#6366f1', '#8b7ff7', '#06b6d4', '#10b981', '#f59e0b', '#ef4444', '#ec4899']
  let hash = 0
  for (let i = 0; i < (id || '').length; i++) hash = id.charCodeAt(i) + ((hash << 5) - hash)
  return colors[Math.abs(hash) % colors.length]
}
