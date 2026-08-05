// 简易 Markdown 渲染（表格/标题/列表/加粗/代码）——避免引入重量级 markdown 库
// 返回 HTML 字符串，调用方用 dangerouslySetInnerHTML 注入
export function renderMd(text) {
  if (!text) return ''
  let s = String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // 表格（GFM 风格）
  s = s.replace(/^\|(.+)\|\n\|([-:\s|]+)\|\n((?:\|.+\|\n?)+)/gm, (m, head, sep, body) => {
    const cols = head.split('|').map((c) => c.trim())
    const rows = body
      .trim()
      .split('\n')
      .map((r) => r.replace(/^\||\|$/g, '').split('|').map((c) => c.trim()))
    let html =
      '<table><thead><tr>' + cols.map((c) => '<th>' + c + '</th>').join('') + '</tr></thead><tbody>'
    rows.forEach((r) => {
      html += '<tr>' + r.map((c) => '<td>' + c + '</td>').join('') + '</tr>'
    })
    return html + '</tbody></table>'
  })

  s = s.replace(/^### (.+)$/gm, '<h3>$1</h3>')
  s = s.replace(/^## (.+)$/gm, '<h2>$1</h2>')
  s = s.replace(/^# (.+)$/gm, '<h1>$1</h1>')
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>')
  s = s.replace(/^[-•] (.+)$/gm, '<li>$1</li>')
  s = s.replace(/(<li>[\s\S]+?<\/li>)/g, '<ul>$1</ul>').replace(/<\/ul>\s*<ul>/g, '')
  s = s.replace(/\n{2,}/g, '<br>')
  return s
}
