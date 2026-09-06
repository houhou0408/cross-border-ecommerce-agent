import { useState } from 'react'
import { api, tokenStore } from '../api.js'

// 登录/注册页：品牌化落地页风格（紫红主色 + 网格背景 + hero 左文右卡）
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
      {/* 装饰性浮岛导航（仅品牌） */}
      <div className="login-topbar">跨境电商 AI Agent</div>

      {/* hero：左侧品牌文案 + 右侧登录卡片 */}
      <div className="login-hero">
        <div className="login-hero-left">
          <span className="login-badge">跨境卖家效率引擎！</span>
          <h1 className="login-title">跨境电商 AI Agent</h1>
          <p className="login-sub">
            用一句话完成 Listing 文案、卖点图与视频素材生成；内置智能客服、知识库检索与
            ReAct 多任务编排，覆盖跨境卖家从选品到售后的全流程。
          </p>
          <div className="login-feats">
            <div className="login-feat">
              <strong>一句话描述</strong>
              <span>输入方式</span>
            </div>
            <div className="login-feat">
              <strong>Listing / 视频 / 卖点图</strong>
              <span>输出形式</span>
            </div>
          </div>
        </div>

        <div className="login-card">
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

      <div className="login-foot">AI 生成内容仅供参考 · 请遵守各平台发布规范</div>
    </div>
  )
}
