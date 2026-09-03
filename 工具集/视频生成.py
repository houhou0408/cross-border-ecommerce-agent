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

from config import LOG_DIR, VIDEO_CONFIG, VIDEO_T2V_CONFIG
from 工具集.数据库连接 import get_cursor
from 模块.日志统计 import get_file_logger
logger = get_file_logger("视频生成")

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
_MODEL = VIDEO_CONFIG.get("model", "happyhorse-i2v")


def _save_upload_image(file_bytes: bytes, filename: str) -> str:
    """保存上传的图片到静态目录，返回相对路径。"""
    ext = os.path.splitext(filename)[1] or ".jpg"
    saved_name = f"product_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
    save_path = UPLOAD_DIR / saved_name
    with open(save_path, "wb") as f:
        f.write(file_bytes)
    return f"/uploads/{saved_name}"


def _create_task_record(prompt: str, image_url: str, status: str = "processing") -> Dict[str, Any]:
    """创建视频生成任务记录（自动从请求上下文取当前用户，做数据归属）。"""
    from 工具集.用户认证 import get_current_user_ctx
    user = get_current_user_ctx() or {}
    task_id = uuid.uuid4().hex[:12]
    task = {
        "id": task_id,
        "user_id": user.get("id"),
        "username": user.get("username", ""),
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


# ============ 任务持久化：MySQL 优先，JSON 文件降级 ============

_TABLES_ENSURED = False


def _ensure_tables():
    """懒建 video_task 表（首次写任务时执行一次；建表失败静默走 JSON 降级）。"""
    global _TABLES_ENSURED
    if _TABLES_ENSURED:
        return
    with get_cursor() as cur:
        if cur is not None:
            try:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS video_task (
                        id VARCHAR(12) PRIMARY KEY,
                        user_id VARCHAR(32) NULL,
                        username VARCHAR(100),
                        prompt TEXT,
                        image_url VARCHAR(500),
                        mode VARCHAR(10),
                        status VARCHAR(20),
                        video_url VARCHAR(1000),
                        used_fallback TINYINT,
                        created_at VARCHAR(32),
                        completed_at VARCHAR(32),
                        INDEX idx_video_user (user_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("[视频生成] 建表失败，任务将走 JSON 降级: %s", e)
    _TABLES_ENSURED = True


def _row_to_task(row: Dict) -> Dict:
    """DB 行 → 任务 dict。"""
    return {
        "id": row["id"],
        "user_id": row.get("user_id"),
        "username": row.get("username", ""),
        "prompt": row.get("prompt", ""),
        "image_url": row.get("image_url", ""),
        "mode": row.get("mode", ""),
        "status": row.get("status", ""),
        "video_url": row.get("video_url", ""),
        "used_fallback": bool(row.get("used_fallback", 0)),
        "created_at": str(row.get("created_at", "")),
        "completed_at": str(row.get("completed_at", "")),
    }


def _task_to_row(task: Dict) -> tuple:
    """任务 dict → DB 行（列序与 INSERT 语句一致）。"""
    return (
        task["id"], task.get("user_id"), task.get("username", ""),
        task.get("prompt", ""), task.get("image_url", ""), task.get("mode", ""),
        task.get("status", ""), task.get("video_url", ""),
        1 if task.get("used_fallback") else 0,
        task.get("created_at", ""), task.get("completed_at", ""),
    )


def _save_task(task: Dict):
    """保存任务：MySQL upsert 优先，无库/失败时降级 JSON 文件。"""
    _ensure_tables()
    with get_cursor() as cur:
        if cur is not None:
            try:
                cur.execute(
                    "INSERT INTO video_task (id, user_id, username, prompt, image_url, mode, "
                    "status, video_url, used_fallback, created_at, completed_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE status=VALUES(status), video_url=VALUES(video_url), "
                    "used_fallback=VALUES(used_fallback), completed_at=VALUES(completed_at)",
                    _task_to_row(task),
                )
                return
            except Exception as e:  # noqa: BLE001
                logger.warning("[视频生成] 任务入库失败，降级 JSON 文件: %s", e)
    # JSON 降级
    tasks = _load_tasks()
    tasks[task["id"]] = task
    try:
        with open(_TASK_DIR, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("[视频生成] 任务保存失败: %s", e)


def _load_tasks() -> Dict[str, Dict]:
    """加载所有任务：DB 优先，降级 JSON 文件。"""
    with get_cursor() as cur:
        if cur is not None:
            try:
                cur.execute("SELECT * FROM video_task")
                return {r["id"]: _row_to_task(r) for r in cur.fetchall()}
            except Exception as e:  # noqa: BLE001
                logger.warning("[视频生成] 任务读取降级 JSON 文件: %s", e)
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
        logger.warning("[视频生成] 图片不存在: %s", local_path)
        return None

    try:
        from dashscope.utils.oss_utils import OssUtils
        oss_url, _ = OssUtils.upload(
            model="happyhorse-1.1-i2v",  # 固定用 HappyHorse 做 OSS 上传
            file_path=str(local_path),
            api_key=_API_KEY,
        )
        logger.info("[视频生成] 图片上传成功: %s", oss_url)
        return oss_url
    except Exception as e:
        logger.warning("[视频生成] OSS 上传异常: %s", e)
    return None


def _create_r2v_task(prompt: str, image_url: str) -> Optional[str]:
    """创建 HappyHorse 图生视频任务，返回 task_id。

    自动适配 I2V / R2V 两种模式：
    - happyhorse-1.1-i2v：media.type 必须为 first_frame（首帧驱动生视频）
    - happyhorse-1.1-r2v：media.type 为 reference_image（参考图生视频）
    """
    # 根据模型名自动选择 media type，I2V 用 first_frame，R2V 用 reference_image
    media_type = "first_frame" if "i2v" in _MODEL.lower() else "reference_image"
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
                {"type": media_type, "url": image_url}
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
                logger.info("[视频生成] 任务创建成功: %s", task_id)
                return task_id
            logger.warning("[视频生成] 任务创建返回无 task_id: %s", result)
        else:
            logger.warning("[视频生成] 任务创建失败 HTTP %s: %s", r.status_code, r.text[:300])
    except Exception as e:
        logger.warning("[视频生成] 任务创建异常: %s", e)
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
                logger.info("[视频生成] 轮询状态: %s", status)

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
                    logger.warning("[视频生成] 任务失败: %s", msg)
                    return None
        except Exception as e:
            logger.warning("[视频生成] 轮询异常: %s", e)

        time.sleep(interval)

    logger.warning("[视频生成] 轮询超时 (%ss)", timeout)
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
            logger.info("[视频生成] 视频下载完成: %s", save_path)
            return f"/videos/{filename}"
        else:
            logger.warning("[视频生成] 视频下载失败 HTTP %s", r.status_code)
    except Exception as e:
        logger.warning("[视频生成] 视频下载异常: %s", e)
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


# ============ 文生视频（T2V）============

def _create_t2v_task(prompt: str) -> Optional[str]:
    """创建文生视频任务（通义万相 Wan2.1 T2V），返回 task_id。

    与 R2V 的区别：不需要参考图片，input 只传 prompt。
    """
    headers = {
        "Authorization": f"Bearer {_API_KEY}",
        "X-DashScope-Async": "enable",
        "Content-Type": "application/json",
    }
    body = {
        "model": VIDEO_T2V_CONFIG.get("model", "wanx2.1-t2v-turbo"),
        "input": {
            "prompt": prompt,
        },
        "parameters": {
            "resolution": VIDEO_T2V_CONFIG.get("resolution", "720P"),
            "ratio": VIDEO_T2V_CONFIG.get("ratio", "16:9"),
            "duration": VIDEO_T2V_CONFIG.get("duration", 5),
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
                logger.info("[文生视频] 任务创建成功: %s", task_id)
                return task_id
            logger.warning("[文生视频] 任务创建返回无 task_id: %s", result)
        else:
            logger.warning("[文生视频] 任务创建失败 HTTP %s: %s", r.status_code, r.text[:300])
    except Exception as e:
        logger.warning("[文生视频] 任务创建异常: %s", e)
    return None


def generate_text_video_task(prompt: str) -> Dict[str, Any]:
    """文生视频：纯文字描述生成视频（通义万相 Wan2.1 T2V）。

    流程：创建 T2V 任务 → 轮询 → 下载视频
    无需图片，仅凭文字描述生成视频。

    Args:
        prompt: 视频描述（如"一只猫在阳光下打盹，慵懒午后，暖色调"）

    Returns:
        dict: task_id / status / video_url / prompt / used_fallback
    """
    # 未配置 API Key → 降级
    if not _API_KEY:
        return _do_fallback(prompt, "", "，未配置 DASHSCOPE_API_KEY")

    # 创建任务记录（文生视频无图片）
    task = _create_task_record(prompt, "", "processing")
    task["mode"] = "t2v"  # 标记文生视频模式
    _save_task(task)

    # 步骤1：创建 T2V 任务
    logger.info("[文生视频] 步骤1: 创建 T2V 任务 (model=%s)", VIDEO_T2V_CONFIG.get('model'))
    ds_task_id = _create_t2v_task(prompt)
    if not ds_task_id:
        return _do_fallback(prompt, "", "，任务创建失败")

    # 步骤2：轮询任务状态（复用 R2V 的轮询逻辑）
    logger.info("[文生视频] 步骤2: 轮询任务 %s", ds_task_id)
    video_url = _poll_task(ds_task_id)
    if not video_url:
        return _do_fallback(prompt, "", "，视频生成超时或失败")

    # 步骤3：下载视频到本地
    logger.info("[文生视频] 步骤3: 下载视频")
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
        "image_url": "",
        "prompt": prompt,
        "mode": "t2v",
        "used_fallback": False,
        "msg": "视频已生成（通义万相 Wan2.1 T2V）",
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
    logger.info("[视频生成] 步骤1: 上传图片 %s", image_path)
    remote_url = _upload_image_to_dashscope(image_path)
    if not remote_url:
        return _do_fallback(prompt, image_path, "，图片上传失败")

    # 步骤2：创建 R2V 任务
    logger.info("[视频生成] 步骤2: 创建 R2V 任务 (model=%s)", _MODEL)
    ds_task_id = _create_r2v_task(prompt, remote_url)
    if not ds_task_id:
        return _do_fallback(prompt, image_path, "，任务创建失败")

    # 步骤3：轮询任务状态
    logger.info("[视频生成] 步骤3: 轮询任务 %s", ds_task_id)
    video_url = _poll_task(ds_task_id)
    if not video_url:
        return _do_fallback(prompt, image_path, "，视频生成超时或失败")

    # 步骤4：下载视频到本地
    logger.info("[视频生成] 步骤4: 下载视频")
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


def list_video_tasks(user_id: str = None) -> list:
    """列出视频生成任务（按时间倒序）。

    Args:
        user_id: 非空时只返回该用户的任务（数据隔离）；None 返回全部（内部/遗留兼容）。
    """
    tasks = _load_tasks()
    if user_id is not None:
        tasks = {k: v for k, v in tasks.items() if v.get("user_id") == user_id}
    return sorted(tasks.values(), key=lambda t: t.get("created_at", ""), reverse=True)


def get_video_task(task_id: str, user_id: str = None) -> Optional[Dict]:
    """查询单个任务。user_id 非空时校验归属，非本人任务返回 None。"""
    task = _load_tasks().get(task_id)
    if task is None:
        return None
    if user_id is not None and task.get("user_id") != user_id:
        return None
    return task


def delete_video_task(task_id: str, user_id: str = None) -> bool:
    """删除单个视频任务（user_id 非空时校验归属，防越权删除）。"""
    with get_cursor() as cur:
        if cur is not None:
            if user_id is not None:
                cur.execute("SELECT user_id FROM video_task WHERE id=%s", (task_id,))
                row = cur.fetchone()
                if not row or row.get("user_id") != user_id:
                    logger.warning("[视频生成] 用户 %s 越权删除任务 %s", user_id, task_id)
                    return False
            try:
                cur.execute("DELETE FROM video_task WHERE id=%s", (task_id,))
                return True
            except Exception as e:  # noqa: BLE001
                logger.warning("[视频生成] 删除任务失败（DB）: %s", e)
                return False
    # JSON 降级
    tasks = _load_tasks()
    task = tasks.get(task_id)
    if not task:
        return False
    if user_id is not None and task.get("user_id") != user_id:
        logger.warning("[视频生成] 用户 %s 越权删除任务 %s（JSON 降级模式）", user_id, task_id)
        return False
    del tasks[task_id]
    try:
        with open(_TASK_DIR, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error("[视频生成] 删除任务失败: %s", e)
    return False


# ============ Agent 工具版（@tool 注册，供对话中调用） ============
from langchain_core.tools import tool


@tool("generate_promo_video")
def 生成宣传视频(prompt: str, image_path: str = "") -> str:
    """根据商品参考图生成宣传视频（图生视频模式）。

    当用户要求"生成产品视频""做宣传视频"且提供了商品图片时调用此工具。
    会返回视频链接供用户查看。

    重要：视频内容严格基于用户上传的商品参考图生成，prompt 仅描述运镜/场景氛围，
    不影响参考图中的产品本身。若用户上传了图片，prompt 不要写具体商品名称
    （如"蓝牙音箱"），应只描述场景氛围，避免与参考图产品冲突。

    Args:
        prompt: 场景氛围描述，如"户外运动场景，阳光下展示质感，慢镜头特写"。有上传图时不要写商品名称。
        image_path: 用户上传的商品图片路径（如 /uploads/xxx.jpg）。若用户消息含【用户已上传商品图片：xxx】则必传该路径，留空则走文生视频降级。
    """
    result = generate_video_task(prompt=prompt, image_path=image_path, image_bytes=None)
    mode_note = "图生视频（HappyHorse 1.1 R2V）" if image_path else "文生视频降级（未提供图片）"
    if image_path:
        return (
            f"视频已生成（{mode_note}，基于您上传的商品参考图）。\n"
            f"场景描述：{prompt}\n"
            f"视频链接：{result['video_url']}"
        )
    return (
        f"视频已生成（{mode_note}）。\n"
        f"产品描述：{prompt}\n"
        f"视频链接：{result['video_url']}"
    )


@tool("generate_text_video")
def 文生视频(prompt: str) -> str:
    """根据文字描述生成视频（文生视频模式，无需图片）。

    当用户要求"根据文字生成视频""文生视频""用描述生成视频"时调用此工具。
    纯文字描述即可生成视频，适合创意短片、场景演示等。

    Args:
        prompt: 视频描述，如"一只猫在阳光下打盹，慵懒午后，暖色调，慢镜头"
    """
    result = generate_text_video_task(prompt=prompt)
    return (
        f"文生视频已生成。\n"
        f"视频描述：{prompt}\n"
        f"视频链接：{result['video_url']}\n"
        f"生成模式：{result.get('mode', 't2v').upper()}（通义万相 Wan2.1）"
    )
