import { useState, useRef, useEffect, useCallback } from 'react'
import { api } from '../api.js'
import Message from '../components/Message.jsx'

// 买家模式快捷示例
const BUYER_EXAMPLES = [
  '物流一般多久能到？',
  '怎么退换货？',
  '查一下我的订单 ORD2026071803',
  '尺码怎么选'
]
const BUYER_QUERIES = [
  '物流一般多久能到？',
  '怎么退换货？',
  '查一下我的订单 ORD2026071803',
  '尺码怎么选'
]
// 卖家模式快捷示例
const SELLER_EXAMPLES = [
  '买家问物流多久到',
  '买家想退货',
  '买家说商品有质量问题要退款',
  '买家催发货'
]
const SELLER_QUERIES = [
  '有个买家问我：物流一般需要多久才能到？怎么回复比较好',
  '买家说收到了但不喜欢，想退货，怎么安抚并引导',
  '买家反馈收到货有瑕疵要求全额退款，怎么处理话术',
  '买家一直催发货，怎么礼貌回复'
]

export default function SupportPage() {
  const [mode, setMode] = useState('buyer')   // buyer=买家客服 / seller=卖家话术助手
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [sessionId, setSessionId] = useState(null)
  const [transferred, setTransferred] = useState(false)
  const [toast, setToast] = useState(null)
  const boxRef = useRef(null)

  // 切模式时保留会话，但提示已切换
  useEffect(() => {
    setTransferred(false)
  }, [mode])

  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
    const t = setTimeout(() => { if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight }, 120)
    return () => clearTimeout(t)
  }, [messages, sending])

  const pushMsg = (m) => setMessages((prev) => [...prev, m])

  const showToast = (msg) => {
    const t = Date.now()
    setToast({ msg, ts: t })
    setTimeout(() => setToast((cur) => (cur && cur.ts === t ? null : cur)), 2500)
  }

  const onSend = async (text) => {
    if (!text.trim() || sending) return
    pushMsg({ role: 'user', text, meta: null })
    setInput('')
    setSending(true)
    try {
      const d = await api.supportAsk(text, mode, sessionId)
      if (d.session_id) setSessionId(d.session_id)
      // 客服回答标注：faq/order/guide 为确定性来源，置信度取 1；LLM 生成取后端 score
      const grounded = d.grounded ?? true
      pushMsg({ role: 'bot', text: d.reply || d.error || '(空)', meta: { type: d.type || 'llm', grounded, score: d.score ?? (grounded ? 1 : 0) } })
    } catch (e) {
      pushMsg({ role: 'bot', text: '❌ 请求失败：' + e.message, meta: null })
    } finally {
      setSending(false)
    }
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSend(input) }
  }

  const onTransfer = async () => {
    if (!sessionId) { showToast('请先发起咨询后再转人工'); return }
    setSending(true)
    try {
      const d = await api.supportTransfer(sessionId)
      pushMsg({ role: 'bot', text: d.msg, meta: { type: 'transfer' } })
      setTransferred(true)
    } catch (e) {
      showToast('转人工失败：' + e.message)
    } finally {
      setSending(false)
    }
  }

  // 人工评价：拿到最后一条机器人回复做评价
  const onReview = async (rating) => {
    const lastBot = [...messages].reverse().find((m) => m.role === 'bot' && m.text)
    if (!lastBot) { showToast('暂无评价内容'); return }
    try {
      await api.supportReview({ session_id: sessionId, query: '', answer: lastBot.text, rating, comment: rating === 'good' ? '客服好评' : '客服差评' })
      showToast(rating === 'good' ? '感谢好评，我们会继续努力' : '感谢反馈，我们会优化')
    } catch {
      showToast('评价提交失败')
    }
  }

  const examples = mode === 'buyer' ? BUYER_EXAMPLES : SELLER_EXAMPLES
  const exampleQueries = mode === 'buyer' ? BUYER_QUERIES : SELLER_QUERIES
  const isEmpty = messages.length === 0

  return (
    <div className="support-page">
      {/* 双模式切换（买家客服 / 卖家话术助手） */}
      <div className="video-mode-tabs support-tabs">
        <button className={`mode-tab ${mode === 'buyer' ? 'active' : ''}`}
          onClick={() => setMode('buyer')}>买家接待客服</button>
        <button className={`mode-tab ${mode === 'seller' ? 'active' : ''}`}
          onClick={() => setMode('seller')}>卖家话术助手</button>
      </div>

      <div className="support-panel">
        <div className="support-panel-head">
          <span className="support-mode-tag">{mode === 'buyer' ? '售前售后自动接待' : '生成可复制话术'}</span>
          <div className="support-actions">
            {mode === 'buyer' && !transferred && (
              <button className="btn support-btn" onClick={onTransfer} disabled={sending}>转人工</button>
            )}
            {mode === 'buyer' && (
              <div className="support-review">
                <span className="support-review-label">回答评价</span>
                <button className="rv-btn good" onClick={() => onReview('good')} disabled={sending}>好评</button>
                <button className="rv-btn bad" onClick={() => onReview('bad')} disabled={sending}>差评</button>
              </div>
            )}
          </div>
        </div>

        <div className="messages support-msgs" ref={boxRef}>
          {isEmpty && (
            <div className="chat-empty">
              <div className="empty-icon">🎧</div>
              <h3 className="empty-title">
                {mode === 'buyer' ? '欢迎咨询，我的客服为您服务' : '买家消息 → 一键生成话术'}
              </h3>
              <p className="empty-desc">
                {mode === 'buyer'
                  ? '可咨询物流、退换货、尺码、支付、售后等问题，或直接发订单号查物流状态。'
                  : '输入买家的问题或场景，我为您生成可直接复制、专业且安抚买家情绪的回复话术。'}
              </p>
              <div className="empty-examples">
                {examples.map((label, i) => (
                  <button key={i} className="empty-ex-item"
                    onClick={() => { setInput(exampleQueries[i]); onSend(exampleQueries[i]) }}>
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

        <div className="chat-foot support-foot">
          <div className="input-bar">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKey}
              placeholder={mode === 'buyer'
                ? '输入买家咨询或订单号，Enter 发送 · Shift+Enter 换行'
                : '粘贴买家提问或描述场景，生成回复话术'}
            />
            <button className="send-btn primary" onClick={() => onSend(input)} disabled={!input.trim() || sending}>
              发送
            </button>
          </div>
        </div>
      </div>

      {toast && (
        <div className="toast"><span className="toast-icon">✓</span><span>{toast.msg}</span></div>
      )}
    </div>
  )
}