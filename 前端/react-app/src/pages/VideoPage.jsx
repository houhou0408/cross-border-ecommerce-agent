import { useState, useRef, useCallback, useEffect } from 'react'
import { api } from '../api.js'

// 视频生成页：上传商品图片 + 描述 → 生成产品宣传视频（图生视频）
export default function VideoPage() {
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [prompt, setPrompt] = useState('')
  const [generating, setGenerating] = useState(false)
  const [result, setResult] = useState(null)
  const [history, setHistory] = useState([])
  const [toast, setToast] = useState(null)
  const fileRef = useRef(null)

  const loadHistory = useCallback(async () => {
    try {
      const d = await api.listVideoTasks()
      setHistory(d.tasks || [])
    } catch {
      /* 静默 */
    }
  }, [])

  useEffect(() => {
    loadHistory()
  }, [loadHistory])

  const notify = (msg) => {
    const t = Date.now()
    setToast({ msg, ts: t })
    setTimeout(() => setToast((c) => (c && c.ts === t ? null : c)), 2500)
  }

  const onSelectFile = (e) => {
    const f = e.target.files?.[0]
    if (!f) return
    if (!f.type.startsWith('image/')) {
      notify('请上传图片文件')
      return
    }
    setFile(f)
    setPreview(URL.createObjectURL(f))
    setResult(null)
  }

  // 移除已选图片，回到空状态
  const onRemoveImage = () => {
    setFile(null)
    setPreview(null)
    if (fileRef.current) fileRef.current.value = ''
  }

  // 重新选择图片（直接触发文件选择）
  const onReselect = () => {
    fileRef.current?.click()
  }

  const onGenerate = async () => {
    if (!file) {
      notify('请先上传商品图片')
      return
    }
    setGenerating(true)
    setResult(null)
    try {
      const d = await api.generateVideo(file, prompt)
      if (d.error) {
        notify('生成失败：' + d.error)
      } else {
        setResult(d)
        notify('视频已生成')
        loadHistory()
      }
    } catch (e) {
      notify('生成失败：' + e.message)
    } finally {
      setGenerating(false)
    }
  }

  const onDrop = (e) => {
    e.preventDefault()
    const f = e.dataTransfer.files?.[0]
    if (f && f.type.startsWith('image/')) {
      setFile(f)
      setPreview(URL.createObjectURL(f))
      setResult(null)
    }
  }

  return (
    <div className="video-page form-page">
      {/* 上传 + 生成区 */}
      <div className="video-gen-card form-card">
        <h3>产品宣传视频生成</h3>
        <p className="form-hint">
          上传商品图片，输入产品卖点描述，AI 生成动态宣传视频。
        </p>

        {/* 图片上传区（居中，带操作按钮） */}
        <div className="upload-section">
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            onChange={onSelectFile}
            style={{ display: 'none' }}
          />
          <div
            className={`upload-zone ${preview ? 'has-img' : ''}`}
            onClick={() => !preview && fileRef.current?.click()}
            onDrop={onDrop}
            onDragOver={(e) => e.preventDefault()}
          >
            {preview ? (
              <>
                <img src={preview} alt="商品图" className="upload-preview" />
                <div className="upload-overlay">
                  <button className="overlay-btn" onClick={(e) => { e.stopPropagation(); onReselect() }}>
                    🔄 重新选择
                  </button>
                  <button className="overlay-btn danger" onClick={(e) => { e.stopPropagation(); onRemoveImage() }}>
                    ✕ 移除
                  </button>
                </div>
              </>
            ) : (
              <div className="upload-placeholder">
                <span className="upload-icon">📷</span>
                <span>点击或拖拽上传商品图片</span>
                <span className="upload-hint">支持 JPG / PNG</span>
              </div>
            )}
          </div>
        </div>

        {/* 描述 + 生成按钮（独立一行，不再溢出） */}
        <div className="video-form">
          <label className="form-label">产品描述 / 卖点</label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="如：防水蓝牙音箱，户外运动场景，阳光下展示质感，20小时续航"
            rows={3}
          />
          <div className="video-actions">
            <button
              className="btn primary"
              onClick={onGenerate}
              disabled={generating || !file}
            >
              {generating ? '⏳ 生成中...' : '🎬 生成视频'}
            </button>
            {file && !generating && (
              <button className="btn ghost" onClick={onRemoveImage}>
                取消
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 结果展示 */}
      {result && (
        <div className="video-result-card form-card">
          <h3>生成结果</h3>
          {result.image_url && (
            <div className="result-images">
              <div className="result-item">
                <span className="result-label">商品原图</span>
                <img src={result.image_url} alt="原图" className="result-img" />
              </div>
              <span className="result-arrow">→</span>
              <div className="result-item">
                <span className="result-label">宣传视频</span>
                <video
                  src={result.video_url}
                  controls
                  autoPlay
                  loop
                  className="result-video"
                />
              </div>
            </div>
          )}
          {!result.image_url && (
            <video
              src={result.video_url}
              controls
              autoPlay
              loop
              className="result-video-full"
            />
          )}
          {result.used_fallback && (
            <p className="result-tip">
              💡 当前为示例视频。配置 VIDEO_API_KEY 环境变量后可生成真实 AI 视频。
            </p>
          )}
        </div>
      )}

      {/* 历史记录（始终显示，空时给提示） */}
      <div className="video-history form-card">
        <h3>生成历史</h3>
        {history.length > 0 ? (
          <div className="hist-list">
            {history.map((t) => (
              <div className="hist-item" key={t.id}>
                {t.image_url && <img src={t.image_url} alt="" className="hist-thumb" />}
                <div className="hist-info">
                  <span className="hist-prompt">{t.prompt || '（无描述）'}</span>
                  <span className="hist-time">{t.created_at}</span>
                </div>
                <span className={`hist-status ${t.used_fallback ? 'fallback' : 'done'}`}>
                  {t.used_fallback ? '示例' : 'AI生成'}
                </span>
                <a href={t.video_url} target="_blank" rel="noreferrer" className="hist-link">
                  查看
                </a>
              </div>
            ))}
          </div>
        ) : (
          <div className="hist-empty">暂无生成记录，上传图片开始体验</div>
        )}
      </div>

      {toast && (
        <div className="toast">
          <span className="toast-icon">✓</span>
          <span>{toast.msg}</span>
        </div>
      )}
    </div>
  )
}
