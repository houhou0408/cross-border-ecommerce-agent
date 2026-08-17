# -*- coding: utf-8 -*-
"""FastAPI 服务：为跨境电商 Agent 提供简易 HTTP 接口，便于演示与联调。

启动: python -m uvicorn 接口.FastAPI服务:app --host 0.0.0.0 --port 8000 --reload
或:   python 接口/FastAPI服务.py

接口:
- GET  /                  Web 前端界面（聊天+工具面板+统计）
- GET  /health            健康检查
- POST /ask               Agent 多任务问答（ReAct+工具调用+幻觉治理）
- POST /listing           直接生成 Listing
- POST /tariff            直接查关税
- POST /currency          直接汇率换算
- GET  /stats             运行统计（调用量/耗时/幻觉拦截率）
"""
import sys
from pathlib import Path

# 确保项目根目录在 sys.path（兼容直接运行）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, UploadFile, File, Form, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from 模块.Agent调度 import get_agent
from 模块.日志统计 import get_logger
from 模块.记忆模块 import get_memory
from 模块.切片向量化 import add_documents, list_documents, delete_document
from 模块.效果评估 import get_evaluator, TEST_SET
from 工具集.关税查询 import 查询关税
from 工具集.汇率转换 import 汇率换算
from 工具集.Listing生成 import 生成产品Listing
from 工具集.视频生成 import generate_video_task, generate_text_video_task, list_video_tasks, get_video_task, delete_video_task
from 工具集.卖点图生成 import generate_selling_images, list_image_tasks, get_image_task, delete_image_task
from 工具集.用户认证 import register, login, logout, get_user_by_token, get_current_user

app = FastAPI(title="跨境电商 AI Agent", version="1.0.0")

# 前端目录：优先用 React 构建产物（前端/dist），未构建时回退到原 index.html
_FRONTEND_ROOT = Path(__file__).resolve().parent.parent / "前端"
_DIST_DIR = _FRONTEND_ROOT / "dist"          # React + Vite 构建产物
_LEGACY_HTML = _FRONTEND_ROOT / "index.html"  # 旧版单文件前端（回退用）

# 挂载构建产物的静态资源（/assets/... 由 Vite 生成）
if _DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST_DIR / "assets")), name="assets")

# 挂载上传图片和视频的静态目录
_STATIC_DIR = Path(__file__).resolve().parent.parent / "静态资源"
(_STATIC_DIR / "uploads").mkdir(parents=True, exist_ok=True)
(_STATIC_DIR / "videos").mkdir(parents=True, exist_ok=True)
(_STATIC_DIR / "images").mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_STATIC_DIR / "uploads")), name="uploads")
app.mount("/videos", StaticFiles(directory=str(_STATIC_DIR / "videos")), name="videos")
app.mount("/images", StaticFiles(directory=str(_STATIC_DIR / "images")), name="images")


# ============ 请求/响应模型 ============
class AskRequest(BaseModel):
    query: str = Field(..., min_length=1, description="用户自然语言任务")
    session_id: str | None = Field(None, description="会话ID，为空则新建会话")
    image_path: str | None = Field(None, description="用户在对话中上传的商品图片路径（/uploads/xxx.jpg），供图生视频/卖点图工具使用")


class ListingRequest(BaseModel):
    product: str = Field(..., description="产品名称")
    platform: str = Field("amazon", description="平台 amazon/shopee/temu")
    language: str = Field("en", description="语言 en/zh")
    features: str = Field("", description="产品卖点")


class TariffRequest(BaseModel):
    country: str = Field(..., description="目的国")
    category: str = Field(..., description="商品类别")
    value: float = Field(0.0, description="货值")
    freight: float = Field(0.0, description="运费")
    insurance: float = Field(0.0, description="保险费")


class CurrencyRequest(BaseModel):
    amount: float
    from_currency: str
    to_currency: str


class RegisterRequest(BaseModel):
    username: str = Field(..., description="用户名，至少 2 字符")
    password: str = Field(..., description="密码，至少 6 位")


class LoginRequest(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


# ============ 接口 ============
@app.get("/")
def index():
    """根路由：返回 Web 前端界面（React 构建产物优先，回退到旧版单文件）。

    注意：index.html 禁止缓存，确保浏览器总是加载最新构建产物（assets 文件名带 hash，可长期缓存）。
    """
    _NO_CACHE = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    dist_index = _DIST_DIR / "index.html"
    if dist_index.exists():
        return FileResponse(str(dist_index), headers=_NO_CACHE)
    if _LEGACY_HTML.exists():
        return FileResponse(str(_LEGACY_HTML), headers=_NO_CACHE)
    return {"msg": "前端未构建，请在 前端/react-app 下执行 npm run build"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "跨境电商AIAgent"}


# ============ 用户认证接口 ============
@app.post("/auth/register")
def auth_register(req: RegisterRequest):
    """用户注册。"""
    result = register(req.username, req.password)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "注册失败")}
    return result


@app.post("/auth/login")
def auth_login(req: LoginRequest):
    """用户登录，返回 token。"""
    result = login(req.username, req.password)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "登录失败")}
    return result


@app.post("/auth/logout")
def auth_logout(user: dict = Depends(get_current_user)):
    """退出登录。"""
    logout(user.get("token", ""))
    return {"ok": True, "msg": "已退出登录"}


@app.get("/auth/me")
def auth_me(user: dict = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return {"ok": True, "user": {"id": user["id"], "username": user["username"]}}


@app.post("/ask")
def ask(req: AskRequest):
    """Agent 多任务问答主接口（支持多轮对话记忆）。

    流程：
    1. 无 session_id → 新建会话；有 session_id → 复用历史；
    2. 从记忆模块取出历史，转为 LangChain messages 注入 Agent；
    3. Agent 编排（ReAct + 工具调用 + 幻觉治理）；
    4. 把本轮 user/assistant 消息写回记忆模块持久化。
    """
    memory = get_memory()
    agent = get_agent()

    # 会话管理：无 session_id 则新建
    if req.session_id:
        session_id = req.session_id
    else:
        sess = memory.create_session()
        session_id = sess["id"]

    # 取历史上下文（多轮记忆）
    history = memory.get_history(session_id)
    chat_history = memory.to_langchain_messages(history)

    # 若用户上传了商品图片，将图片路径以约定格式注入 query，供 Agent 调用图生视频/卖点图工具
    effective_query = req.query
    if req.image_path:
        effective_query = f"【用户已上传商品图片：{req.image_path}】\n用户问题：{req.query}"

    # Agent 编排
    result = agent.orchestrate(effective_query, chat_history=chat_history, session_id=session_id)
    result["session_id"] = session_id

    # 写回记忆（user + assistant，存原始问题不含图片标记）
    memory.add_message(session_id, "user", req.query)
    memory.add_message(session_id, "assistant", result.get("answer", ""), {
        "tools_used": result.get("tools_used", []),
        "grounded": result.get("grounded"),
        "score": result.get("score"),
        "latency_ms": result.get("latency_ms"),
    })

    return result


@app.post("/chat/upload-image")
async def chat_upload_image(file: UploadFile = File(...)):
    """对话页上传商品图片：保存后返回 image_path，供 /ask 调用时携带。

    与「视频生成」「卖点图」页面的上传逻辑一致，复用 _save_upload_image。
    """
    from 工具集.视频生成 import _save_upload_image
    if not file.content_type or not file.content_type.startswith("image/"):
        return {"error": "仅支持图片文件"}
    data = await file.read()
    if not data:
        return {"error": "图片内容为空"}
    image_path = _save_upload_image(data, file.filename or "chat_image.jpg")
    return {"image_path": image_path, "url": image_path}


# ============ 会话管理接口（记忆模块） ============
@app.get("/sessions")
def list_sessions():
    """列出所有会话。"""
    return {"sessions": get_memory().list_sessions()}


@app.post("/sessions")
def create_session():
    """新建会话。"""
    return get_memory().create_session()


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    """获取会话详情（含消息历史）。"""
    sess = get_memory().get_session(session_id)
    if not sess:
        return {"error": "会话不存在"}, 404
    return sess


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    """删除会话。"""
    ok = get_memory().delete_session(session_id)
    return {"deleted": ok}


@app.post("/listing")
def listing(req: ListingRequest):
    """直接调用 Listing 生成工具。"""
    text = 生成产品Listing.invoke({
        "产品名称": req.product,
        "平台": req.platform,
        "语言": req.language,
        "产品卖点": req.features,
    })
    return {"listing": text}


@app.post("/tariff")
def tariff(req: TariffRequest):
    """直接查关税。"""
    text = 查询关税.invoke({
        "目的国": req.country,
        "商品类别": req.category,
        "货值": req.value,
        "运费": req.freight,
        "保险费": req.insurance,
    })
    return {"result": text}


@app.post("/currency")
def currency(req: CurrencyRequest):
    """直接汇率换算。"""
    text = 汇率换算.invoke({
        "金额": req.amount,
        "源币种": req.from_currency,
        "目标币种": req.to_currency,
    })
    return {"result": text}


@app.get("/stats")
def stats():
    """运行统计。"""
    return get_logger().stats()


@app.get("/collection/status")
def collection_status():
    """数据采集模块状态（汇率/选品热度的数据来源与更新时间）。"""
    from 工具集.数据采集 import get_collection_status
    return get_collection_status()


# ============ 知识库管理接口（文档上传/列表/删除） ============
@app.get("/kb/documents")
def kb_list():
    """列出知识库所有文档（来源+切片数）。"""
    try:
        docs = list_documents()
        return {"documents": docs, "total": len(docs)}
    except Exception as e:
        return {"documents": [], "total": 0, "error": str(e)}


@app.post("/kb/upload")
async def kb_upload(file: UploadFile = File(...)):
    """上传文档到知识库：自动切片 → 向量化 → 增量写入 Chroma。

    支持 .md / .txt。上传后即可被 Agent 检索到。
    """
    import os
    from langchain_core.documents import Document

    filename = file.filename or "uploaded.md"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".md", ".txt", ".markdown"):
        return {"error": "仅支持 .md / .txt 文件"}

    content = (await file.read()).decode("utf-8", errors="ignore")
    doc = Document(page_content=content, metadata={"source": filename})
    try:
        n = add_documents([doc])
        return {"source": filename, "chunks": n, "msg": f"已入库 {n} 条切片"}
    except Exception as e:
        return {"error": str(e)}


@app.delete("/kb/documents/{source}")
def kb_delete(source: str):
    """删除知识库中指定来源的文档。"""
    try:
        n = delete_document(source)
        return {"source": source, "deleted": n}
    except Exception as e:
        return {"error": str(e)}


# ============ Agent 效果评估接口 ============
@app.get("/eval/testset")
def eval_testset():
    """返回评估测试集（前端展示用，不执行）。"""
    return {"testset": TEST_SET, "total": len(TEST_SET)}


@app.post("/eval/run")
def eval_run():
    """执行批量评估，返回汇总报告。

    会真实调用 Agent 执行每条测试，耗时较长（每条约10-30秒）。
    """
    evaluator = get_evaluator()
    report = evaluator.run_all()
    return report


# ============ 视频生成接口（图生视频） ============
@app.post("/video/generate")
async def video_generate(file: UploadFile = File(...), prompt: str = Form("")):
    """上传商品图片 + 描述，生成产品宣传视频（图生视频）。

    流程：保存图片 → 调用视频生成 → 返回视频URL。
    未配置 VIDEO_API_KEY 时返回示例视频（降级，保证可演示）。
    """
    img_bytes = await file.read()
    result = generate_video_task(
        prompt=prompt or "产品宣传视频",
        image_bytes=img_bytes,
        filename=file.filename or "product.jpg",
    )
    return result


@app.get("/video/tasks")
def video_tasks():
    """列出所有视频生成任务。"""
    return {"tasks": list_video_tasks()}


class TextVideoRequest(BaseModel):
    prompt: str = Field(..., description="视频描述文字")


@app.post("/video/text-to-video")
def video_text_to_video(req: TextVideoRequest):
    """文生视频：纯文字描述生成视频（通义万相 Wan2.1 T2V）。

    无需图片，仅凭文字描述生成视频。
    未配置 VIDEO_API_KEY 时返回示例视频（降级，保证可演示）。
    """
    return generate_text_video_task(prompt=req.prompt)


@app.get("/video/tasks/{task_id}")
def video_task_detail(task_id: str):
    """查询单个视频任务状态。"""
    t = get_video_task(task_id)
    if not t:
        return {"error": "任务不存在"}
    return t


@app.delete("/video/tasks/{task_id}")
def video_task_delete(task_id: str):
    """删除单个视频任务。"""
    ok = delete_video_task(task_id)
    return {"deleted": ok, "task_id": task_id}


# ============ 卖点图生成接口（商品图 → 全套电商营销图） ============
@app.post("/image/generate-batch")
async def image_generate_batch(
    file: UploadFile = File(...),
    product: str = Form(""),
    features: str = Form(""),
):
    """上传商品图片 + 描述，生成全套电商卖点图（4 种类型）。

    流程：保存商品原图 → 调用通义万相 T2I 生成 4 种营销图 → 返回图片URL。
    未配置 DASHSCOPE_API_KEY 时返回占位图（降级，保证可演示）。

    生成类型：白底主图 / 场景应用图 / 卖点标注图 / 详情长图
    """
    img_bytes = await file.read()
    result = generate_selling_images(
        product=product or "产品",
        features=features,
        image_bytes=img_bytes,
        filename=file.filename or "product.jpg",
    )
    return result


@app.get("/image/tasks")
def image_tasks():
    """列出所有卖点图生成任务。"""
    return {"tasks": list_image_tasks()}


@app.get("/image/tasks/{task_id}")
def image_task_detail(task_id: str):
    """查询单个卖点图任务状态。"""
    t = get_image_task(task_id)
    if not t:
        return {"error": "任务不存在"}
    return t


@app.delete("/image/tasks/{task_id}")
def image_task_delete(task_id: str):
    """删除单个卖点图任务。"""
    ok = delete_image_task(task_id)
    return {"deleted": ok, "task_id": task_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("接口.FastAPI服务:app", host="0.0.0.0", port=8000, reload=False)
