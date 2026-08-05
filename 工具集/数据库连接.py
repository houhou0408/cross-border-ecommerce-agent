# -*- coding: utf-8 -*-
"""数据库连接助手：统一管理 MySQL 连接，并提供降级策略。

设计要点：
- 演示环境可能未安装 MySQL，因此提供 get_cursor 上下文管理器，
  连接失败时返回 None，调用方据此降级到内置 mock 数据，保证 Demo 可跑通；
- 真实生产环境中，关税/汇率/Listing 均落库持久化。
"""
from contextlib import contextmanager
from typing import Optional

from config import MYSQL_CONFIG


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

    连接失败时 yield None，不抛异常，由调用方处理降级。
    """
    conn = None
    cur = None
    try:
        import mysql.connector
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        cur = conn.cursor(dictionary=True)
        yield cur
        if conn.is_connected():
            conn.commit()
    except Exception as e:  # noqa: BLE001
        # 数据库不可用时静默降级
        print(f"[数据库] 连接失败，将使用内置数据降级: {e}")
        yield None
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None and getattr(conn, "is_connected", lambda: False)():
            try:
                conn.close()
            except Exception:
                pass


def is_db_available() -> bool:
    """快速探测数据库是否可用。"""
    with get_cursor() as cur:
        return cur is not None
