import { useState } from 'react'
import { api } from '../api'
import { renderMd } from '../utils/md.js'
import { IconTariff } from '../components/Icons.jsx'

// 关税查询页：表单 + 结果
export default function TariffPage({ onDataChanged }) {
  const [form, setForm] = useState({ country: '美国', category: '电子产品', value: 500, freight: 0 })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState('')
  const [error, setError] = useState('')

  const onSubmit = async () => {
    if (!form.country.trim() || !form.category.trim()) {
      setError('请填写目的国与商品类别')
      return
    }
    setError('')
    setLoading(true)
    setResult('')
    try {
      const d = await api.tariff({ ...form, insurance: 0 })
      setResult(d.result || d.error || '(空)')
      onDataChanged()
    } catch (e) {
      setError('请求失败：' + e.message)
    } finally {
      setLoading(false)
    }
  }

  const presets = [
    { label: '美国·电子', country: '美国', category: '电子产品', value: 500, freight: 50 },
    { label: '欧盟·服装', country: '德国', category: '服装', value: 300, freight: 40 },
    { label: '日本·家居', country: '日本', category: '家居用品', value: 200, freight: 30 }
  ]

  return (
    <div className="form-page">
      <div className="form-card">
        <div className="form-head">
          <h3>查询参数</h3>
          <button
            className="link-btn"
            onClick={() => { setForm({ country: '美国', category: '电子产品', value: 500, freight: 0 }); setError('') }}
          >
            重置
          </button>
        </div>
        <div className="quick-presets">
          {presets.map((p) => (
            <button
              key={p.label}
              className="preset-chip"
              onClick={() => setForm({ ...form, country: p.country, category: p.category, value: p.value, freight: p.freight })}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="row">
          <div className="field required">
            <label>目的国</label>
            <input value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })} />
          </div>
          <div className="field required">
            <label>商品类别</label>
            <input
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}
            />
          </div>
        </div>
        <div className="row">
          <div className="field">
            <label>货值 (USD)</label>
            <input
              type="number"
              value={form.value}
              onChange={(e) => setForm({ ...form, value: Number(e.target.value) })}
            />
          </div>
          <div className="field">
            <label>运费 (USD)</label>
            <input
              type="number"
              value={form.freight}
              onChange={(e) => setForm({ ...form, freight: Number(e.target.value) })}
            />
          </div>
        </div>
        {error && <div className="err-tip">{error}</div>}
        <button className="btn primary" onClick={onSubmit} disabled={loading}>
          {loading ? '查询中…' : '查询关税'}
        </button>
      </div>

      <div className="result-card">
        <h3>查询结果</h3>
        {loading ? (
          <div className="placeholder">
            <span className="spinner" /> 正在查询…
          </div>
        ) : result ? (
          <div className="result-text" dangerouslySetInnerHTML={{ __html: renderMd(result) }} />
        ) : (
          <div className="result-empty">
            <div className="result-empty-icon"><IconTariff size={28} /></div>
            <div className="result-empty-text">填写参数后点击「查询关税」</div>
            <div className="result-empty-hint">将计算关税税率、完税价格、综合税费与预估到岸成本</div>
          </div>
        )}
      </div>
    </div>
  )
}
