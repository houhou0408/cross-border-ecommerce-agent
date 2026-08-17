import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '../api.js'

// 知识库管理页：极简 B 端风格，纯文字 + 蓝色单一强调色
export default function KbPage() {
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [toast, setToast] = useState(null)
  const fileRef = useRef(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const d = await api.listKbDocs()
      setDocs(d.documents || [])
    } catch (e) {
      setDocs([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const notify = (msg) => {
    const t = Date.now()
    setToast({ msg, ts: t })
    setTimeout(() => setToast((c) => (c && c.ts === t ? null : c)), 2500)
  }

  const onUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const d = await api.uploadKbDoc(file)
      if (d.error) {
        notify('上传失败：' + d.error)
      } else {
        notify(`已入库 ${d.chunks} 条切片（${d.source}）`)
        refresh()
      }
    } catch (e) {
      notify('上传失败：' + e.message)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const onDelete = async (source) => {
    if (!confirm(`确认删除「${source}」？`)) return
    try {
      const d = await api.deleteKbDoc(source)
      if (d.error) {
        notify('删除失败：' + d.error)
      } else {
        notify(`已删除 ${d.deleted} 条切片`)
        refresh()
      }
    } catch (e) {
      notify('删除失败：' + e.message)
    }
  }

  const totalChunks = docs.reduce((s, d) => s + (d.chunks || 0), 0)

  return (
    <div className="kb-page">
      {/* 统计面板：纯文字，上下结构 */}
      <div className="kb-stats">
        <div className="kb-stat-item">
          <span className="kb-stat-num">{docs.length}</span>
          <span className="kb-stat-label">文档总数</span>
        </div>
        <div className="kb-stat-divider" />
        <div className="kb-stat-item">
          <span className="kb-stat-num">{totalChunks}</span>
          <span className="kb-stat-label">切片总数</span>
        </div>
        <div className="kb-stat-divider" />
        <div className="kb-stat-item">
          <span className="kb-stat-num kb-stat-text">BGE</span>
          <span className="kb-stat-label">嵌入模型</span>
        </div>
        <div className="kb-stat-divider" />
        <div className="kb-stat-item">
          <span className="kb-stat-num kb-stat-text">Chroma</span>
          <span className="kb-stat-label">向量数据库</span>
        </div>
      </div>

      {/* 上传区：仅虚线框 + 文字提示 */}
      <div className="kb-section">
        <h3 className="kb-title">上传文档到知识库</h3>
        <p className="kb-desc">
          支持 .md / .txt 文件。上传后自动切片 → 向量化 → 写入 Chroma 向量库，立即可被 Agent 检索。
        </p>
        <div
          className={`kb-dropzone ${uploading ? 'uploading' : ''}`}
          onClick={() => !uploading && fileRef.current?.click()}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".md,.txt,.markdown"
            onChange={onUpload}
            id="kb-file"
            style={{ display: 'none' }}
          />
          <div className="kb-drop-text">
            {uploading ? '上传中...' : '点击或拖拽文件到此上传'}
          </div>
          <div className="kb-drop-hint">.md / .txt 格式，自动切片入库</div>
        </div>
      </div>

      {/* 文档列表：纯文字，无图标 */}
      <div className="kb-section">
        <div className="kb-list-head">
          <h3 className="kb-title">知识库文档</h3>
          <span className="kb-count">共 {docs.length} 个文档 · {totalChunks} 条切片</span>
        </div>
        {loading ? (
          <div className="kb-empty"><span className="spinner" /> 加载中...</div>
        ) : docs.length === 0 ? (
          <div className="kb-empty">知识库暂无文档，上传第一个文档开始体验</div>
        ) : (
          <div className="kb-table">
            <div className="kb-row kb-head-row">
              <span>来源文件</span>
              <span>切片数</span>
              <span>操作</span>
            </div>
            {docs.map((d, i) => (
              <div className="kb-row" key={i}>
                <span className="kb-src">{d.source}</span>
                <span className="kb-chunks">{d.chunks}</span>
                <span>
                  <button className="kb-del" onClick={() => onDelete(d.source)}>
                    删除
                  </button>
                </span>
              </div>
            ))}
          </div>
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
