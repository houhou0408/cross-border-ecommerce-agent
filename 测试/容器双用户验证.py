# -*- coding: utf-8 -*-
"""容器级双用户隔离验证脚本（走真实 HTTP + 真实 MySQL）。"""
import requests

BASE = "http://localhost:8000"

# 1. 注册并登录两个用户
import time
tag = str(int(time.time()))
users = {}
for name in ("alice", "bob"):
    r = requests.post(f"{BASE}/auth/register",
                      json={"username": f"e2e_{name}_{tag}", "password": "pass123"}).json()
    assert r["ok"], r
    r = requests.post(f"{BASE}/auth/login",
                      json={"username": f"e2e_{name}_{tag}", "password": "pass123"}).json()
    assert r["ok"], r
    users[name] = {"token": r["token"], "id": r["user"]["id"],
                   "headers": {"Authorization": f"Bearer {r['token']}"}}

# 2. alice 建 2 个会话，bob 建 1 个
for _ in range(2):
    assert requests.post(f"{BASE}/sessions", headers=users["alice"]["headers"]).status_code == 200
sid_b = requests.post(f"{BASE}/sessions", headers=users["bob"]["headers"]).json()["id"]

a_sessions = requests.get(f"{BASE}/sessions", headers=users["alice"]["headers"]).json()["sessions"]
b_sessions = requests.get(f"{BASE}/sessions", headers=users["bob"]["headers"]).json()["sessions"]
assert len(a_sessions) == 2, f"alice 应有 2 个会话，实际 {len(a_sessions)}"
assert len(b_sessions) == 1, f"bob 应有 1 个会话，实际 {len(b_sessions)}"
assert {s["id"] for s in a_sessions}.isdisjoint({s["id"] for s in b_sessions})
print("[PASS] 会话列表按用户隔离")

# 3. bob 读/删 alice 的会话被拒
sid_a = a_sessions[0]["id"]
r = requests.get(f"{BASE}/sessions/{sid_a}", headers=users["bob"]["headers"])
assert r.status_code == 404, f"bob 读 alice 会话应 404，实际 {r.status_code}"
r = requests.delete(f"{BASE}/sessions/{sid_a}", headers=users["bob"]["headers"]).json()
assert r["deleted"] is False
print("[PASS] 越权读/删会话被拒")

# 4. alice 读取/删除自己的会话正常
assert requests.get(f"{BASE}/sessions/{sid_a}", headers=users["alice"]["headers"]).status_code == 200
assert requests.delete(f"{BASE}/sessions/{sid_a}", headers=users["alice"]["headers"]).json()["deleted"] is True
print("[PASS] 本人会话读写删正常")

# 5. 视频任务归属（无 Key 走降级，任务仍入库）
r = requests.post(f"{BASE}/video/text-to-video", json={"prompt": "端到端验证"},
                  headers=users["alice"]["headers"]).json()
assert "task_id" in r, r
a_tasks = requests.get(f"{BASE}/video/tasks", headers=users["alice"]["headers"]).json()["tasks"]
b_tasks = requests.get(f"{BASE}/video/tasks", headers=users["bob"]["headers"]).json()["tasks"]
assert any(t["id"] == r["task_id"] for t in a_tasks), "alice 应看到自己的任务"
assert not any(t["id"] == r["task_id"] for t in b_tasks), "bob 不应看到 alice 的任务"
print("[PASS] 视频任务按用户隔离（MySQL 入库）")

# 6. 数据库层验证：任务确实写进了 MySQL（而非 JSON 降级）
import subprocess
out = subprocess.run(
    ["docker", "exec", "cb-agent-mysql", "mysql", "-uroot", "-p316624",
     "cross_border_agent", "-e",
     f"SELECT id, user_id, status FROM video_task WHERE id='{r['task_id']}';"],
    capture_output=True, text=True)
assert r["task_id"] in out.stdout, f"任务应写入 MySQL: {out.stdout} {out.stderr}"
print("[PASS] 任务记录真实写入 MySQL video_task 表")

# 7. bob 用 alice 的 session_id 提问被拒
r = requests.post(f"{BASE}/ask",
                  json={"query": "hi", "session_id": a_sessions[1]["id"]},
                  headers=users["bob"]["headers"]).json()
assert "error" in r, r
print("[PASS] /ask 携带他人会话被拒")

print("\n全部端到端验证通过 ✓")
