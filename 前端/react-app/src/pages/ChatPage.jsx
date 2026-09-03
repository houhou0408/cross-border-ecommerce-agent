import { useState, useRef, useEffect, useCallback } from 'react'
import { api } from '../api.js'
import Message from '../components/Message.jsx'
import Lightbox from '../components/Lightbox.jsx'
import { IconChat } from '../components/Icons.jsx'

const EXAMPLES = [
  '美国电子产品关税+换算人民币',
  'Shopee上架规范',
  '新手选品建议',
  '欧盟电子产品认证'
]
const EXAMPLE_QUERIES = [
  '蓝牙音箱出口美国电子产品，货值500美元，查关税并换算成人民币',
  'Shopee上架有什么规范要求？',
  '新手卖家做跨境电商，选品有什么建议？',
  '欧盟电子产品需要哪些认证？'
]
// 上传图片后推荐的生成类问题
const IMAGE_EXAMPLES = [
  '用这张商品图生成宣传视频',
  '基于这张图生成电商卖点图'
]

// 智能对话页：支持多轮对话记忆（基于 session_id 加载历史）+ 发送中途停止
export default function ChatPage({ onDataChanged, onNewChat, sessionId, onSessionChange }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [imageFile, setImageFile] = useState(null)       // 待上传的图片文件
  const [imagePreview, setImagePreview] = useState(null) // 图片预览 URL
  const [imagePath, setImagePath] = useState(null)       // 上传成功后后端返回的路径
  const [uploading, setUploading] = useState(false)      // 图片上传中
  const [lightbox, setLightbox] = useState(null) // { src, type }
  const boxRef = useRef(null)
  const abortRef = useRef(null)  // 存储当前请求的 AbortController
  const imgInputRef = useRef(null) // 图片文件选择 input

  // 事件委托：点击对话气泡内的图片/视频 → 打开灯箱
  const onMessagesClick = (e) => {
    const el = e.target
    if (el.classList?.contains('md-image')) {
      setLightbox({ src: el.getAttribute('src'), type: 'image' })
    } else if (el.classList?.contains('md-video')) {
      setLightbox({ src: el.getAttribute('src'), type: 'video' })
    }
  }

  // 选择图片：本地预览 + 上传到后端拿 image_path
  const onPickImage = async (e) => {
    const f = e.target.files?.[0]
    if (!f) return
    if (!f.type.startsWith('image/')) return
    setImageFile(f)
    setImagePreview(URL.createObjectURL(f))
    setImagePath(null)
    setUploading(true)
    try {
      const d = await api.uploadChatImage(f)
      if (d.image_path) {
        setImagePath(d.image_path)
      }
    } catch {
      /* 上传失败则 imagePath 保持 null，发送时不携带 */
    } finally {
      setUploading(false)
    }
  }

  // 移除已选图片
  const onRemoveImage = () => {
    setImageFile(null)
    setImagePreview(null)
    setImagePath(null)
    if (imgInputRef.current) imgInputRef.current.value = ''
  }

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
    const el = boxRef.current
    if (!el) return
    // 立即滚到底部
    el.scrollTop = el.scrollHeight
    // 延迟再滚一次，应对图片/视频异步加载导致高度变化
    const t = setTimeout(() => {
      if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight
    }, 120)
    return () => clearTimeout(t)
  }, [messages, sending, loadingHistory])

  const pushMsg = (msg) => setMessages((prev) => [...prev, msg])

  const onSend = async (text) => {
    if (!text.trim() || sending) return
    // 若正在上传图片，等待上传完成
    if (uploading) return
    pushMsg({ role: 'user', text, meta: null, image: imagePreview })
    setInput('')
    setSending(true)

    // 创建 AbortController，支持中途停止
    const ctrl = new AbortController()
    abortRef.current = ctrl
    // 捕获本次发送携带的图片路径（发送后立即清空）
    const sendImagePath = imagePath

    try {
      const d = await api.ask(text, sessionId, ctrl.signal, sendImagePath)
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
      // 发送完成后清空已上传图片
      onRemoveImage()
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
      <div className="messages" ref={boxRef} onClick={onMessagesClick}>
        {loadingHistory && (
          <div className="hist-loading">加载历史对话...</div>
        )}
        {/* 空状态引导（无会话 或 新会话无消息） */}
        {isEmpty && (
          <div className="chat-empty">
            <div className="empty-icon"><IconChat size={36} /></div>
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
        {/* 已选图片预览条 */}
        {imagePreview && (
          <div className="chat-image-bar">
            <div className="chat-image-preview">
              <img src={imagePreview} alt="商品图" />
              <div className="chat-image-status">
                {uploading ? '上传中…' : imagePath ? '已就绪' : '上传失败'}
              </div>
            </div>
            <button className="chat-image-remove" onClick={onRemoveImage} title="移除图片">
              ✕
            </button>
          </div>
        )}
        {!isEmpty && (
          <div className="examples">
            {(imagePath ? IMAGE_EXAMPLES : EXAMPLES).map((label, i) => (
              <button key={i} onClick={() => {
                if (imagePath) {
                  setInput(i === 0 ? '用这张商品图生成宣传视频' : '基于这张图生成电商卖点图')
                } else {
                  setInput(EXAMPLE_QUERIES[i])
                }
              }}>
                {label}
              </button>
            ))}
          </div>
        )}
        <div className="input-bar">
          {/* 图片上传按钮 */}
          <input
            ref={imgInputRef}
            type="file"
            accept="image/*"
            style={{ display: 'none' }}
            onChange={onPickImage}
          />
          <button
            className="send-btn img-btn"
            onClick={() => imgInputRef.current?.click()}
            disabled={sending || uploading}
            title="上传商品图片（用于图生视频/卖点图）"
          >
            📎
          </button>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder={imagePath
              ? '已上传商品图，输入"生成宣传视频"或"生成卖点图"即可调用工具'
              : (hasSession ? '输入任务，Enter 发送 · Shift+Enter 换行（支持上下文追问）' : '输入问题自动创建对话，或先点 + 新建')}
          />
          {sending ? (
            <button className="send-btn stop" onClick={onStop}>
              ⏹ 停止
            </button>
          ) : (
            <button className="send-btn primary" onClick={() => onSend(input)} disabled={!input.trim() || uploading}>
              发送
            </button>
          )}
        </div>
      </div>
      {/* 图片/视频灯箱：点击放大查看 + 下载 */}
      {lightbox && (
        <Lightbox
          src={lightbox.src}
          type={lightbox.type}
          onClose={() => setLightbox(null)}
        />
      )}
    </div>
  )
}
