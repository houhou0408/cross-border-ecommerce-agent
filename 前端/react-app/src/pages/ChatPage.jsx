import { useState, useRef, useEffect, useCallback } from 'react'
import { api } from '../api.js'
import Message from '../components/Message.jsx'

const EXAMPLES = [
  '🔍 美国电子产品关税+换算人民币',
  '📋 Shopee上架规范',
  '💡 新手选品建议',
  '🇪🇺 欧盟电子产品认证'
]
const EXAMPLE_QUERIES = [
  '蓝牙音箱出口美国电子产品，货值500美元，查关税并换算成人民币',
  'Shopee上架有什么规范要求？',
  '新手卖家做跨境电商，选品有什么建议？',
  '欧盟电子产品需要哪些认证？'
]

// 智能对话页：支持多轮对话记忆（基于 session_id 加载历史）+ 发送中途停止
export default function ChatPage({ onDataChanged, onNewChat, sessionId, onSessionChange }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const boxRef = useRef(null)
  const abortRef = useRef(null)  // 存储当前请求的 AbortController

  // 切换会话时加载历史消息（多轮记忆）
  const loadHistory = useCallback(async (sid) => {
    if (!sid) {
      // 无会话：清空消息，显示空状态引导（不显示假对话气泡）
      setMessages([])
      return
    }
    setLoadingHistory(true)
    try {
      const sess = await api.getSession(sid)
      if (sess && sess.messages && sess.messages.length > 0) {
        const histMsgs = sess.messages.map((m) => ({
          role: m.role === 'user' ? 'user' : 'bot',
          text: m.content,
          meta: m.meta || null
        }))
        setMessages(histMsgs)
      } else {
        setMessages([])
      }
    } catch {
      setMessages([])
    } finally {
      setLoadingHistory(false)
    }
  }, [])

  useEffect(() => {
    loadHistory(sessionId)
  }, [sessionId, loadHistory])

  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.scrollHeight
  }, [messages, sending, loadingHistory])

  const pushMsg = (msg) => setMessages((prev) => [...prev, msg])

  const onSend = async (text) => {
    if (!text.trim() || sending) return
    pushMsg({ role: 'user', text, meta: null })
    setInput('')
    setSending(true)

    // 创建 AbortController，支持中途停止
    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      const d = await api.ask(text, sessionId, ctrl.signal)
      // 若后端新建了会话（首次无 sessionId），同步到父组件
      if (!sessionId && d.session_id) {
        onSessionChange()
      }
      pushMsg({ role: 'bot', text: d.answer || d.error || '(空)', meta: d })
      onDataChanged()
      onSessionChange()
    } catch (e) {
      // 用户主动中止时不报错，只提示已停止
      if (e.name === 'AbortError') {
        pushMsg({ role: 'bot', text: '⏹ 已停止生成。', meta: null })
      } else {
        pushMsg({ role: 'bot', text: '❌ 请求失败：' + e.message, meta: null })
      }
    } finally {
      setSending(false)
      abortRef.current = null
    }
  }

  // 中途停止生成
  const onStop = () => {
    if (abortRef.current) {
      abortRef.current.abort()
    }
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSend(input)
    }
  }

  const hasSession = !!sessionId
  const isEmpty = messages.length === 0 && !loadingHistory

  return (
    <div className="chat-page">
      <div className="messages" ref={boxRef}>
        {loadingHistory && (
          <div className="hist-loading">加载历史对话...</div>
        )}
        {/* 空状态引导（无会话 或 新会话无消息） */}
        {isEmpty && (
          <div className="chat-empty">
            <div className="empty-icon">💬</div>
            <h3 className="empty-title">
              {hasSession ? '开始你的对话' : '新建对话开始使用'}
            </h3>
            <p className="empty-desc">
              {hasSession
                ? '输入跨境电商相关问题，Agent 会自动调用工具完成任务。'
                : '点击左侧「+」新建对话，或直接在下方输入问题自动创建。'}
            </p>
            {!hasSession && (
              <button className="btn primary empty-new-btn" onClick={onNewChat}>
                + 新建对话
              </button>
            )}
            <div className="empty-examples">
              <p className="empty-ex-title">试试这些问题：</p>
              {EXAMPLES.map((label, i) => (
                <button
                  key={i}
                  className="empty-ex-item"
                  onClick={() => {
                    if (!hasSession) { onNewChat() }
                    setInput(EXAMPLE_QUERIES[i])
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <Message key={i} msg={m} />
        ))}
        {sending && <Message msg={{ role: 'bot', text: '', thinking: true, meta: null }} />}
      </div>

      <div className="chat-foot">
        {!isEmpty && (
          <div className="examples">
            {EXAMPLES.map((label, i) => (
              <button key={i} onClick={() => setInput(EXAMPLE_QUERIES[i])}>
                {label}
              </button>
            ))}
          </div>
        )}
        <div className="input-bar">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder={hasSession ? '输入任务，Enter 发送 · Shift+Enter 换行（支持上下文追问）' : '输入问题自动创建对话，或先点 + 新建'}
          />
          {sending ? (
            <button className="send-btn stop" onClick={onStop}>
              ⏹ 停止
            </button>
          ) : (
            <button className="send-btn primary" onClick={() => onSend(input)} disabled={!input.trim()}>
              发送
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
