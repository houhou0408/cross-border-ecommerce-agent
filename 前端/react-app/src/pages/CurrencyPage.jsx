import { useState } from 'react'
import { api } from '../api'
import { renderMd } from '../utils/md.js'
import { IconCurrency } from '../components/Icons.jsx'

// 汇率换算页：表单 + 结果
export default function CurrencyPage({ onDataChanged }) {
  const [form, setForm] = useState({ amount: 500, from: 'USD', to: 'CNY' })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState('')
  const [error, setError] = useState('')

  const onSubmit = async () => {
    setError('')
    setLoading(true)
    setResult('')
    try {
      const d = await api.currency({
        amount: Number(form.amount),
        from_currency: form.from.toUpperCase(),
        to_currency: form.to.toUpperCase()
      })
      setResult(d.result || d.error || '(空)')
      onDataChanged()
    } catch (e) {
      setError('请求失败：' + e.message)
    } finally {
      setLoading(false)
    }
  }

  const presets = [
    { label: 'USD → CNY', from: 'USD', to: 'CNY', amount: 100 },
    { label: 'EUR → CNY', from: 'EUR', to: 'CNY', amount: 100 },
    { label: 'JPY → CNY', from: 'JPY', to: 'CNY', amount: 10000 }
  ]

  return (
    <div className="form-page">
      <div className="form-card">
        <div className="form-head">
          <h3>换算参数</h3>
          <button
            className="link-btn"
            onClick={() => { setForm({ amount: 500, from: 'USD', to: 'CNY' }); setError('') }}
          >
            重置
          </button>
        </div>
        <div className="quick-presets">
          {presets.map((p) => (
            <button
              key={p.label}
              className="preset-chip"
              onClick={() => setForm({ ...form, from: p.from, to: p.to, amount: p.amount })}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="field">
          <label>金额</label>
          <input
            type="number"
            value={form.amount}
            onChange={(e) => setForm({ ...form, amount: e.target.value })}
          />
        </div>
        <div className="row">
          <div className="field">
            <label>源币种</label>
            <input value={form.from} onChange={(e) => setForm({ ...form, from: e.target.value })} />
          </div>
          <div className="field">
            <label>目标币种</label>
            <input value={form.to} onChange={(e) => setForm({ ...form, to: e.target.value })} />
          </div>
        </div>
        {error && <div className="err-tip">{error}</div>}
        <button className="btn primary" onClick={onSubmit} disabled={loading}>
          {loading ? '换算中…' : '换算'}
        </button>
      </div>

      <div className="result-card">
        <h3>换算结果</h3>
        {loading ? (
          <div className="placeholder">
            <span className="spinner" /> 正在换算…
          </div>
        ) : result ? (
          <div className="result-text" dangerouslySetInnerHTML={{ __html: renderMd(result) }} />
        ) : (
          <div className="result-empty">
            <div className="result-empty-icon"><IconCurrency size={28} /></div>
            <div className="result-empty-text">填写参数后点击「换算」</div>
            <div className="result-empty-hint">支持 USD / EUR / JPY / CNY 等多币种实时汇率</div>
          </div>
        )}
      </div>
    </div>
  )
}
