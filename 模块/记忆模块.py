# -*- coding: utf-8 -*-
"""记忆模块：管理 Agent 的多轮对话上下文与会话历史持久化。

设计要点（面试讲解重点）：
1. 双层存储：MySQL 持久化（生产）+ JSON 文件降级（无库环境可演示）；
2. 会话隔离：每个 session_id 独立历史，互不干扰；
3. 上下文注入：orchestrate 时把历史消息注入 LangChain messages，让 Agent 具备"记忆"，
   能基于上下文追问（如"刚才那个关税换算成日元呢"）；
4. 自动摘要：历史超过阈值时保留最近 N 轮 + 早期摘要，避免 token 爆炸（简化版：截断）。

对应 JD 职责 1 的"记忆模块"与职责 4 的"多轮对话"。
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from config import LOG_DIR
from 工具集.数据库连接 import get_cursor
from 模块.日志统计 import get_file_logger
logger = get_file_logger("记忆模块")

# 无 MySQL 时的 JSON 文件降级路径
_SESSION_FILE = LOG_DIR / "sessions.json"

# 每个会话保留的最大历史轮数（超出则截断早期消息，控制 token）
MAX_HISTORY_TURNS = 10


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _new_session_id() -> str:
    return datetime.now().strftime("%m%d") + uuid.uuid4().hex[:4]


class 记忆管理器:
    """会话历史管理：增删查 + 上下文组装。"""

    def __init__(self):
        self._ensure_table()
        self._mem_sessions: Dict[str, Dict[str, Any]] = self._load_json()

    # ---------- 存储 ----------
    def _ensure_table(self):
        """建表（MySQL 不可用时静默跳过，走 JSON 降级）。"""
        with get_cursor() as cur:
            if cur is None:
                return
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_session (
                    id VARCHAR(32) PRIMARY KEY,
                    title VARCHAR(200),
                    created_at DATETIME,
                    updated_at DATETIME
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_message (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    session_id VARCHAR(32),
                    role VARCHAR(20),
                    content TEXT,
                    meta JSON,
                    created_at DATETIME,
                    INDEX idx_session (session_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )

    def _load_json(self) -> Dict[str, Dict[str, Any]]:
        """加载 JSON 降级文件。"""
        if _SESSION_FILE.exists():
            try:
                with open(_SESSION_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_json(self):
        """写入 JSON 降级文件。"""
        try:
            with open(_SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(self._mem_sessions, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("[记忆模块] JSON 持久化失败: %s", e)

    # ---------- 会话 CRUD ----------
    def create_session(self, title: str = "新对话") -> Dict[str, Any]:
        """新建会话，返回 {id, title, created_at, messages:[]}。"""
        sid = _new_session_id()
        now = _now()
        session = {"id": sid, "title": title, "created_at": now, "updated_at": now, "messages": []}

        with get_cursor() as cur:
            if cur is not None:
                cur.execute(
                    "INSERT INTO chat_session (id, title, created_at, updated_at) VALUES (%s,%s,%s,%s)",
                    (sid, title, now, now),
                )
                return session
        # 降级
        self._mem_sessions[sid] = session
        self._save_json()
        return session

    def list_sessions(self) -> List[Dict[str, Any]]:
        """列出所有会话（按更新时间倒序），返回简要信息列表。"""
        with get_cursor() as cur:
            if cur is not None:
                cur.execute(
                    "SELECT id, title, created_at, updated_at FROM chat_session ORDER BY updated_at DESC"
                )
                rows = cur.fetchall()
                # 统计每个会话消息数
                result = []
                for r in rows:
                    cur.execute(
                        "SELECT COUNT(*) AS cnt FROM chat_message WHERE session_id=%s", (r["id"],)
                    )
                    cnt = cur.fetchone()
                    result.append({
                        "id": r["id"],
                        "title": r["title"],
                        "created_at": str(r["created_at"]),
                        "updated_at": str(r["updated_at"]),
                        "message_count": cnt["cnt"] if cnt else 0,
                    })
                return result
        # 降级
        return [
            {
                "id": s["id"],
                "title": s["title"],
                "created_at": s["created_at"],
                "updated_at": s["updated_at"],
                "message_count": len(s.get("messages", [])),
            }
            for s in sorted(
                self._mem_sessions.values(),
                key=lambda x: x.get("updated_at", ""),
                reverse=True,
            )
        ]

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取单个会话及其消息历史。"""
        with get_cursor() as cur:
            if cur is not None:
                cur.execute("SELECT * FROM chat_session WHERE id=%s", (session_id,))
                sess = cur.fetchone()
                if not sess:
                    return None
                cur.execute(
                    "SELECT role, content, meta, created_at FROM chat_message "
                    "WHERE session_id=%s ORDER BY id ASC",
                    (session_id,),
                )
                msgs = cur.fetchall()
                return {
                    "id": sess["id"],
                    "title": sess["title"],
                    "created_at": str(sess["created_at"]),
                    "updated_at": str(sess["updated_at"]),
                    "messages": [
                        {
                            "role": m["role"],
                            "content": m["content"],
                            "meta": json.loads(m["meta"]) if m["meta"] else None,
                            "created_at": str(m["created_at"]),
                        }
                        for m in msgs
                    ],
                }
        # 降级
        return self._mem_sessions.get(session_id)

    def delete_session(self, session_id: str) -> bool:
        """删除会话。"""
        with get_cursor() as cur:
            if cur is not None:
                cur.execute("DELETE FROM chat_message WHERE session_id=%s", (session_id,))
                cur.execute("DELETE FROM chat_session WHERE id=%s", (session_id,))
                return True
        # 降级
        if session_id in self._mem_sessions:
            del self._mem_sessions[session_id]
            self._save_json()
            return True
        return False

    # ---------- 消息管理 ----------
    def add_message(self, session_id: str, role: str, content: str, meta: Dict = None):
        """追加一条消息到会话，并更新会话时间。"""
        now = _now()
        meta_json = json.dumps(meta or {}, ensure_ascii=False)

        with get_cursor() as cur:
            if cur is not None:
                cur.execute(
                    "INSERT INTO chat_message (session_id, role, content, meta, created_at) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (session_id, role, content, meta_json, now),
                )
                # 首条用户消息作为会话标题
                if role == "user":
                    cur.execute(
                        "SELECT COUNT(*) AS cnt FROM chat_message WHERE session_id=%s AND role='user'",
                        (session_id,),
                    )
                    if cur.fetchone()["cnt"] == 1:
                        cur.execute(
                            "UPDATE chat_session SET title=%s, updated_at=%s WHERE id=%s",
                            (content[:30], now, session_id),
                        )
                    else:
                        cur.execute(
                            "UPDATE chat_session SET updated_at=%s WHERE id=%s", (now, session_id)
                        )
                else:
                    cur.execute(
                        "UPDATE chat_session SET updated_at=%s WHERE id=%s", (now, session_id)
                    )
                return
        # 降级
        sess = self._mem_sessions.get(session_id)
        if not sess:
            now = _now()
            sess = {"id": session_id, "title": "新对话", "created_at": now, "updated_at": now, "messages": []}
            self._mem_sessions[session_id] = sess
        sess["messages"].append({"role": role, "content": content, "meta": meta, "created_at": now})
        sess["updated_at"] = now
        if role == "user" and sum(1 for m in sess["messages"] if m["role"] == "user") == 1:
            sess["title"] = content[:30]
        self._save_json()

    def get_history(self, session_id: str, max_turns: int = MAX_HISTORY_TURNS) -> List[Dict[str, str]]:
        """获取会话历史，返回 [{role, content}, ...]，截断到最近 max_turns 轮。

        用于注入 LangChain messages 作为多轮对话上下文。
        """
        sess = self.get_session(session_id)
        if not sess:
            return []
        msgs = sess.get("messages", [])
        # 截断：保留最近 max_turns 条消息
        if len(msgs) > max_turns:
            msgs = msgs[-max_turns:]
        return [{"role": m["role"], "content": m["content"]} for m in msgs]

    def to_langchain_messages(self, history: List[Dict[str, str]]):
        """把历史转为 LangChain 消息列表（HumanMessage / AIMessage 交替）。

        供 Agent 调度注入上下文，实现多轮对话记忆。
        """
        from langchain_core.messages import HumanMessage, AIMessage

        msgs = []
        for m in history:
            if m["role"] == "user":
                msgs.append(HumanMessage(content=m["content"]))
            else:
                msgs.append(AIMessage(content=m["content"]))
        return msgs


# 模块级单例
_memory_instance: Optional[记忆管理器] = None


def get_memory() -> 记忆管理器:
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = 记忆管理器()
    return _memory_instance
