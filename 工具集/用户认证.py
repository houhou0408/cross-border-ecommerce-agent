# -*- coding: utf-8 -*-
"""用户认证模块：注册 / 登录 / token 管理 / FastAPI 鉴权依赖。

设计要点：
1. 零外部依赖：密码哈希用标准库 hashlib.pbkdf2_hmac，token 用 uuid4，无需 bcrypt/pyjwt；
2. 用户存储：JSON 文件持久化（数据/users.json），保证 Demo 环境无需 MySQL 即可用；
3. token 机制：登录成功生成随机 token，存入 数据/tokens.json，带过期时间；
4. FastAPI 集成：提供 get_current_user 依赖，业务接口用 Depends() 保护；
5. 安全性：密码加盐哈希存储，token 有时效，不支持明文密码比对。
"""
import os
import json
import time
import uuid
import hashlib
import secrets
from pathlib import Path
from typing import Optional, Dict, Any

from config import AUTH_CONFIG, DATA_DIR
from 工具集.数据库连接 import get_cursor, is_db_available

# 确保数据目录存在
(DATA_DIR).mkdir(parents=True, exist_ok=True)

_USERS_FILE = Path(AUTH_CONFIG["users_file"])
_TOKENS_FILE = Path(AUTH_CONFIG["tokens_file"])
_TOKEN_EXPIRE = AUTH_CONFIG["token_expire_hours"] * 3600  # 转秒

# 迭代次数（pbkdf2）
_PBKDF2_ITERATIONS = 100000


# ============ 密码哈希（标准库 pbkdf2_hmac，无外部依赖） ============

def _hash_password(password: str, salt: str = None) -> str:
    """密码加盐哈希。返回格式: salt$hash"""
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS)
    return f"{salt}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    """验证密码是否匹配存储的哈希值。"""
    try:
        salt, hash_hex = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS)
        return secrets.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ============ 用户存储（JSON 文件，保证 Demo 可用） ============

def _load_users() -> Dict[str, Dict[str, Any]]:
    """加载用户数据。"""
    if _USERS_FILE.exists():
        try:
            with open(_USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_users(users: Dict):
    """保存用户数据。"""
    try:
        _USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[认证] 用户数据保存失败: {e}")


def _load_tokens() -> Dict[str, Dict[str, Any]]:
    """加载 token 映射。"""
    if _TOKENS_FILE.exists():
        try:
            with open(_TOKENS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_tokens(tokens: Dict):
    """保存 token 映射。"""
    try:
        _TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_TOKENS_FILE, "w", encoding="utf-8") as f:
            json.dump(tokens, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[认证] token 数据保存失败: {e}")


def _cleanup_tokens(tokens: Dict) -> Dict:
    """清理过期 token。"""
    now = time.time()
    return {k: v for k, v in tokens.items() if v.get("expires_at", 0) > now}


# ============ 注册 / 登录 ============

def register(username: str, password: str) -> Dict[str, Any]:
    """用户注册。

    Returns:
        成功: {"ok": True, "user": {...}}
        失败: {"ok": False, "error": "..."}
    """
    username = (username or "").strip()
    if not username or len(username) < 2:
        return {"ok": False, "error": "用户名至少 2 个字符"}
    if not password or len(password) < 6:
        return {"ok": False, "error": "密码至少 6 位"}

    users = _load_users()
    if username in users:
        return {"ok": False, "error": "用户名已存在"}

    users[username] = {
        "id": uuid.uuid4().hex[:12],
        "username": username,
        "password_hash": _hash_password(password),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save_users(users)
    print(f"[认证] 新用户注册: {username}")
    return {"ok": True, "user": {"id": users[username]["id"], "username": username}}


def login(username: str, password: str) -> Dict[str, Any]:
    """用户登录，返回 token。

    Returns:
        成功: {"ok": True, "token": "...", "user": {...}}
        失败: {"ok": False, "error": "..."}
    """
    username = (username or "").strip()
    users = _load_users()
    user = users.get(username)

    if not user:
        return {"ok": False, "error": "用户名不存在"}

    if not _verify_password(password, user.get("password_hash", "")):
        return {"ok": False, "error": "密码错误"}

    # 生成 token
    token = secrets.token_urlsafe(32)
    tokens = _cleanup_tokens(_load_tokens())
    tokens[token] = {
        "user_id": user["id"],
        "username": username,
        "expires_at": time.time() + _TOKEN_EXPIRE,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save_tokens(tokens)
    print(f"[认证] 用户登录: {username}")
    return {
        "ok": True,
        "token": token,
        "user": {"id": user["id"], "username": username},
    }


def logout(token: str):
    """退出登录，删除 token。"""
    tokens = _load_tokens()
    if token in tokens:
        del tokens[token]
        _save_tokens(tokens)


def get_user_by_token(token: str) -> Optional[Dict[str, Any]]:
    """根据 token 获取用户信息（验证有效性 + 过期检查）。"""
    if not token:
        return None
    tokens = _cleanup_tokens(_load_tokens())
    token_data = tokens.get(token)
    if not token_data:
        return None
    if token_data.get("expires_at", 0) < time.time():
        return None
    # 保存清理后的 token（删除过期项）
    _save_tokens(tokens)
    return {
        "id": token_data["user_id"],
        "username": token_data["username"],
        "token": token,
    }


# ============ FastAPI 鉴权依赖 ============

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> Dict[str, Any]:
    """FastAPI 依赖：从 Authorization Bearer 头提取 token 并验证用户。

    用法:
        @app.get("/protected")
        async def protected(user: dict = Depends(get_current_user)):
            return {"user": user["username"]}
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="未提供认证 token")
    user = get_user_by_token(credentials.credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="token 无效或已过期")
    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> Optional[Dict[str, Any]]:
    """可选鉴权：有 token 则验证，无 token 返回 None（不报错）。

    用于部分接口需要识别用户但不强制登录的场景。
    """
    if credentials is None or not credentials.credentials:
        return None
    return get_user_by_token(credentials.credentials)
