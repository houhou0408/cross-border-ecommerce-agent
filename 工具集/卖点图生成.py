# -*- coding: utf-8 -*-
"""商品卖点图生成工具：上传商品图 + 描述，调用通义万相 wanx2.1-t2i 生成全套电商营销图。

设计要点（面试讲解重点）：
1. 一图生多图：用户上传 1 张商品图 + 填写描述/卖点，自动生成 4 种电商标准营销图；
2. 四种类型：白底主图、场景应用图、卖点标注图、详情长图，覆盖电商主图+详情页需求；
3. 异步任务：图像生成耗时较长(10-30秒/张)，采用任务制（创建→轮询→下载）；
4. 降级策略：API 调用失败时返回占位图，保证流程可演示；
5. 集成方式：既可独立页面调用，也可作为 Agent 工具在对话中触发。

对应业务场景：跨境电商 Listing 主图、A+ 内容素材、社交媒体推广图、详情页长图。
"""
import os
import time
import uuid
import json
from pathlib import Path
from typing import Dict, Any, Optional, List

import requests

from config import LOG_DIR, IMAGE_T2I_CONFIG, IMAGE_TEMPLATES, _SCENE_MAP
from 工具集.视频生成 import _save_upload_image, UPLOAD_DIR
from 工具集.数据库连接 import get_cursor
from 模块.日志统计 import get_file_logger
logger = get_file_logger("卖点图生成")

# 卖点图任务存储
_IMAGE_TASK_DIR = LOG_DIR / "image_tasks.json"

# 卖点图保存目录（复用 uploads 目录下的子目录）
IMAGE_DIR = UPLOAD_DIR.parent / "images"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

# 降级占位图（API 调用失败时返回，SVG 内嵌文字说明，保证流程可演示）
_FALLBACK_IMAGE_SVG = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='512' height='512'>"
    "<rect width='100%25' height='100%25' fill='%23f1f5f9'/>"
    "<text x='50%25' y='50%25' font-size='18' fill='%2364748b' "
    "text-anchor='middle' dominant-baseline='middle'>{label}</text>"
    "</svg>"
)

# 从配置读取
_API_KEY = IMAGE_T2I_CONFIG.get("api_key", "")
_BASE_URL = IMAGE_T2I_CONFIG.get("base_url", "https://dashscope.aliyuncs.com/api/v1")
_MODEL = IMAGE_T2I_CONFIG.get("model", "wanx2.1-t2i-turbo")


# ============ 任务记录管理 ============

def _create_task_record(product: str, features: str, image_url: str) -> Dict[str, Any]:
    """创建卖点图生成任务记录（自动从请求上下文取当前用户，做数据归属）。"""
    from 工具集.用户认证 import get_current_user_ctx
    user = get_current_user_ctx() or {}
    task_id = uuid.uuid4().hex[:12]
    task = {
        "id": task_id,
        "user_id": user.get("id"),
        "username": user.get("username", ""),
        "product": product,
        "features": features,
        "image_url": image_url,  # 用户上传的商品原图
        "status": "processing",
        "images": {},            # {type: url}
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "completed_at": "",
        "used_fallback": False,
    }
    _save_task(task)
    return task


# ============ 任务持久化：MySQL 优先，JSON 文件降级 ============

_TABLES_ENSURED = False


def _ensure_tables():
    """懒建 image_task 表（首次写任务时执行一次；建表失败静默走 JSON 降级）。"""
    global _TABLES_ENSURED
    if _TABLES_ENSURED:
        return
    with get_cursor() as cur:
        if cur is not None:
            try:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS image_task (
                        id VARCHAR(12) PRIMARY KEY,
                        user_id VARCHAR(32) NULL,
                        username VARCHAR(100),
                        product VARCHAR(500),
                        features TEXT,
                        image_url VARCHAR(500),
                        status VARCHAR(20),
                        images MEDIUMTEXT,
                        used_fallback TINYINT,
                        created_at VARCHAR(32),
                        completed_at VARCHAR(32),
                        INDEX idx_image_user (user_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("[卖点图] 建表失败，任务将走 JSON 降级: %s", e)
    _TABLES_ENSURED = True


def _row_to_task(row: Dict) -> Dict:
    """DB 行 → 任务 dict（images 列存 JSON 字符串，反序列化）。"""
    try:
        images = json.loads(row.get("images") or "{}")
    except Exception:
        images = {}
    return {
        "id": row["id"],
        "user_id": row.get("user_id"),
        "username": row.get("username", ""),
        "product": row.get("product", ""),
        "features": row.get("features", ""),
        "image_url": row.get("image_url", ""),
        "status": row.get("status", ""),
        "images": images,
        "used_fallback": bool(row.get("used_fallback", 0)),
        "created_at": str(row.get("created_at", "")),
        "completed_at": str(row.get("completed_at", "")),
    }


def _task_to_row(task: Dict) -> tuple:
    """任务 dict → DB 行（列序与 INSERT 语句一致）。"""
    return (
        task["id"], task.get("user_id"), task.get("username", ""),
        task.get("product", ""), task.get("features", ""), task.get("image_url", ""),
        task.get("status", ""), json.dumps(task.get("images", {}), ensure_ascii=False),
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
                    "INSERT INTO image_task (id, user_id, username, product, features, image_url, "
                    "status, images, used_fallback, created_at, completed_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE status=VALUES(status), images=VALUES(images), "
                    "used_fallback=VALUES(used_fallback), completed_at=VALUES(completed_at)",
                    _task_to_row(task),
                )
                return
            except Exception as e:  # noqa: BLE001
                logger.warning("[卖点图] 任务入库失败，降级 JSON 文件: %s", e)
    # JSON 降级
    tasks = _load_tasks()
    tasks[task["id"]] = task
    try:
        with open(_IMAGE_TASK_DIR, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("[卖点图] 任务保存失败: %s", e)


def _load_tasks() -> Dict[str, Dict]:
    """加载所有任务：DB 优先，降级 JSON 文件。"""
    with get_cursor() as cur:
        if cur is not None:
            try:
                cur.execute("SELECT * FROM image_task")
                return {r["id"]: _row_to_task(r) for r in cur.fetchall()}
            except Exception as e:  # noqa: BLE001
                logger.warning("[卖点图] 任务读取降级 JSON 文件: %s", e)
    if _IMAGE_TASK_DIR.exists():
        try:
            with open(_IMAGE_TASK_DIR, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


# ============ 通义万相 T2I API 调用 ============

def _image_to_base64_url(image_path: str) -> Optional[str]:
    """把本地图片转为 data:image/xxx;base64,... 格式，供 wan2.7-image 图生图参考。"""
    try:
        local_path = UPLOAD_DIR / image_path.replace("/uploads/", "")
        if not local_path.exists():
            logger.warning("[卖点图] 参考图不存在: %s", local_path)
            return None
        ext = local_path.suffix.lower().lstrip(".")
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "bmp": "bmp"}.get(ext, "png")
        import base64
        with open(local_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/{mime};base64,{b64}"
    except Exception as e:
        logger.warning("[卖点图] 参考图转 base64 异常: %s", e)
        return None


def _create_t2i_task(prompt: str, size: str = "1024*1024", ref_image: str = "",
                     model_override: str = "") -> Optional[str]:
    """创建通义万相文生图任务，返回 task_id。

    wan2.7-image 模型：支持图生图（参考图），使用 messages/content 格式；
    无参考图时退化为纯文生图。
    异步任务，需 X-DashScope-Async: enable 头，创建后通过轮询获取结果。

    Args:
        model_override: 非空时替换默认 model，用于铺货模式切换快速模型。
    """
    headers = {
        "Authorization": f"Bearer {_API_KEY}",
        "X-DashScope-Async": "enable",
        "Content-Type": "application/json",
    }

    # wan2.7-image 用 messages/content 格式，支持 image 参考
    content = [{"text": prompt}]
    if ref_image:
        content.append({"image": ref_image})

    body = {
        "model": model_override if model_override else _MODEL,
        "input": {
            "messages": [{"role": "user", "content": content}]
        },
        "parameters": {
            "size": size,
            "n": IMAGE_T2I_CONFIG.get("n", 1),
        },
    }
    try:
        r = requests.post(
            f"{_BASE_URL}/services/aigc/image-generation/generation",
            headers=headers,
            json=body,
            timeout=30,
        )
        if r.status_code == 200:
            result = r.json()
            output = result.get("output", {})
            task_id = output.get("task_id")
            if task_id:
                logger.info("[卖点图] 任务创建成功: %s (ref=%s prompt=%s...)", task_id, '有' if ref_image else '无', prompt[:40])
                return task_id
            logger.warning("[卖点图] 任务创建返回无 task_id: %s", result)
        else:
            logger.warning("[卖点图] 任务创建失败 HTTP %s: %s", r.status_code, r.text[:300])
    except Exception as e:
        logger.warning("[卖点图] 任务创建异常: %s", e)
    return None


def _poll_task(task_id: str) -> Optional[str]:
    """轮询图像生成任务状态，返回图片 URL。

    兼容两种返回格式：
    - 旧版（wan2.2-t2i）：output.task_status / output.results[].url
    - 新版（wan2.7-image）：output.task_status / output.choices[].message.content[].image
    """
    headers = {"Authorization": f"Bearer {_API_KEY}"}
    interval = IMAGE_T2I_CONFIG.get("poll_interval", 3)
    timeout = IMAGE_T2I_CONFIG.get("poll_timeout", 180)
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
                logger.info("[卖点图] 轮询状态: %s", status)

                if status == "SUCCEEDED":
                    # 新版 wan2.7-image：choices[].message.content[].image
                    choices = output.get("choices", [])
                    if choices:
                        for ch in choices:
                            msg = ch.get("message", {})
                            for c in msg.get("content", []):
                                if c.get("image"):
                                    return c["image"]
                    # 旧版：results[].url
                    results = output.get("results", [])
                    if results and isinstance(results, list):
                        return results[0].get("url", "")
                    # 兼容直接返回 url 的格式
                    return output.get("url")
                elif status == "FAILED":
                    msg = output.get("message", "未知错误")
                    logger.warning("[卖点图] 任务失败: %s", msg)
                    return None
        except Exception as e:
            logger.warning("[卖点图] 轮询异常: %s", e)

        time.sleep(interval)

    logger.warning("[卖点图] 轮询超时 (%ss)", timeout)
    return None


def _download_image(image_url: str, prefix: str = "img") -> str:
    """下载远程图片到本地，返回相对路径。"""
    try:
        r = requests.get(image_url, timeout=60, stream=True)
        if r.status_code == 200:
            filename = f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:6]}.png"
            save_path = IMAGE_DIR / filename
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info("[卖点图] 图片下载完成: %s", save_path)
            return f"/images/{filename}"
        else:
            logger.warning("[卖点图] 图片下载失败 HTTP %s", r.status_code)
    except Exception as e:
        logger.warning("[卖点图] 图片下载异常: %s", e)
    # 下载失败则返回远程 URL
    return image_url


def _build_prompt(template_key: str, product: str, features: str, category: str = "") -> str:
    """根据模板构建图像生成 prompt。

    Args:
        category: 商品品类（如"电子产品""服装"等），用于场景图智能匹配场景描述。
                  仅对 template_key="scene" 生效。
    """
    template = IMAGE_TEMPLATES.get(template_key, {})
    prompt = template.get("prompt", "product photography of {product}")

    # 智能场景匹配：场景图根据品类选择对应场景描述
    scene_desc = "lifestyle product photography in natural setting"  # 默认场景
    if template_key == "scene" and category:
        scene_desc = _SCENE_MAP.get(category, scene_desc)

    return prompt.format(product=product, features=features or "high quality, durable",
                         scene_desc=scene_desc)


def _do_fallback(product: str, features: str, image_url: str, reason: str = "") -> Dict[str, Any]:
    """降级：返回占位图（4 种类型各一张 SVG）。"""
    task = _create_task_record(product, features, image_url)
    images = {}
    for key, tpl in IMAGE_TEMPLATES.items():
        images[key] = {
            "name": tpl["name"],
            "url": _FALLBACK_IMAGE_SVG.format(label=tpl["name"]),
            "fallback": True,
        }
    task["images"] = images
    task["status"] = "completed"
    task["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    task["used_fallback"] = True
    _save_task(task)
    return {
        "task_id": task["id"],
        "status": "completed",
        "images": images,
        "image_url": image_url,
        "product": product,
        "features": features,
        "used_fallback": True,
        "msg": f"卖点图已生成（占位图{reason}）",
    }


# ============ 主入口 ============

def generate_selling_images(
    product: str,
    features: str = "",
    image_bytes: bytes = None,
    filename: str = "",
    image_path: str = "",
    types: List[str] = None,
    quality: str = "精品",
    category: str = "",
) -> Dict[str, Any]:
    """生成全套电商卖点图（通义万相 wanx2.1-t2i 文生图）。

    流程：保存商品原图 → 对每种类型创建 T2I 任务 → 轮询 → 下载

    Args:
        product: 商品描述（如"防水蓝牙音箱，黑色圆柱形"）
        features: 卖点列表（如"20小时续航,IPX7防水,蓝牙5.3"）
        image_bytes: 商品原图二进制（有则保存）
        filename: 原始文件名
        image_path: 已上传图片的URL路径（如 /uploads/xxx.jpg）
        types: 要生成的图片类型列表，默认全部4种
        quality: "精品"（高质量 wan2.7-image）或 "铺货"（快速低成本 fast_model）
        category: 商品品类（如"电子产品""服装"等），用于场景图智能匹配

    Returns:
        dict: task_id / status / images / image_url / product / features / used_fallback
    """
    # 保存上传的商品原图
    if image_bytes and not image_path:
        image_path = _save_upload_image(image_bytes, filename or "product.jpg")

    # 默认生成全部 4 种
    if types is None:
        types = list(IMAGE_TEMPLATES.keys())

    # 精品/铺货双画质
    model_override = ""
    if quality == "铺货":
        model_override = IMAGE_T2I_CONFIG.get("fast_model", "wan2.2-t2i-flash")

    # 未配置 API Key → 降级
    if not _API_KEY:
        return _do_fallback(product, features, image_path, "，未配置 DASHSCOPE_API_KEY")

    # 创建任务记录
    task = _create_task_record(product, features, image_path)
    task["status"] = "processing"
    _save_task(task)

    images: Dict[str, Any] = {}

    # 把用户上传的商品图转 base64，作为图生图参考（wan2.7-image 支持）
    ref_image_b64 = _image_to_base64_url(image_path) if image_path else ""
    if ref_image_b64:
        logger.info("[卖点图] 已加载参考图: %s (base64 长度=%s)", image_path, len(ref_image_b64))
    else:
        logger.info("[卖点图] 无参考图，走纯文生图（product 描述决定生成内容）")

    # 逐种类型生成（通义万相 T2I 一次只生成一张，逐个调用）
    for key in types:
        tpl = IMAGE_TEMPLATES.get(key, {})
        name = tpl.get("name", key)
        prompt = _build_prompt(key, product, features, category)

        logger.info("\n[卖点图] 生成 %s (type=%s)", name, key)
        logger.info("[卖点图] prompt: %s...", prompt[:80])

        # 详情长图用竖版尺寸
        size = "768*1024" if key == "detail" else IMAGE_T2I_CONFIG.get("size", "1024*1024")

        # 步骤1：创建 T2I 任务（带参考图时走图生图）
        ds_task_id = _create_t2i_task(prompt, size=size, ref_image=ref_image_b64,
                                      model_override=model_override)
        if not ds_task_id:
            images[key] = {
                "name": name,
                "url": _FALLBACK_IMAGE_SVG.format(label=name),
                "fallback": True,
                "error": "任务创建失败",
            }
            task["images"] = images
            _save_task(task)
            continue

        # 步骤2：轮询
        img_url = _poll_task(ds_task_id)
        if not img_url:
            images[key] = {
                "name": name,
                "url": _FALLBACK_IMAGE_SVG.format(label=name),
                "fallback": True,
                "error": "生成超时或失败",
            }
            task["images"] = images
            _save_task(task)
            continue

        # 步骤3：下载到本地
        local_url = _download_image(img_url, prefix=f"sell_{key}")
        images[key] = {
            "name": name,
            "url": local_url,
            "fallback": False,
        }
        task["images"] = images
        _save_task(task)

    # 标记任务完成
    all_fallback = all(v.get("fallback") for v in images.values()) if images else True
    task["status"] = "completed"
    task["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    task["used_fallback"] = all_fallback
    _save_task(task)

    return {
        "task_id": task["id"],
        "status": "completed",
        "images": images,
        "image_url": image_path,
        "product": product,
        "features": features,
        "used_fallback": all_fallback,
        "msg": "卖点图已生成（通义万相 wanx2.1-t2i）" if not all_fallback else "卖点图已生成（部分降级）",
    }


def list_image_tasks(user_id: str = None) -> list:
    """列出卖点图生成任务（按时间倒序）。

    Args:
        user_id: 非空时只返回该用户的任务（数据隔离）；None 返回全部（内部/遗留兼容）。
    """
    tasks = _load_tasks()
    if user_id is not None:
        tasks = {k: v for k, v in tasks.items() if v.get("user_id") == user_id}
    return sorted(tasks.values(), key=lambda t: t.get("created_at", ""), reverse=True)


def get_image_task(task_id: str, user_id: str = None) -> Optional[Dict]:
    """查询单个任务。user_id 非空时校验归属，非本人任务返回 None。"""
    task = _load_tasks().get(task_id)
    if task is None:
        return None
    if user_id is not None and task.get("user_id") != user_id:
        return None
    return task


def delete_image_task(task_id: str, user_id: str = None) -> bool:
    """删除单个卖点图任务（user_id 非空时校验归属，防越权删除）。"""
    with get_cursor() as cur:
        if cur is not None:
            if user_id is not None:
                cur.execute("SELECT user_id FROM image_task WHERE id=%s", (task_id,))
                row = cur.fetchone()
                if not row or row.get("user_id") != user_id:
                    logger.warning("[卖点图] 用户 %s 越权删除任务 %s", user_id, task_id)
                    return False
            try:
                cur.execute("DELETE FROM image_task WHERE id=%s", (task_id,))
                return True
            except Exception as e:  # noqa: BLE001
                logger.warning("[卖点图] 删除任务失败（DB）: %s", e)
                return False
    # JSON 降级
    tasks = _load_tasks()
    task = tasks.get(task_id)
    if not task:
        return False
    if user_id is not None and task.get("user_id") != user_id:
        logger.warning("[卖点图] 用户 %s 越权删除任务 %s（JSON 降级模式）", user_id, task_id)
        return False
    del tasks[task_id]
    try:
        with open(_IMAGE_TASK_DIR, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error("[卖点图] 删除任务失败: %s", e)
    return False


# ============ Agent 工具版（@tool 注册，供对话中调用） ============
from langchain_core.tools import tool


@tool("generate_selling_images")
def 生成卖点图(product: str, features: str = "", image_path: str = "",
              品类: str = "", 画质: str = "精品") -> str:
    """根据商品参考图生成全套电商卖点图（白底主图、场景图、卖点标注图、详情长图）。

    当用户要求"生成卖点图""做商品图""电商主图""详情图"时调用此工具。
    会返回 4 张图片链接供用户查看。

    重要：图像内容严格基于用户上传的商品参考图生成，product 参数仅用于任务记录，
    不影响生成图像内容。若用户上传了图片，product 应填"用户上传的商品图"，
    禁止根据历史对话猜测商品名称（如把上传的手表图描述成音箱）。

    Args:
        product: 商品描述。有上传图时填"用户上传的商品图"；无图时填实际商品描述。
        features: 产品卖点，逗号分隔，如"20小时续航,IPX7防水,蓝牙5.3,360度环绕音"
        image_path: 用户上传的商品图片路径（如 /uploads/xxx.jpg）。若用户消息含【用户已上传商品图片：xxx】则传入该路径，留空则走纯文生图。
        品类: 商品品类（如"电子产品""服装""家居""美妆"等），用于场景图智能匹配场景风格。
        画质: "精品"（高质量 wan2.7-image）或 "铺货"（快速低成本）。
    """
    result = generate_selling_images(product=product, features=features, image_path=image_path,
                                     quality=画质, category=品类)
    # 有参考图时，回复不写死商品名称，避免 LLM 套用上下文里的旧商品名
    if image_path:
        lines = ["商品卖点图已生成（基于您上传的商品参考图）。"]
    else:
        lines = [f"商品卖点图已生成。", f"商品描述：{product}"]
    if features:
        lines.append(f"产品卖点：{features}")
    lines.append("")
    lines.append("生成结果：")
    for key, img in result.get("images", {}).items():
        name = img.get("name", key)
        url = img.get("url", "")
        tag = "（占位图）" if img.get("fallback") else ""
        lines.append(f"- {name}{tag}：{url}")
    if result.get("used_fallback"):
        lines.append("")
        lines.append("提示：当前为占位图。配置 DASHSCOPE_API_KEY 后可生成真实 AI 卖点图。")
    return "\n".join(lines)
