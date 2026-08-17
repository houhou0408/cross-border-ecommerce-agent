import { useState } from 'react'
import { renderMd } from '../utils/md.js'

// 单条消息：头像 + 气泡(markdown) + 可折叠溯源模块 + 元信息标签
export default function Message({ msg }) {
  const isBot = msg.role === 'bot'
  const meta = msg.meta
  const sources = meta?.sources || []
  const [traceOpen, setTraceOpen] = useState(false)

  return (
    <div className={`msg ${msg.role}`}>
      <div className="avatar">{isBot ? 'AI' : '我'}</div>

      {/* 思考中占位 */}
      {msg.thinking ? (
        <div className="bubble thinking-bubble">
          <span className="spinner" />
          Agent 正在思考并调用工具…
        </div>
      ) : (
        <div className="bubble-wrap">
          <div
            className="bubble"
            dangerouslySetInnerHTML={isBot ? { __html: renderMd(msg.text) } : undefined}
          >
            {!isBot ? msg.text : null}
          </div>

          {/* 用户消息附带的上传图片 */}
          {!isBot && msg.image && (
            <div className="msg-attach-image">
              <img src={msg.image} alt="附件" />
            </div>
          )}

          {/* 可折叠：知识库检索溯源 */}
          {isBot && sources.length > 0 && (
            <div className={`trace ${traceOpen ? 'open' : ''}`}>
              <button className="trace-head" onClick={() => setTraceOpen((v) => !v)}>
                <span className="trace-icon">📚</span>
                <span className="trace-title">知识库检索溯源</span>
                <span className="trace-count">{sources.length} 条引用</span>
                <span className={`trace-arrow ${traceOpen ? 'up' : ''}`}>▾</span>
              </button>
              {traceOpen && (
                <div className="trace-body">
                  {sources.map((s) => (
                    <div className="trace-item" key={s.index}>
                      <div className="trace-item-head">
                        <span className="trace-idx">[{s.index}]</span>
                        <span className="trace-src">{s.source}</span>
                        <span className="trace-score">相关度 {s.score.toFixed(2)}</span>
                      </div>
                      <div className="trace-snippet">{s.snippet}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 工具调用时间线 */}
          {meta && meta.tools_used && meta.tools_used.length > 0 && (
            <div className="toolline">
              {meta.tools_used.map((t, i) => (
                <span key={i}>
                  <span className="step">🔧 {t.tool}</span>
                  {i < meta.tools_used.length - 1 ? <span className="arrow"> → </span> : null}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 元信息标签 */}
      {meta && !msg.thinking && (
        <div className="meta">
          <span className="tag time">⏱ {meta.latency_ms || 0}ms</span>
          {meta.session_id ? <span className="tag">#{meta.session_id}</span> : null}
          {meta.grounded ? (
            <span className="tag ok">✓ 置信度 {(meta.score || 0).toFixed(2)}</span>
          ) : (
            <span className="tag warn">
              ⚠ 置信度 {(meta.score || 0).toFixed(2)} · 幻觉风险
            </span>
          )}
        </div>
      )}
    </div>
  )
}
