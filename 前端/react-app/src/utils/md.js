// 简易 Markdown 渲染（表格/标题/列表/加粗/代码/图片/视频/链接）——避免引入重量级 markdown 库
// 返回 HTML 字符串，调用方用 dangerouslySetInnerHTML 注入
export function renderMd(text) {
  if (!text) return ''
  let s = String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // 媒体占位符：先提取图片/视频为占位符，避免被后续正则破坏，最后还原
  const media = []
  const stash = (html) => { media.push(html); return `\u0000M${media.length - 1}\u0000` }
  const isVideo = (u) => /\/videos\/|\.(mp4|webm|mov)(\?|$)/i.test(u)
  const isImage = (u) => /\/images\/|\.(png|jpe?g|gif|webp|svg)(\?|$)/i.test(u)
  const toMedia = (url, alt = '') => {
    const dlBtn = `<a class="md-dl-btn" href="${url}" download title="下载文件">下载</a>`
    if (isVideo(url)) {
      return stash(`<div class="md-media-wrap"><video src="${url}" controls class="md-video"></video>${dlBtn}</div>`)
    }
    return stash(`<div class="md-media-wrap"><img src="${url}" alt="${alt}" class="md-image" />${dlBtn}</div>`)
  }

  // 1. markdown 图片 ![alt](url)
  s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (m, alt, url) => toMedia(url, alt))

  // 2. markdown 链接 [text](url)：图片/视频内嵌展示，其余渲染为超链接
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, label, url) => {
    if (isImage(url) || isVideo(url)) return toMedia(url, label)
    return `<a href="${url}" target="_blank" rel="noopener">${label}</a>`
  })

  // 3. 纯 URL（/images/xxx.png 或 /videos/xxx.mp4，需带扩展名；前面不能是 = 引号 / 字母，避免破坏属性）
  s = s.replace(/(^|[^"'=\/\w])(\/(?:images|videos)\/[A-Za-z0-9._-]+\.(?:png|jpe?g|gif|webp|svg|mp4|webm|mov))/gi,
    (m, pre, url) => pre + toMedia(url))

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

  // 还原媒体占位符
  s = s.replace(/\u0000M(\d+)\u0000/g, (m, i) => media[Number(i)])
  return s
}
