# -*- coding: utf-8 -*-
"""数据库连接助手：统一管理 MySQL 连接（连接池），并提供降级策略。

设计要点：
- 演示环境可能未安装 MySQL，因此提供 get_cursor 上下文管理器，
  连接失败时返回 None，调用方据此降级到内置 mock 数据，保证 Demo 可跑通；
- 真实生产环境中，关税/汇率/Listing 均落库持久化；
- 连接复用：mysql.connector 连接池（懒创建），池不可用/耗尽时回退直连；
  一次 /ask 会触发多次短查询，连接池避免每次开关连接的开销；
- 连接失败日志去重：首次 WARNING、后续 DEBUG（防刷屏），恢复后复位；
- with 体内的 SQL 异常正常上抛，不再被吞（便于定位真实错误）。
"""
import logging
import threading
from contextlib import contextmanager

from config import MYSQL_CONFIG

logger = logging.getLogger("跨境Agent.数据库连接")

# 连接失败日志去重状态：首次失败记 WARNING，持续失败降为 DEBUG，恢复后复位
_db_fail_logged = False

# 连接池（懒创建；初始化失败则永久降级为直连，不再反复尝试）
_POOL = None
_POOL_LOCK = threading.Lock()
_POOL_SIZE = 8
_POOL_DISABLED = False


def _get_pool():
    """获取（或创建）MySQL 连接池；不可用时返回 None。

    池创建是幂等的：加锁保证并发下只建一次。初始化失败（驱动缺失/配置错误/
    测试注入假驱动无 pooling 模块）记录一次日志后置 _POOL_DISABLED，
    后续调用直接跳过，避免每次请求重复尝试与刷日志。
    """
    global _POOL, _POOL_DISABLED
    if _POOL is not None:
        return _POOL
    if _POOL_DISABLED:
        return None
    with _POOL_LOCK:
        if _POOL is not None:
            return _POOL
        if _POOL_DISABLED:
            return None
        try:
            from mysql.connector import pooling
            _POOL = pooling.MySQLConnectionPool(
                pool_name="crossborder_agent",
                pool_size=_POOL_SIZE,
                pool_reset_session=True,
                **MYSQL_CONFIG,
                connection_timeout=3,
            )
            return _POOL
        except Exception as e:  # noqa: BLE001
            _POOL_DISABLED = True
            logger.info("[数据库] 连接池初始化失败，改用直连: %s", e)
            return None


def _open_connection():
    """打开一条可用连接：优先从池取，池不可用/耗尽则直连。"""
    import mysql.connector
    pool = _get_pool()
    if pool is not None:
        try:
            return pool.get_connection()
        except Exception:  # noqa: BLE001  # 池耗尽(PoolError)或连接失效 → 直连兜底
            logger.debug("[数据库] 连接池取用失败，本次回退直连")
    return mysql.connector.connect(
        **MYSQL_CONFIG,
        connection_timeout=3,
    )


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
    池化连接的 close() 等价于归还连接池。
    """
    global _db_fail_logged
    conn = None
    cur = None

    # ---- 阶段1：建立连接（失败 → yield None 降级）----
    try:
        conn = _open_connection()
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
