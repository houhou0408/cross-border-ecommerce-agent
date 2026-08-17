import { useEffect } from 'react'

// 图片/视频灯箱：点击对话里的媒体放大查看，支持下载与 ESC/点遮罩关闭
export default function Lightbox({ src, type, onClose }) {
  // ESC 关闭
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!src) return null
  const isVideo = type === 'video' || /\.(mp4|webm|mov)(\?|$)/i.test(src)
  // 从 URL 提取文件名作为下载名
  const filename = src.split('/').pop() || (isVideo ? 'video.mp4' : 'image.png')

  return (
    <div className="lightbox" onClick={onClose}>
      <div className="lightbox-bar" onClick={(e) => e.stopPropagation()}>
        <span className="lightbox-name">{filename}</span>
        <a
          className="lightbox-download"
          href={src}
          download={filename}
          onClick={(e) => e.stopPropagation()}
        >
          ⬇ 下载
        </a>
        <button className="lightbox-close" onClick={onClose} title="关闭 (Esc)">✕</button>
      </div>
      <div className="lightbox-stage" onClick={onClose}>
        {isVideo ? (
          <video
            src={src}
            controls
            autoPlay
            className="lightbox-video"
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <img
            src={src}
            alt={filename}
            className="lightbox-image"
            onClick={(e) => e.stopPropagation()}
          />
        )}
      </div>
    </div>
  )
}
