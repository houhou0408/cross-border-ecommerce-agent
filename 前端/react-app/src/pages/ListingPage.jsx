import { useState } from 'react'
import { api } from '../api.js'
import { renderMd } from '../utils/md.js'

// Listing 生成页：表单 + 结果展示
export default function ListingPage({ onDataChanged }) {
  const [form, setForm] = useState({ product: '', platform: 'amazon', language: 'zh', features: '' })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState('')
  const [error, setError] = useState('')

  const onSubmit = async () => {
    if (!form.product.trim()) {
      setError('请输入产品名称')
      return
    }
    setError('')
    setLoading(true)
    setResult('')
    try {
      const d = await api.listing(form)
      setResult(d.listing || d.error || '(空)')
      onDataChanged()
    } catch (e) {
      setError('请求失败：' + e.message)
    } finally {
      setLoading(false)
    }
  }

  const presets = [
    { label: '蓝牙音箱', product: '便携式蓝牙音箱', features: 'IPX7防水, 20小时续航, 重低音' },
    { label: 'LED台灯', product: '智能LED台灯', features: '无极调光, 触控, USB供电' },
    { label: '瑜伽垫', product: 'TPE瑜伽垫', features: '防滑, 6mm加厚, 环保材质' }
  ]

  return (
    <div className="form-page">
      <div className="form-card">
        <h3>生成参数</h3>
        <div className="quick-presets">
          {presets.map((p) => (
            <button
              key={p.label}
              className="preset-chip"
              onClick={() => setForm({ ...form, product: p.product, features: p.features })}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="field">
          <label>产品名称</label>
          <input
            value={form.product}
            onChange={(e) => setForm({ ...form, product: e.target.value })}
            placeholder="如 蓝牙音箱"
          />
        </div>
        <div className="row">
          <div className="field">
            <label>平台</label>
            <select value={form.platform} onChange={(e) => setForm({ ...form, platform: e.target.value })}>
              <option value="amazon">Amazon</option>
              <option value="shopee">Shopee</option>
              <option value="temu">Temu</option>
            </select>
          </div>
          <div className="field">
            <label>语言</label>
            <select value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
              <option value="zh">中文</option>
              <option value="en">English</option>
            </select>
          </div>
        </div>
        <div className="field">
          <label>产品卖点（可选）</label>
          <input
            value={form.features}
            onChange={(e) => setForm({ ...form, features: e.target.value })}
            placeholder="如 IPX7防水, 续航20小时"
          />
        </div>
        {error && <div className="err-tip">{error}</div>}
        <button className="btn primary" onClick={onSubmit} disabled={loading}>
          {loading ? '生成中…' : '✨ 生成 Listing'}
        </button>
      </div>

      <div className="result-card">
        <h3>生成结果</h3>
        {loading ? (
          <div className="placeholder">
            <span className="spinner" /> 正在调用 Agent 生成…
          </div>
        ) : result ? (
          <div className="result-text" dangerouslySetInnerHTML={{ __html: renderMd(result) }} />
        ) : (
          <div className="result-empty">
            <div className="result-empty-icon">📝</div>
            <div className="result-empty-text">填写参数后点击「生成 Listing」</div>
            <div className="result-empty-hint">Agent 将根据产品信息生成标题、五点描述、关键词</div>
          </div>
        )}
      </div>
    </div>
  )
}
