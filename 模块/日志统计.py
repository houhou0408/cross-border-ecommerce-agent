# -*- coding: utf-8 -*-
"""日志统计模块：记录每次 Agent 调用，并产出可观测性统计。

职责：
1. 日志落盘（文件日志，便于排查）；
2. 查询日志写入 MySQL query_log 表（库不可用时仅落文件）；
3. 提供统计接口：调用量、平均耗时、幻觉拦截率、工具使用频次。
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from config import LOG_DIR
from 工具集.数据库连接 import get_cursor


def _setup_file_logger() -> logging.Logger:
    """配置文件日志。"""
    logger = logging.getLogger("跨境Agent")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    log_file = LOG_DIR / f"agent_{datetime.now().strftime('%Y%m%d')}.log"
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(fh)
    # 同时输出到控制台
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    logger.addHandler(sh)
    # 子 logger（跨境Agent.xxx）消息向父级传播，统一走这套 handler
    logging.getLogger("跨境Agent").propagate = False
    return logger


def get_file_logger(name: str = "") -> logging.Logger:
    """获取挂载到全局文件日志体系的 logger（各业务模块统一日志入口）。

    Args:
        name: 模块名（如 "视频生成"），生成子 logger "跨境Agent.视频生成"；
              留空返回根 logger。

    说明：日志同时落盘 LOG_DIR/agent_YYYYMMDD.log 与控制台；
    子 logger 消息会传播到 "跨境Agent" 根 logger 的 handler，无需重复配置。
    """
    _setup_file_logger()
    if name:
        return logging.getLogger(f"跨境Agent.{name}")
    return logging.getLogger("跨境Agent")


class 日志统计器:
    """日志记录与统计。"""

    def __init__(self):
        self.logger = _setup_file_logger()
        self._mem_buffer: List[Dict[str, Any]] = []  # 库不可用时的内存缓冲

    def log_query(self, payload: Dict[str, Any]):
        """记录一次 Agent 调用。

        payload 字段见 Agent调度.orchestrate 返回。
        """
        # 1) 文件日志
        self.logger.info(
            "session=%s latency=%sms grounded=%s score=%s tools=%s | query_buf=%s",
            payload.get("session_id"),
            payload.get("latency_ms"),
            payload.get("grounded"),
            payload.get("score"),
            [t["tool"] for t in payload.get("tools_used", [])],
            (payload.get("raw_answer", "") or "")[:80].replace("\n", " "),
        )

        # 2) 内存缓冲（统计用，库不可用时也能统计）
        self._mem_buffer.append(payload)

        # 3) 写入 MySQL
        self._write_to_db(payload)

    def _write_to_db(self, payload: Dict[str, Any]):
        """写入 MySQL query_log 表。"""
        with get_cursor() as cur:
            if cur is None:
                return
            tools = json.dumps(
                [t["tool"] for t in payload.get("tools_used", [])],
                ensure_ascii=False,
            )
            cur.execute(
                "INSERT INTO query_log (session_id, user_query, agent_answer, tools_used, "
                "retrievals, grounded, latency_ms) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    payload.get("session_id"),
                    payload.get("raw_answer", "")[:500],  # 简化：用答案前缀；真实场景应存原始query
                    payload.get("answer", "")[:5000],
                    tools,
                    payload.get("retrievals"),
                    1 if payload.get("grounded") else 0,
                    payload.get("latency_ms"),
                ),
            )

    def stats(self) -> Dict[str, Any]:
        """产出运行统计（基于内存缓冲，演示用）。返回结构始终一致，便于前端/接口消费。"""
        buf = self._mem_buffer
        if not buf:
            return {
                "total_calls": 0,
                "avg_latency_ms": 0,
                "avg_grounding_score": 0.0,
                "hallucination_block_rate": 0.0,
                "tool_frequency": {},
                "last_session": None,
            }
        total = len(buf)
        avg_latency = sum(b["latency_ms"] for b in buf) / total
        grounded_count = sum(1 for b in buf if b["grounded"])
        hallucination_rate = 1 - grounded_count / total

        # 工具使用频次
        tool_freq: Dict[str, int] = {}
        for b in buf:
            for t in b.get("tools_used", []):
                tool_freq[t["tool"]] = tool_freq.get(t["tool"], 0) + 1

        avg_score = sum(b["score"] for b in buf) / total
        return {
            "total_calls": total,
            "avg_latency_ms": round(avg_latency, 1),
            "avg_grounding_score": round(avg_score, 3),
            "hallucination_block_rate": round(hallucination_rate, 3),
            "tool_frequency": tool_freq,
            "last_session": buf[-1].get("session_id"),
        }

    def dump_buffer(self, path: Path = None):
        """把内存缓冲导出为 JSON（便于生成测试日志）。"""
        path = path or (LOG_DIR / "调用记录.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._mem_buffer, f, ensure_ascii=False, indent=2)
        self.logger.info("[日志统计] 已导出调用记录 -> %s", path)


_logger_instance: Optional[日志统计器] = None


def get_logger() -> 日志统计器:
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = 日志统计器()
    return _logger_instance
