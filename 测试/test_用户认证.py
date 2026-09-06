# -*- coding: utf-8 -*-
"""用户认证模块测试：注册 / 登录 / token 生命周期 / 密码哈希安全。

覆盖点（面试讲解重点）：
1. 密码加盐哈希存储，文件里绝不出现明文密码；
2. 注册/登录参数校验（用户名长度、密码长度、重复注册）；
3. token 过期与登出后的失效逻辑；
4. FastAPI 依赖 get_current_user 的 401 行为。
"""
import asyncio
import json
import time

import pytest
from fastapi import HTTPException


# ============ 密码哈希 ============

class Test密码哈希:
    def test_哈希格式为salt_dollar_hash(self, tmp_auth_files):
        stored = tmp_auth_files._hash_password("secret123")
        salt, hash_hex = stored.split("$", 1)
        assert len(salt) == 32          # 16字节hex
        assert len(hash_hex) == 64      # sha256 hex

    def test_相同密码不同盐(self, tmp_auth_files):
        # 每次哈希随机加盐 → 同密码两次结果不同（防彩虹表）
        assert tmp_auth_files._hash_password("abc123") != tmp_auth_files._hash_password("abc123")

    def test_验证密码正确与错误(self, tmp_auth_files):
        stored = tmp_auth_files._hash_password("abc123")
        assert tmp_auth_files._verify_password("abc123", stored) is True
        assert tmp_auth_files._verify_password("abc124", stored) is False

    def test_损坏的哈希格式安全返回False(self, tmp_auth_files):
        assert tmp_auth_files._verify_password("abc123", "没有分隔符") is False
        assert tmp_auth_files._verify_password("abc123", "") is False


# ============ 注册 ============

class Test注册:
    def test_注册成功(self, tmp_auth_files):
        r = tmp_auth_files.register("alice", "pass123")
        assert r["ok"] is True
        assert r["user"]["username"] == "alice"

    def test_密码不明文落盘(self, tmp_auth_files):
        tmp_auth_files.register("alice", "pass123")
        with open(tmp_auth_files._USERS_FILE, encoding="utf-8") as f:
            raw = f.read()
        assert "pass123" not in raw
        assert "password_hash" in raw

    def test_用户名过短拒绝(self, tmp_auth_files):
        assert tmp_auth_files.register("a", "pass123")["ok"] is False

    def test_密码过短拒绝(self, tmp_auth_files):
        assert tmp_auth_files.register("alice", "12345")["ok"] is False

    def test_重复注册拒绝(self, tmp_auth_files):
        tmp_auth_files.register("alice", "pass123")
        r = tmp_auth_files.register("alice", "other456")
        assert r["ok"] is False
        assert "已存在" in r["error"]

    def test_空参数拒绝(self, tmp_auth_files):
        assert tmp_auth_files.register("", "pass123")["ok"] is False
        assert tmp_auth_files.register("alice", "")["ok"] is False


# ============ 登录 / token 生命周期 ============

class Test登录与Token:
    def _setup_user(self, auth):
        auth.register("alice", "pass123")

    def test_登录成功返回token(self, tmp_auth_files):
        self._setup_user(tmp_auth_files)
        r = tmp_auth_files.login("alice", "pass123")
        assert r["ok"] is True
        assert len(r["token"]) >= 32
        assert r["user"]["username"] == "alice"

    def test_密码错误_不泄露用户名是否存在(self, tmp_auth_files):
        self._setup_user(tmp_auth_files)
        r = tmp_auth_files.login("alice", "wrong66")
        assert r["ok"] is False
        # 防用户名枚举：用户不存在与密码错误统一提示
        assert "用户名或密码错误" in r["error"]

    def test_用户名不存在_与密码错误同响应(self, tmp_auth_files):
        r = tmp_auth_files.login("nobody", "pass123")
        assert r["ok"] is False
        assert "用户名或密码错误" in r["error"]

    def test_连续失败触发限速(self, tmp_auth_files, monkeypatch):
        import 基础设施.用户认证 as auth
        self._setup_user(tmp_auth_files)
        # 清空限速计数，保证用例独立
        monkeypatch.setattr(auth, "_login_fails", {})
        for _ in range(5):
            auth.login("alice", "bad-pass")
        r = auth.login("alice", "pass123")  # 即使密码正确也应被锁
        assert r["ok"] is False
        assert r.get("rate_limited") is True

    def test_两次登录token不同(self, tmp_auth_files):
        self._setup_user(tmp_auth_files)
        t1 = tmp_auth_files.login("alice", "pass123")["token"]
        t2 = tmp_auth_files.login("alice", "pass123")["token"]
        assert t1 != t2

    def test_token查回用户(self, tmp_auth_files):
        self._setup_user(tmp_auth_files)
        token = tmp_auth_files.login("alice", "pass123")["token"]
        user = tmp_auth_files.get_user_by_token(token)
        assert user is not None
        assert user["username"] == "alice"

    def test_token过期失效(self, tmp_auth_files):
        self._setup_user(tmp_auth_files)
        token = tmp_auth_files.login("alice", "pass123")["token"]
        # 手动把过期时间改到过去
        with open(tmp_auth_files._TOKENS_FILE, encoding="utf-8") as f:
            tokens = json.load(f)
        tokens[token]["expires_at"] = time.time() - 1
        with open(tmp_auth_files._TOKENS_FILE, "w", encoding="utf-8") as f:
            json.dump(tokens, f)
        assert tmp_auth_files.get_user_by_token(token) is None

    def test_登出后token失效(self, tmp_auth_files):
        self._setup_user(tmp_auth_files)
        token = tmp_auth_files.login("alice", "pass123")["token"]
        tmp_auth_files.logout(token)
        assert tmp_auth_files.get_user_by_token(token) is None

    def test_伪造token返回None(self, tmp_auth_files):
        assert tmp_auth_files.get_user_by_token("forged-token-xyz") is None
        assert tmp_auth_files.get_user_by_token("") is None


# ============ FastAPI 鉴权依赖 ============

class TestFastAPI鉴权依赖:
    def test_无凭据抛401(self, tmp_auth_files):
        from fastapi.security import HTTPAuthorizationCredentials
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(tmp_auth_files.get_current_user(creds))
        assert exc.value.status_code == 401

    def test_无凭据对象抛401(self, tmp_auth_files):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(tmp_auth_files.get_current_user(None))
        assert exc.value.status_code == 401

    def test_无效token抛401(self, tmp_auth_files):
        from fastapi.security import HTTPAuthorizationCredentials
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad-token")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(tmp_auth_files.get_current_user(creds))
        assert exc.value.status_code == 401

    def test_有效token返回用户(self, tmp_auth_files):
        from fastapi.security import HTTPAuthorizationCredentials
        tmp_auth_files.register("alice", "pass123")
        token = tmp_auth_files.login("alice", "pass123")["token"]
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user = asyncio.run(tmp_auth_files.get_current_user(creds))
        assert user["username"] == "alice"

    def test_可选鉴权无token返回None(self, tmp_auth_files):
        assert asyncio.run(tmp_auth_files.get_current_user_optional(None)) is None
