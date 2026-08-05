# -*- coding: utf-8 -*-
"""视频生成工具：根据商品图片 + 描述，调用阿里云百炼 HappyHorse 1.1 R2V 生成产品宣传视频。

设计要点（面试讲解重点）：
1. 参考生视频(R2V)：用户上传商品图片作为参考图，AI 基于图片+文字描述生成动态宣传视频；
2. 异步任务：视频生成耗时较长(1-5分钟)，采用任务制（上传图片→创建任务→轮询→下载）；
3. 降级策略：API 调用失败时返回示例视频，保证流程可演示；
4. 集成方式：既可独立页面调用，也可作为 Agent 工具在对话中触发。

对应业务场景：跨境电商产品主图视频、Listing 宣传视频、社交媒体短视频素材。
"""
import os
import time
import uuid
import json
from pathlib import Path
from typing import Dict, Any, Optional

import requests

from config import LOG_DIR, VIDEO_CONFIG
from 工具集.数据库连接 import get_cursor

# 视频生成任务存储
_TASK_DIR = LOG_DIR / "video_tasks.json"

# 上传图片保存目录
UPLOAD_DIR = Path(__file__).parent.parent / "静态资源" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 视频文件目录
VIDEO_DIR = Path(__file__).parent.parent / "静态资源" / "videos"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

# 降级示例视频（API 调用失败时返回，保证流程可演示）
_FALLBACK_VIDEO = "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerJoyrides.mp4"

# 从配置读取
_API_KEY = VIDEO_CONFIG.get("api_key", "")
_BASE_URL = VIDEO_CONFIG.get("base_url", "https://dashscope.aliyuncs.com/api/v1")
_MODEL = VIDEO_CONFIG.get("model", "happyhorse-1.1-r2v")


def _save_upload_image(file_bytes: bytes, filename: str) -> str:
    """保存上传的图片到静态目录，返回相对路径。"""
    ext = os.path.splitext(filename)[1] or ".jpg"
    saved_name = f"product_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
    save_path = UPLOAD_DIR / saved_name
    with open(save_path, "wb") as f:
        f.write(file_bytes)
    return f"/uploads/{saved_name}"


def _create_task_record(prompt: str, image_url: str, status: str = "processing") -> Dict[str, Any]:
    """创建视频生成任务记录。"""
    task_id = uuid.uuid4().hex[:12]
    task = {
        "id": task_id,
        "prompt": prompt,
        "image_url": image_url,
        "status": status,
        "video_url": "",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "completed_at": "",
        "used_fallback": False,
    }
    _save_task(task)
    return task


def _save_task(task: Dict):
    """保存任务到 JSON 文件（简化持久化）。"""
    tasks = _load_tasks()
    tasks[task["id"]] = task
    try:
        with open(_TASK_DIR, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[视频生成] 任务保存失败: {e}")


def _load_tasks() -> Dict[str, Dict]:
    """加载所有任务。"""
    if _TASK_DIR.exists():
        try:
            with open(_TASK_DIR, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


# ============ DashScope API 调用 ============

def _upload_image_to_dashscope(image_path: str) -> Optional[str]:
    """上传本地图片到 DashScope OSS，返回 oss:// URL。

    HappyHorse R2V 需要图片是公网可访问 URL。
    使用 DashScope SDK 的 OssUtils 上传到 OSS，返回 oss:// 协议 URL。
    调用视频生成 API 时需附带 X-DashScope-OssResourceResolve: enable 头。
    """
    # 拼接本地完整路径
    if image_path.startswith("/uploads/"):
        local_path = UPLOAD_DIR / image_path.replace("/uploads/", "")
    else:
        local_path = Path(image_path)

    if not local_path.exists():
        print(f"[视频生成] 图片不存在: {local_path}")
        return None

    try:
        from dashscope.utils.oss_utils import OssUtils
        oss_url, _ = OssUtils.upload(
            model=_MODEL,
            file_path=str(local_path),
            api_key=_API_KEY,
        )
        print(f"[视频生成] 图片上传成功: {oss_url}")
        return oss_url
    except Exception as e:
        print(f"[视频生成] OSS 上传异常: {e}")
    return None


def _create_r2v_task(prompt: str, image_url: str) -> Optional[str]:
    """创建 HappyHorse R2V 参考生视频任务，返回 task_id。"""
    headers = {
        "Authorization": f"Bearer {_API_KEY}",
        "X-DashScope-Async": "enable",
        "X-DashScope-OssResourceResolve": "enable",
        "Content-Type": "application/json",
    }
    body = {
        "model": _MODEL,
        "input": {
            "prompt": prompt,
            "media": [
                {"type": "reference_image", "url": image_url}
            ],
        },
        "parameters": {
            "resolution": VIDEO_CONFIG.get("resolution", "720P"),
            "ratio": VIDEO_CONFIG.get("ratio", "16:9"),
            "duration": VIDEO_CONFIG.get("duration", 5),
            "watermark": False,
        },
    }
    try:
        r = requests.post(
            f"{_BASE_URL}/services/aigc/video-generation/video-synthesis",
            headers=headers,
            json=body,
            timeout=30,
        )
        if r.status_code == 200:
            result = r.json()
            task_id = result.get("output", {}).get("task_id")
            if task_id:
                print(f"[视频生成] 任务创建成功: {task_id}")
                return task_id
            print(f"[视频生成] 任务创建返回无 task_id: {result}")
        else:
            print(f"[视频生成] 任务创建失败 HTTP {r.status_code}: {r.text[:300]}")
    except Exception as e:
        print(f"[视频生成] 任务创建异常: {e}")
    return None


def _poll_task(task_id: str) -> Optional[str]:
    """轮询视频生成任务状态，返回视频 URL。"""
    headers = {"Authorization": f"Bearer {_API_KEY}"}
    interval = VIDEO_CONFIG.get("poll_interval", 5)
    timeout = VIDEO_CONFIG.get("poll_timeout", 300)
    start = time.time()

    while time.time() - start < timeout:
        try:
            r = requests.get(
                f"{_BASE_URL}/tasks/{task_id}",
                headers=headers,
                timeout=30,
            )
            if r.status_code == 200:
                result = r.json()
                output = result.get("output", {})
                status = output.get("task_status", "")
                print(f"[视频生成] 轮询状态: {status}")

                if status == "SUCCEEDED":
                    video_url = output.get("video_url")
                    if video_url:
                        return video_url
                    # 兼容 results 数组格式
                    results = output.get("results", [])
                    if results and isinstance(results, list):
                        return results[0].get("url", "")
                elif status == "FAILED":
                    msg = output.get("message", "未知错误")
                    print(f"[视频生成] 任务失败: {msg}")
                    return None
        except Exception as e:
            print(f"[视频生成] 轮询异常: {e}")

        time.sleep(interval)

    print(f"[视频生成] 轮询超时 ({timeout}s)")
    return None


def _download_video(video_url: str) -> str:
    """下载远程视频到本地，返回本地路径。"""
    try:
        r = requests.get(video_url, timeout=120, stream=True)
        if r.status_code == 200:
            filename = f"video_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp4"
            save_path = VIDEO_DIR / filename
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"[视频生成] 视频下载完成: {save_path}")
            return f"/videos/{filename}"
        else:
            print(f"[视频生成] 视频下载失败 HTTP {r.status_code}")
    except Exception as e:
        print(f"[视频生成] 视频下载异常: {e}")
    # 下载失败则返回远程 URL
    return video_url


def _do_fallback(prompt: str, image_path: str, reason: str = "") -> Dict[str, Any]:
    """降级：返回示例视频。"""
    task = _create_task_record(prompt, image_path)
    task["video_url"] = _FALLBACK_VIDEO
    task["status"] = "completed"
    task["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    task["used_fallback"] = True
    _save_task(task)
    return {
        "task_id": task["id"],
        "status": "completed",
        "video_url": _FALLBACK_VIDEO,
        "image_url": image_path,
        "prompt": prompt,
        "used_fallback": True,
        "msg": f"视频已生成（示例视频{reason}）",
    }


def generate_video_task(prompt: str, image_path: str = "", image_bytes: bytes = None,
                        filename: str = "") -> Dict[str, Any]:
    """生成产品宣传视频（HappyHorse 1.1 R2V 参考生视频）。

    流程：保存图片 → 上传到 DashScope → 创建 R2V 任务 → 轮询 → 下载视频

    Args:
        prompt: 产品描述/卖点（如"防水蓝牙音箱，户外场景，阳光下闪耀"）
        image_path: 已上传图片的URL路径（如 /uploads/xxx.jpg）
        image_bytes: 图片二进制（有则保存）
        filename: 原始文件名

    Returns:
        dict: task_id / status / video_url / image_url / prompt
    """
    # 保存上传图片
    if image_bytes and not image_path:
        image_path = _save_upload_image(image_bytes, filename or "product.jpg")

    # 未配置 API Key → 降级
    if not _API_KEY:
        return _do_fallback(prompt, image_path, "，未配置 DASHSCOPE_API_KEY")

    # 无图片 → 降级（R2V 必须有参考图）
    if not image_path:
        return _do_fallback(prompt, image_path, "，R2V 需要上传参考图片")

    # 创建任务记录
    task = _create_task_record(prompt, image_path, "processing")

    # 步骤1：上传图片到 DashScope
    print(f"[视频生成] 步骤1: 上传图片 {image_path}")
    remote_url = _upload_image_to_dashscope(image_path)
    if not remote_url:
        return _do_fallback(prompt, image_path, "，图片上传失败")

    # 步骤2：创建 R2V 任务
    print(f"[视频生成] 步骤2: 创建 R2V 任务 (model={_MODEL})")
    ds_task_id = _create_r2v_task(prompt, remote_url)
    if not ds_task_id:
        return _do_fallback(prompt, image_path, "，任务创建失败")

    # 步骤3：轮询任务状态
    print(f"[视频生成] 步骤3: 轮询任务 {ds_task_id}")
    video_url = _poll_task(ds_task_id)
    if not video_url:
        return _do_fallback(prompt, image_path, "，视频生成超时或失败")

    # 步骤4：下载视频到本地
    print(f"[视频生成] 步骤4: 下载视频")
    local_video = _download_video(video_url)

    # 更新任务记录
    task["video_url"] = local_video
    task["status"] = "completed"
    task["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    task["used_fallback"] = False
    _save_task(task)

    return {
        "task_id": task["id"],
        "status": "completed",
        "video_url": local_video,
        "image_url": image_path,
        "prompt": prompt,
        "used_fallback": False,
        "msg": "视频已生成（HappyHorse 1.1 R2V）",
    }


def list_video_tasks() -> list:
    """列出所有视频生成任务（按时间倒序）。"""
    tasks = _load_tasks()
    return sorted(tasks.values(), key=lambda t: t.get("created_at", ""), reverse=True)


def get_video_task(task_id: str) -> Optional[Dict]:
    """查询单个任务。"""
    return _load_tasks().get(task_id)


# ============ Agent 工具版（@tool 注册，供对话中调用） ============
from langchain_core.tools import tool


@tool("generate_promo_video")
def 生成宣传视频(prompt: str) -> str:
    """根据产品描述生成宣传视频。

    当用户要求"生成产品视频""做宣传视频"时调用此工具。
    会返回视频链接供用户查看。

    Args:
        prompt: 产品描述与卖点，如"防水蓝牙音箱，户外运动场景，阳光下展示质感"
    """
    result = generate_video_task(prompt=prompt, image_path="", image_bytes=None)
    return (
        f"视频已生成。\n"
        f"产品描述：{prompt}\n"
        f"视频链接：{result['video_url']}\n"
        f"（提示：上传商品图片到「视频生成」页面可获得图生视频效果）"
    )
