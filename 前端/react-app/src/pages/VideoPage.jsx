import { useState, useRef, useCallback, useEffect } from 'react'
import { api } from '../api.js'
import { IconCamera, IconImage, IconDoc } from '../components/Icons.jsx'

// 素材生成页：支持「图生视频」「文生视频」「卖点图生成」三种模式切换
export default function VideoPage() {
  const [mode, setMode] = useState('r2v') // r2v=图生视频 | t2v=文生视频 | sell=卖点图
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [prompt, setPrompt] = useState('')
  // 卖点图专用状态
  const [product, setProduct] = useState('')
  const [features, setFeatures] = useState('')
  const [generating, setGenerating] = useState(false)
  const [result, setResult] = useState(null)
  const [history, setHistory] = useState([])
  const [toast, setToast] = useState(null)
  const fileRef = useRef(null)

  const loadHistory = useCallback(async () => {
    try {
      const [vd, im] = await Promise.all([api.listVideoTasks(), api.listImageTasks()])
      // 合并视频和图片任务历史，统一展示
      const videoTasks = (vd.tasks || []).map((t) => ({ ...t, kind: 'video' }))
      const imageTasks = (im.tasks || []).map((t) => ({ ...t, kind: 'image' }))
      const all = [...videoTasks, ...imageTasks]
      all.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))
      setHistory(all)
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

  const onRemoveImage = () => {
    setFile(null)
    setPreview(null)
    if (fileRef.current) fileRef.current.value = ''
  }

  const onReselect = () => {
    fileRef.current?.click()
  }

  // 切换模式时清空状态
  const onSwitchMode = (m) => {
    if (m === mode) return
    setMode(m)
    setResult(null)
    if (m === 't2v') {
      setFile(null)
      setPreview(null)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  // 视频任务已改为异步：提交立即返回 task_id，后台生成，此处轮询直到完成
  const pollVideoTask = async (taskId) => {
    const maxTry = 100 // 4s × 100 ≈ 6.7 分钟
    for (let i = 0; i < maxTry; i++) {
      const t = await api.getVideoTask(taskId)
      if (t && t.status === 'completed') return t
      if (t && t.error) throw new Error(t.error)
      await new Promise((r) => setTimeout(r, 4000))
    }
    throw new Error('等待超时，请稍后在生成历史中查看结果')
  }

  const onGenerate = async () => {
    if (mode === 'r2v' && !file) {
      notify('请先上传商品图片')
      return
    }
    if (mode === 't2v' && !prompt.trim()) {
      notify('请输入视频描述')
      return
    }
    if (mode === 'sell' && !file) {
      notify('请先上传商品图片')
      return
    }
    if (mode === 'sell' && !product.trim()) {
      notify('请输入商品描述')
      return
    }
    setGenerating(true)
    setResult(null)
    try {
      let d
      if (mode === 'r2v') {
        d = await api.generateVideo(file, prompt)
      } else if (mode === 't2v') {
        d = await api.generateTextVideo(prompt)
      } else {
        d = await api.generateSellingImages(file, product, features)
      }
      if (d.error) {
        notify('生成失败：' + d.error)
        return
      }
      if (mode === 'sell') {
        setResult(d)
        notify('卖点图已生成')
        loadHistory()
        return
      }
      // 视频模式：异步任务 → 轮询直到完成
      notify('任务已提交，后台生成中…')
      const fin = await pollVideoTask(d.task_id)
      setResult(fin)
      notify(mode === 'r2v' ? '视频已生成' : '文生视频已生成')
      loadHistory()
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

  const isSellMode = mode === 'sell'
  const needImage = mode === 'r2v' || isSellMode
  const canGenerate = !generating && (
    (mode === 'r2v' && file) ||
    (mode === 't2v' && prompt.trim()) ||
    (isSellMode && file && product.trim())
  )

  return (
    <div className="video-page form-page">
      {/* 模式切换 */}
      <div className="video-mode-tabs">
        <button
          className={`mode-tab ${mode === 'r2v' ? 'active' : ''}`}
          onClick={() => onSwitchMode('r2v')}
        >
          图生视频
        </button>
        <button
          className={`mode-tab ${mode === 't2v' ? 'active' : ''}`}
          onClick={() => onSwitchMode('t2v')}
        >
          文生视频
        </button>
        <button
          className={`mode-tab ${mode === 'sell' ? 'active' : ''}`}
          onClick={() => onSwitchMode('sell')}
        >
          卖点图生成
        </button>
      </div>

      {/* 上传 + 生成区 */}
      <div className="video-gen-card form-card">
        <h3>
          {mode === 'r2v' ? '产品宣传视频生成' : (mode === 't2v' ? '文生视频生成' : '商品卖点图生成')}
        </h3>
        <p className="form-hint">
          {mode === 'r2v'
            ? '上传商品图片，输入产品卖点描述，AI 生成动态宣传视频。'
            : (mode === 't2v'
              ? '输入文字描述，AI 直接生成视频（无需图片），适合创意短片与场景演示。'
              : '上传商品图片，填写商品描述与卖点，AI 一键生成 4 种电商标准营销图（白底主图/场景图/卖点标注图/详情长图）。')}
        </p>

        {/* 需要图片的模式：显示图片上传区 */}
        {needImage && (
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
                      重新选择
                    </button>
                    <button className="overlay-btn danger" onClick={(e) => { e.stopPropagation(); onRemoveImage() }}>
                      移除
                    </button>
                  </div>
                </>
              ) : (
                <div className="upload-placeholder">
                  <span className="upload-icon"><IconCamera size={26} /></span>
                  <span>点击或拖拽上传商品图片</span>
                  <span className="upload-hint">支持 JPG / PNG</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* 卖点图模式：商品描述 + 卖点输入 */}
        {isSellMode ? (
          <div className="video-form">
            <label className="form-label">商品描述</label>
            <input
              type="text"
              className="sell-input"
              value={product}
              onChange={(e) => setProduct(e.target.value)}
              placeholder="如：防水蓝牙音箱，黑色圆柱形，户外便携"
            />
            <label className="form-label" style={{ marginTop: 12 }}>产品卖点（逗号分隔，可选）</label>
            <textarea
              value={features}
              onChange={(e) => setFeatures(e.target.value)}
              placeholder="如：20小时续航, IPX7防水, 蓝牙5.3, 360度环绕音"
              rows={2}
            />
            <div className="video-actions">
              <button
                className="btn primary"
                onClick={onGenerate}
                disabled={!canGenerate}
              >
                {generating ? '生成中（4张图约1-2分钟）...' : '生成全套卖点图'}
              </button>
              {(file || product || features) && !generating && (
                <button
                  className="btn ghost"
                  onClick={() => {
                    onRemoveImage()
                    setProduct('')
                    setFeatures('')
                    setResult(null)
                  }}
                >
                  取消
                </button>
              )}
            </div>
          </div>
        ) : (
          /* 视频模式：描述 + 生成按钮 */
          <div className="video-form">
            <label className="form-label">
              {mode === 'r2v' ? '产品描述 / 卖点' : '视频描述'}
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={
                mode === 'r2v'
                  ? '如：防水蓝牙音箱，户外运动场景，阳光下展示质感，20小时续航'
                  : '如：一只猫在阳光下打盹，慵懒午后，暖色调，慢镜头，电影感'
              }
              rows={3}
            />
            <div className="video-actions">
              <button
                className="btn primary"
                onClick={onGenerate}
                disabled={!canGenerate}
              >
                {generating ? '后台生成中（约 1-5 分钟）…' : '生成视频'}
              </button>
              {(file || prompt) && !generating && (
                <button
                  className="btn ghost"
                  onClick={() => {
                    if (mode === 'r2v') {
                      onRemoveImage()
                    }
                    setPrompt('')
                    setResult(null)
                  }}
                >
                  取消
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 结果展示：卖点图模式 */}
      {result && isSellMode && (
        <div className="video-result-card form-card">
          <h3>卖点图生成结果</h3>
          {result.image_url && (
            <div className="sell-original">
              <span className="result-label">商品原图</span>
              <img src={result.image_url} alt="原图" className="sell-orig-img" />
            </div>
          )}
          <div className="sell-grid">
            {Object.entries(result.images || {}).map(([key, img]) => (
              <div className={`sell-card ${key === 'detail' ? 'wide' : ''}`} key={key}>
                <div className="sell-card-head">
                  <span className="sell-card-name">{img.name}</span>
                  {img.fallback && <span className="sell-tag-fallback">占位图</span>}
                </div>
                <img src={img.url} alt={img.name} className="sell-img" />
                <a href={img.url} target="_blank" rel="noreferrer" className="sell-dl">
                  查看大图 ↗
                </a>
              </div>
            ))}
          </div>
          {result.used_fallback && (
            <p className="result-tip">
              当前为占位图。配置 DASHSCOPE_API_KEY 环境变量后可生成真实 AI 卖点图。
            </p>
          )}
        </div>
      )}

      {/* 结果展示：视频模式 */}
      {result && !isSellMode && (
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
              当前为示例视频。配置 DASHSCOPE_API_KEY 环境变量后可生成真实 AI 视频。
            </p>
          )}
        </div>
      )}

      {/* 历史记录 */}
      <div className="video-history form-card">
        <div className="hist-header">
          <h3>生成历史</h3>
          {history.length > 0 && (
            <button
              className="btn ghost small"
              onClick={async () => {
                for (const t of history) {
                  const apiFn = t.kind === 'image' ? api.deleteImageTask : api.deleteVideoTask
                  await apiFn(t.id)
                }
                notify('已清空全部历史')
                setHistory([])
              }}
            >
              清空全部
            </button>
          )}
        </div>
        {history.length > 0 ? (
          <div className="hist-list">
            {history.map((t) => (
              <div className="hist-item" key={(t.kind || 'video') + '_' + t.id}>
                {t.kind === 'image' ? (
                  <span className="hist-thumb-text"><IconImage /></span>
                ) : (
                  t.image_url ? (
                    <img src={t.image_url} alt="" className="hist-thumb" />
                  ) : (
                    <span className="hist-thumb-text"><IconDoc /></span>
                  )
                )}
                <div className="hist-info">
                  <span className="hist-prompt">
                    {t.kind === 'image' ? (t.product || '（无描述）') : (t.prompt || '（无描述）')}
                  </span>
                  <span className="hist-time">{t.created_at}</span>
                </div>
                <span className={`hist-status ${t.used_fallback ? 'fallback' : 'done'}`}>
                  {t.kind === 'image' ? '卖点图' : (t.used_fallback ? '示例' : (t.mode === 't2v' ? '文生' : 'AI生成'))}
                </span>
                {t.kind === 'image' ? (
                  <span className="hist-link" onClick={() => setResult(t)} style={{ cursor: 'pointer' }}>
                    查看
                  </span>
                ) : (
                  <a href={t.video_url} target="_blank" rel="noreferrer" className="hist-link">
                    查看
                  </a>
                )}
                <button
                  className="hist-delete"
                  onClick={async () => {
                    const apiFn = t.kind === 'image' ? api.deleteImageTask : api.deleteVideoTask
                    await apiFn(t.id)
                    setHistory((h) => h.filter((x) => x.id !== t.id))
                    notify('已删除')
                  }}
                  title="删除此记录"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="hist-empty">暂无生成记录，开始体验图生视频、文生视频或卖点图生成</div>
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
