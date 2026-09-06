# -*- coding: utf-8 -*-
"""文件安全助手：上传图片校验与图片路径约束（防路径穿越 / 任意文件读取）。

安全背景（整改项）：
1. image_path 由客户端提供，若直接 Path(image_path) 读取，攻击者可构造
   "C:/.../.env" 之类的路径读取本机任意文件，并随视觉/视频 API 请求外传；
   因此业务侧图片路径一律收口到本模块，强制限定在 UPLOAD_DIR 内；
2. 上传文件若不校验扩展名与内容，.html/.svg 可落入公开静态目录形成存储型 XSS，
   超大文件可打满磁盘；因此上传统一做 白名单 + 魔数 + 大小上限 三重校验。

约定：业务侧引用图片路径只用 /uploads/<文件名> 形式（HTTP 可访问路径）。
"""
import os
import time
import uuid
from pathlib import Path
from typing import Optional, Tuple

# 上传图片保存目录（静态挂载目录；与各业务模块的 UPLOAD_DIR 同源）
UPLOAD_DIR = Path(__file__).parent.parent / "静态资源" / "uploads"

# 上传限制：单图 10MB；扩展名白名单
MAX_IMAGE_BYTES = 10 * 1024 * 1024
_ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# 图片文件头魔数（JPEG / PNG / WEBP）
_IMAGE_MAGIC = (
    (b"\xff\xd8\xff", False),           # JPEG
    (b"\x89PNG\r\n\x1a\n", False),      # PNG
    (b"RIFF", True),                    # WEBP：RIFF....WEBP（需再核对 8-12 字节）
)


def safe_resolve_upload_path(image_path: str) -> Optional[Path]:
    """把客户端提供的图片路径解析为 UPLOAD_DIR 内的安全路径。

    仅接受两种形式："/uploads/<文件名>" 或裸文件名 "<文件名>"；
    其余一律拒绝（绝对路径、带目录分隔/.. 的路径），且解析结果
    resolve() 后必须仍位于 UPLOAD_DIR 内（防穿越）。

    Returns:
        安全路径；路径不合法返回 None（存在性检查交给调用方）。
    """
    if not image_path or not isinstance(image_path, str):
        return None
    image_path = image_path.strip()
    if image_path.startswith("/uploads/"):
        rel = image_path[len("/uploads/"):]
    elif image_path.startswith("uploads/"):
        rel = image_path[len("uploads/"):]
    else:
        # 只接受裸文件名：出现目录分隔/绝对路径/.. 即拒绝
        if (
            os.path.isabs(image_path)
            or "/" in image_path
            or "\\" in image_path
            or ".." in image_path
        ):
            return None
        rel = image_path
    if not rel or "\\" in rel or ".." in rel or rel.startswith("/"):
        return None
    try:
        resolved = (UPLOAD_DIR / rel).resolve()
        resolved.relative_to(UPLOAD_DIR.resolve())
    except (ValueError, OSError):
        return None
    return resolved


def read_upload_image(image_path: str) -> Optional[bytes]:
    """安全读取 uploads 目录内的图片字节；路径不合法或文件不存在返回 None。"""
    p = safe_resolve_upload_path(image_path)
    if p is None or not p.is_file():
        return None
    try:
        with open(p, "rb") as f:
            return f.read()
    except OSError:
        return None


def validate_image_upload(data: bytes, filename: str) -> Tuple[bool, str]:
    """校验上传图片：大小上限 + 扩展名白名单 + 文件头魔数。

    Returns:
        (是否通过, 错误信息)；通过时错误信息为空串。
    """
    if not data:
        return False, "图片内容为空"
    if len(data) > MAX_IMAGE_BYTES:
        return False, "图片超过大小限制（10MB）"
    # 无扩展名默认按 jpg 处理（保持旧行为宽容度），真实性由下方魔数校验保证
    ext = os.path.splitext(filename or "")[1].lower() or ".jpg"
    if ext not in _ALLOWED_EXTS:
        return False, "仅支持 jpg/jpeg/png/webp 格式图片"
    for magic, need_webp_check in _IMAGE_MAGIC:
        if data.startswith(magic):
            if need_webp_check and (len(data) < 12 or data[8:12] != b"WEBP"):
                continue
            return True, ""
    return False, "文件内容不是有效图片"


def save_upload_image(data: bytes, filename: str, upload_dir: Optional[Path] = None) -> str:
    """校验并保存上传图片到 uploads 目录，返回 /uploads/<文件名> 相对路径。

    校验不通过抛 ValueError（HTTP 层捕获后转业务错误响应）。
    upload_dir 供调用方注入自定义目录（测试隔离用），默认用本模块 UPLOAD_DIR。
    """
    ok, err = validate_image_upload(data, filename)
    if not ok:
        raise ValueError(err)
    base = Path(upload_dir) if upload_dir else UPLOAD_DIR
    ext = os.path.splitext(filename or "")[1].lower() or ".jpg"
    saved_name = f"product_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
    base.mkdir(parents=True, exist_ok=True)
    with open(base / saved_name, "wb") as f:
        f.write(data)
    return f"/uploads/{saved_name}"
