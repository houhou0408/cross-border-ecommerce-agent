# -*- coding: utf-8 -*-
"""数据库连接助手：统一管理 MySQL 连接，并提供降级策略。

设计要点：
- 演示环境可能未安装 MySQL，因此提供 get_cursor 上下文管理器，
  连接失败时返回 None，调用方据此降级到内置 mock 数据，保证 Demo 可跑通；
- 真实生产环境中，关税/汇率/Listing 均落库持久化；
- 连接失败日志去重：首次 WARNING、后续 DEBUG（防刷屏），恢复后复位；
- with 体内的 SQL 异常正常上抛，不再被吞（便于定位真实错误）。
"""
import logging
from contextlib import contextmanager

from config import MYSQL_CONFIG

logger = logging.getLogger("跨境Agent.数据库连接")

# 连接失败日志去重状态：首次失败记 WARNING，持续失败降为 DEBUG，恢复后复位
_db_fail_logged = False


@contextmanager
def get_cursor():
    """获取 MySQL 游标上下文。

    用法:
        with get_cursor() as cur:
            if cur is None:
                # 降级逻辑
            else:
                cur.execute("SELECT ...")
                rows = cur.fetchall()

    连接失败时 yield None，不抛异常，由调用方处理降级；
    连接成功后，with 体内的 SQL 异常正常上抛（不吞），成功才 commit。
    """
    global _db_fail_logged
    conn = None
    cur = None

    # ---- 阶段1：建立连接（失败 → yield None 降级）----
    try:
        import mysql.connector
        conn = mysql.connector.connect(
            **MYSQL_CONFIG,
            connection_timeout=3,
        )
        cur = conn.cursor(dictionary=True)
    except Exception as e:  # noqa: BLE001
        if not _db_fail_logged:
            logger.warning("[数据库] 连接失败，将使用内置数据降级: %s", e)
            _db_fail_logged = True
        else:
            logger.debug("[数据库] 仍不可用（已降级运行）: %s", e)
        yield None
        return

    if _db_fail_logged:
        logger.info("[数据库] 连接已恢复")
        _db_fail_logged = False

    # ---- 阶段2：使用连接（SQL 异常上抛，成功才 commit）----
    try:
        yield cur
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def is_db_available() -> bool:
    """快速探测数据库是否可用（3s 超时，供 /health 使用）。"""
    with get_cursor() as cur:
        return cur is not None
