import { useState, useRef, useEffect } from 'react'
import Message from './Message.jsx'

// 聊天区：消息列表 + 示例按钮 + 输入框
export default function ChatPanel({ messages, sending, onSend, examples, exampleQueries }) {
  const [input, setInput] = useState('')
  const boxRef = useRef(null)

  // 新消息自动滚到底
  useEffect(() => {
    if (boxRef.current) {
      boxRef.scrollTop = boxRef.scrollHeight
    }
  }, [messages])

  const handleSend = () => {
    const t = input.trim()
    if (!t || sending) return
    setInput('')
    onSend(t)
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const fillExample = (i) => {
    setInput(exampleQueries[i])
  }

  return (
    <div className="chat">
      <div className="messages" ref={boxRef}>
        {messages.map((m, i) => (
          <Message key={i} msg={m} />
        ))}
        {sending && <Message msg={{ role: 'bot', text: '', thinking: true, meta: null }} />}
      </div>

      <div className="examples">
        {examples.map((label, i) => (
          <button key={i} onClick={() => fillExample(i)}>
            {label}
          </button>
        ))}
      </div>

      <div className="input-bar">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKey}
          placeholder="输入任务，Enter 发送 · Shift+Enter 换行"
        />
        <button className="send-btn" onClick={handleSend} disabled={sending}>
          发送
        </button>
      </div>
    </div>
  )
}
