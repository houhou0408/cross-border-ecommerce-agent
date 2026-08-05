// 运行统计页：独立展示可观测指标
export default function StatsPage({ stats, version, onRefresh }) {
  // version 变化时父组件已刷新 stats，这里仅用于触发重渲染
  void version

  const total = stats?.total_calls || 0
  const latency = stats?.avg_latency_ms ? Math.round(stats.avg_latency_ms) : 0
  const score = stats?.avg_grounding_score ? stats.avg_grounding_score.toFixed(2) : '0.00'
  const hallu = ((stats?.hallucination_block_rate || 0) * 100).toFixed(0) + '%'
  const toolFreq = stats?.tool_frequency || {}
  const lastSession = stats?.last_session

  const cards = [
    { label: '调用次数', value: total, color: 'info', icon: '📞', grad: 'blue' },
    { label: '平均耗时', value: latency, unit: 'ms', color: 'purple', icon: '⚡', grad: 'violet' },
    { label: '平均置信度', value: score, color: 'ok', icon: '✓', grad: 'green' },
    { label: '幻觉拦截率', value: hallu, color: 'warn', icon: '⚠', grad: 'amber' }
  ]

  return (
    <div className="stats-page">
      <div className="stats-head">
        <p className="stats-tip">📊 可观测指标随调用实时更新（每 15 秒自动刷新）</p>
        <button className="btn" onClick={onRefresh}>
          🔄 刷新
        </button>
      </div>

      <div className="stat-cards">
        {cards.map((c, i) => (
          <div className="stat-card" key={i}>
            <div className={`stat-icon grad-${c.grad}`}>{c.icon}</div>
            <div className={`stat-value ${c.color}`}>
              {c.value}
              {c.unit ? <span className="unit">{c.unit}</span> : null}
            </div>
            <div className="stat-label">{c.label}</div>
          </div>
        ))}
      </div>

      <div className="stats-grid">
        <div className="stat-detail">
          <h3><span className="hd-tag" /> 工具调用频次</h3>
          {Object.keys(toolFreq).length === 0 ? (
            <div className="result-empty">
              <div className="result-empty-icon">🔧</div>
              <div className="result-empty-text">暂无调用记录</div>
              <div className="result-empty-hint">在智能对话中使用工具后此处将显示统计</div>
            </div>
          ) : (
            <div className="tool-list">
              {Object.entries(toolFreq).map(([name, count], idx) => {
                const max = Math.max(...Object.values(toolFreq))
                const grads = ['violet', 'blue', 'cyan', 'green', 'amber', 'pink', 'orange']
                const g = grads[idx % grads.length]
                return (
                  <div className="tool-row" key={name}>
                    <span className="tool-name">🔧 {name}</span>
                    <div className="tool-bar">
                      <div className={`tool-bar-fill grad-${g}`} style={{ width: `${(count / max) * 100}%` }} />
                    </div>
                    <span className="tool-count">{count}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <div className="stat-detail">
          <h3><span className="hd-tag grad-cyan" /> 最近会话</h3>
          {lastSession ? (
            <div className="last-session-box">
              <div className="ls-icon">💬</div>
              <div className="ls-info">
                <div className="ls-id">会话 ID</div>
                <div className="ls-val">{lastSession}</div>
              </div>
              <span className="ls-badge">活跃</span>
            </div>
          ) : (
            <div className="result-empty">
              <div className="result-empty-icon">💬</div>
              <div className="result-empty-text">暂无会话</div>
              <div className="result-empty-hint">在智能对话中发起对话后将显示最近会话</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
