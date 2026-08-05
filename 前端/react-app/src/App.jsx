import { useState, useEffect, useCallback } from 'react'
import ChatPage from './pages/ChatPage.jsx'
import ListingPage from './pages/ListingPage.jsx'
import TariffPage from './pages/TariffPage.jsx'
import CurrencyPage from './pages/CurrencyPage.jsx'
import StatsPage from './pages/StatsPage.jsx'
import KbPage from './pages/KbPage.jsx'
import EvalPage from './pages/EvalPage.jsx'
import VideoPage from './pages/VideoPage.jsx'
import { api } from './api.js'

// 左侧功能导航
const NAV = [
  { key: 'chat', label: '智能对话', icon: '💬', desc: 'ReAct 多任务编排' },
  { key: 'kb', label: '知识库管理', icon: '📚', desc: '文档上传与检索配置' },
  { key: 'video', label: '视频生成', icon: '🎬', desc: '商品宣传视频' },
  { key: 'listing', label: 'Listing 生成', icon: '📝', desc: '产品文案生成' },
  { key: 'tariff', label: '关税查询', icon: '🛃', desc: '跨境关税计算' },
  { key: 'currency', label: '汇率换算', icon: '💱', desc: '多币种转换' },
  { key: 'stats', label: '运行统计', icon: '📊', desc: '调用与可观测' },
  { key: 'eval', label: '效果评估', icon: '🎯', desc: 'Agent 质量评估' }
]

export default function App() {
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

  useEffect(() => {
    checkHealth()
    refreshStats()
    refreshSessions()
    const t = setInterval(refreshStats, 15000)
    return () => clearInterval(t)
  }, [checkHealth, refreshStats, refreshSessions])

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

  return (
    <div className="shell">
      <aside className="nav">
        <div className="nav-brand">
          <div className="logo">🛒</div>
          <div className="brand-text">
            <div className="brand-title">跨境电商 AI Agent</div>
            <div className="brand-sub">Cross-Border Agent</div>
          </div>
        </div>

        {/* 「对话」标题 + 新建按钮（真实生效） */}
        {active === 'chat' && (
          <>
            <div className="sess-head">
              <span className="sess-title">对话</span>
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
          </>
        )}

        {/* 功能导航 */}
        <nav className="nav-list">
          {NAV.map((item) => (
            <button
              key={item.key}
              className={`nav-item ${active === item.key ? 'active' : ''}`}
              onClick={() => setActive(item.key)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-text">
                <span className="nav-label">{item.label}</span>
                <span className="nav-desc">{item.desc}</span>
              </span>
            </button>
          ))}
        </nav>

        <div className="nav-foot">
          <div className="model-card">
            <div className="mc-label">已接入</div>
            <div className="mc-row">
              <span className="mc-dot" />
              <span>DeepSeek V4-Flash</span>
            </div>
            <div className="mc-row">
              <span className="mc-dot violet" />
              <span>Chroma 向量库</span>
            </div>
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="page-head">
          <h2>{activeNav.label}</h2>
          <span className="sep">|</span>
          <p className="page-sub">{activeNav.desc}</p>
          <span className="head-status">
            <span className="status-dot" /> {health}
          </span>
        </header>
        <div className="page-body">{renderPage()}</div>
        {toast && (
          <div className="toast">
            <span className="toast-icon">✓</span>
            <span>{toast.msg}</span>
          </div>
        )}
      </main>
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
