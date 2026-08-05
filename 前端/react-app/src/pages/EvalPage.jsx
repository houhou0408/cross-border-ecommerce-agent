import { useState, useEffect, useCallback } from 'react'
import { api } from '../api.js'

// Agent 效果评估页：测试集展示 + 批量评估执行
export default function EvalPage() {
  const [testset, setTestset] = useState([])
  const [running, setRunning] = useState(false)
  const [report, setReport] = useState(null)
  const [progress, setProgress] = useState('')

  const loadTestset = useCallback(async () => {
    try {
      const d = await api.getTestset()
      setTestset(d.testset || [])
    } catch {
      /* 静默 */
    }
  }, [])

  useEffect(() => {
    loadTestset()
  }, [loadTestset])

  const onRun = async () => {
    setRunning(true)
    setReport(null)
    setProgress('开始批量评估（共 ' + testset.length + ' 条，预计 1-3 分钟）...')
    try {
      const d = await api.runEval()
      setReport(d)
      setProgress('评估完成')
    } catch (e) {
      setProgress('评估失败：' + e.message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="eval-page">
      <div className="eval-overview">
        <div className="eval-ov-head">
          <h3>Agent 效果评估</h3>
          <button className="btn primary" onClick={onRun} disabled={running || testset.length === 0}>
            {running ? '评估中...' : '▶ 运行批量评估'}
          </button>
        </div>
        <p className="form-hint">
          基于标准测试集，评估 Agent 的工具调用成功率、答案准确率、幻觉率三大指标。
          {progress && <span className="eval-progress"> · {progress}</span>}
        </p>

        {report && (
          <>
            <div className="eval-metrics">
              <div className="metric-card">
                <div className="metric-label">工具调用成功率</div>
                <div className="metric-value green">
                  {(report.tool_success_rate * 100).toFixed(1)}%
                </div>
                <div className="metric-sub">
                  {report.tool_pass_count}/{report.total}
                </div>
              </div>
              <div className="metric-card">
                <div className="metric-label">答案准确率</div>
                <div className="metric-value indigo">
                  {(report.answer_accuracy_rate * 100).toFixed(1)}%
                </div>
                <div className="metric-sub">
                  {report.answer_pass_count}/{report.total}
                </div>
              </div>
              <div className="metric-card">
                <div className="metric-label">幻觉率</div>
                <div className="metric-value amber">
                  {(report.hallucination_rate * 100).toFixed(1)}%
                </div>
                <div className="metric-sub">
                  {report.hallucination_count}/{report.total}
                </div>
              </div>
              <div className="metric-card">
                <div className="metric-label">平均耗时</div>
                <div className="metric-value">{report.avg_latency_ms}ms</div>
                <div className="metric-sub">单次调用</div>
              </div>
            </div>

            {/* 分类统计 */}
            <div className="eval-cat">
              <h4>分类统计</h4>
              <div className="cat-list">
                {Object.entries(report.by_category).map(([cat, v]) => (
                  <div className="cat-item" key={cat}>
                    <span className="cat-name">{cat}</span>
                    <span className="cat-bar">
                      <span
                        className="cat-bar-fill"
                        style={{ width: (v.tool_pass / v.total) * 100 + '%' }}
                      />
                    </span>
                    <span className="cat-rate">
                      工具 {v.tool_pass}/{v.total} · 答案 {v.answer_pass}/{v.total}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>

      {/* 测试集列表 */}
      <div className="eval-testset">
        <h3>测试集（{testset.length} 条）</h3>
        {report ? (
          <div className="ts-table">
            <div className="ts-row ts-head">
              <span>ID</span>
              <span>类别</span>
              <span>测试问题</span>
              <span>工具</span>
              <span>答案</span>
              <span>幻觉</span>
            </div>
            {report.details.map((d) => (
              <div className="ts-row" key={d.test_id}>
                <span className="ts-id">{d.test_id}</span>
                <span className="ts-cat">{d.category}</span>
                <span className="ts-q" title={d.query}>{d.query.slice(0, 24)}...</span>
                <span className={`ts-pass ${d.tool_pass ? 'ok' : 'fail'}`}>
                  {d.tool_pass ? '✓' : '✗'} {d.tools_used.join(',') || '-'}
                </span>
                <span className={`ts-pass ${d.answer_pass ? 'ok' : 'fail'}`}>
                  {d.answer_pass ? '✓' : '✗'} {d.keyword_hits}/{d.keyword_total}
                </span>
                <span className={`ts-pass ${d.grounded ? 'ok' : 'warn'}`}>
                  {d.grounded ? '通过' : '拦截'}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="ts-preview">
            {testset.map((t) => (
              <div className="ts-prev-item" key={t.id}>
                <span className="ts-id">{t.id}</span>
                <span className="ts-cat">{t.category}</span>
                <span className="ts-q">{t.query}</span>
                <span className="ts-tools">期望: {t.expected_tools.join(', ') || '无(超纲)'}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
