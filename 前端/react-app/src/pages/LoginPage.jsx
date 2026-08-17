import { useState } from 'react'
import { api, tokenStore } from '../api.js'

// 登录/注册页：极简 B 端风格，蓝色单一强调色
export default function LoginPage({ onLogin }) {
  const [mode, setMode] = useState('login') // login | register
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const onSubmit = async (e) => {
    e.preventDefault()
    setError('')

    if (!username.trim()) {
      setError('请输入用户名')
      return
    }
    if (!password) {
      setError('请输入密码')
      return
    }

    setLoading(true)
    try {
      const fn = mode === 'login' ? api.login : api.register
      const d = await fn(username.trim(), password)

      if (d.ok) {
        if (mode === 'register') {
          // 注册成功后自动登录
          const loginRes = await api.login(username.trim(), password)
          if (loginRes.ok) {
            tokenStore.set(loginRes.token)
            onLogin(loginRes.user)
          } else {
            setError(loginRes.error || '自动登录失败，请手动登录')
            setMode('login')
          }
        } else {
          tokenStore.set(d.token)
          onLogin(d.user)
        }
      } else {
        setError(d.error || '操作失败')
      }
    } catch (err) {
      setError('网络错误：' + err.message)
    } finally {
      setLoading(false)
    }
  }

  const switchMode = (m) => {
    if (m === mode) return
    setMode(m)
    setError('')
  }

  return (
    <div className="login-page">
      <div className="login-card">
        {/* 品牌标题 */}
        <div className="login-brand">
          <h1>跨境电商 AI Agent</h1>
          <p>Cross-Border E-Commerce AI Platform</p>
        </div>

        {/* 登录/注册切换 */}
        <div className="login-tabs">
          <button
            className={`login-tab ${mode === 'login' ? 'active' : ''}`}
            onClick={() => switchMode('login')}
          >
            登录
          </button>
          <button
            className={`login-tab ${mode === 'register' ? 'active' : ''}`}
            onClick={() => switchMode('register')}
          >
            注册
          </button>
        </div>

        {/* 表单 */}
        <form className="login-form" onSubmit={onSubmit}>
          <div className="login-field">
            <label>用户名</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="请输入用户名"
              autoComplete="username"
            />
          </div>
          <div className="login-field">
            <label>密码</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === 'register' ? '至少 6 位' : '请输入密码'}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </div>

          {error && <div className="login-error">{error}</div>}

          <button type="submit" className="login-submit" disabled={loading}>
            {loading ? '处理中...' : (mode === 'login' ? '登录' : '注册')}
          </button>
        </form>

        <div className="login-hint">
          {mode === 'login' ? '没有账号？' : '已有账号？'}
          <button
            className="login-switch"
            onClick={() => switchMode(mode === 'login' ? 'register' : 'login')}
          >
            {mode === 'login' ? '立即注册' : '立即登录'}
          </button>
        </div>
      </div>
    </div>
  )
}
