#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抢网脚本（一次性）：登录进桌面后尽快把网连上，连上就退出。

行为
----
1. 开机 / 从休眠进入桌面后启动
2. **立刻**开一个认证页监视线程 —— 因为页面往往比网络先弹出来，
   不等连上就开始盯着，一出现就关掉
3. 同时每 fast_interval 秒探测网络：断网 -> 登录 -> 连上
4. 连上之后：等监视线程收工（页面已关 / 或等到 close_portal_timeout 超时）
5. 退出进程
6. 如果 startup_timeout 秒内始终连不上，兜底退出

注意：这是一次性脚本，连上就退。之后如果再掉线，不会自动重连；
      要重连就靠任务的下一次触发（登录 / 解锁）或手动运行。
      本项目只提供一次性联网，不提供常驻模式。
"""

import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import login_options          # noqa: E402

try:
    from logger import logger             # 仓库里原本就有，写 logs\<日期>.log
except ImportError:                       # 单独拷出来跑时退化成控制台日志
    import logging

    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s][%(levelname)s] %(message)s")
    logger = logging.getLogger("portal")

import ruijie_portal                      # noqa: E402

try:
    from close_portal import start_watch, wait_closed
except Exception:                          # noqa: BLE001
    start_watch = None
    wait_closed = None


_MUTEX_HANDLE = None


def _single_instance() -> bool:
    """Windows 命名互斥体：同一时刻只允许一个实例。"""
    global _MUTEX_HANDLE
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        _MUTEX_HANDLE = k32.CreateMutexW(None, False, "Local\\UESTC-Portal-SingleInstance")
        return k32.GetLastError() != 183          # 183 = ERROR_ALREADY_EXISTS
    except Exception:                              # noqa: BLE001
        return True


def _uptime_seconds() -> float:
    """系统已开机多少秒（用来区分"刚开机"和"休眠唤醒"）。"""
    if sys.platform != "win32":
        return 0.0
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetTickCount64.restype = ctypes.c_ulonglong
        return k32.GetTickCount64() / 1000.0
    except Exception:                          # noqa: BLE001
        return 0.0


def _last_resume_age() -> float | None:
    """距离最近一次"从睡眠/休眠恢复"的秒数；读不到返回 None。"""
    if sys.platform != "win32":
        return None
    try:
        ps = (Path(os.environ.get("SystemRoot", r"C:\Windows"))
              / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")
        out = subprocess.run(
            [str(ps), "-NoProfile", "-NonInteractive", "-Command",
             "(Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-Kernel-Power';Id=107} "
             "-MaxEvents 1 -ErrorAction Stop).TimeCreated.ToUniversalTime().ToString('o')"],
            capture_output=True, text=True, timeout=8,
            creationflags=0x08000000)
        text = (out.stdout or "").strip()
        if not text:
            return None
        # PowerShell 的 o 格式有 7 位小数，兼容 Python 3.10 的 ISO 解析。
        text = re.sub(r"(\.\d{6})\d+", r"\1", text)
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - when).total_seconds()
    except Exception:                              # noqa: BLE001
        return None


def choose_close_mode(uptime: float, resume_age: float | None) -> tuple[str, str]:
    """重启关闭认证窗口；本次开机内有唤醒事件时按其他网页判断。

    日志不可读且已经开机较久时使用 auto，避免把普通解锁当作重启。
    """
    if resume_age is not None and 0 <= resume_age <= uptime:
        return "auto", "本次开机后有睡眠/休眠恢复记录"
    if resume_age is not None or uptime < 120:
        return "window", "重启/开机后，直接关闭认证窗口"
    return "auto", "唤醒记录不可读，按其他网页判断"


def apply_config() -> tuple[str, str]:
    user = login_options['user']
    portal = login_options.get('portal', {})
    if portal.get('base_url'):
        ruijie_portal.PORTAL_BASE = portal['base_url'].rstrip('/')
    if portal.get('page_id'):
        ruijie_portal.DEFAULT_PAGE_ID = portal['page_id']
    return user.user_id, user.passwd


def run() -> int:
    """0 = 连上并正常退出；1 = 超时兜底退出。"""
    username, password = apply_config()
    close_page = bool(login_options.get("close_portal_page", True))
    close_timeout = float(login_options.get("close_portal_timeout", 30))
    close_interval = float(login_options.get("close_portal_interval", 2))
    close_mode, basis = choose_close_mode(_uptime_seconds(), _last_resume_age())
    fast_interval = float(login_options.get("fast_interval", 1))
    startup_timeout = float(login_options.get("startup_timeout", 180))

    logger.info("联网任务启动：%s", ruijie_portal.PORTAL_BASE)
    logger.info("抢网参数：探测间隔 %.0f 秒，最多给 %.0f 秒，连上即退出",
                fast_interval, startup_timeout)
    logger.info("判定依据：%s；认证页关闭方式=%s", basis, close_mode)

    # 关键：页面常常比网络先弹，所以一开始就盯，不等连上
    watching = False
    if close_page and start_watch is not None:
        watching = start_watch(timeout=startup_timeout + close_timeout + 30,
                               interval=close_interval,
                               mode=close_mode, logger=logger)
        if watching:
            logger.info("认证页监视已启动：现在起每 %.0f 秒扫一次，弹出即关", close_interval)

    grant_start = time.monotonic()
    deadline = grant_start + startup_timeout if startup_timeout > 0 else 0.0
    offline_hits = 0
    while True:
        if deadline and time.monotonic() >= deadline:
            logger.error("抢网 %.0f 秒仍未登录成功，兜底退出", startup_timeout)
            return 1
        try:
            if ruijie_portal.is_online():
                logger.info("已联网（本次抢网用了 %.1f 秒）", time.monotonic() - grant_start)
                break
            offline_hits += 1
            logger.info("第 %d 次探测到断网，开始登录", offline_hits)
            if ruijie_portal.login_once(username, password, verbose=False):
                logger.info("登录成功，已通过外网连通性复检")
                break
            logger.warning("登录后外网仍不可达，稍后重试")
            time.sleep(fast_interval)
        except Exception:
            logger.error("异常：\n%s", traceback.format_exc())
            time.sleep(max(fast_interval, 3))

    # 连上了：等监视线程把页面处理完（早关掉的话这里立刻返回）
    if close_page and wait_closed is not None:
        if wait_closed(close_timeout):
            logger.info("认证页已处理")
        else:
            logger.info("等待 %.0f 秒没有再出现认证页", close_timeout)

    logger.info("联网任务完成，进程退出")
    return 0


if __name__ == "__main__":
    if not _single_instance():
        logger.info("已有实例在运行，本进程直接退出")
        sys.exit(0)
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:                                      # noqa: BLE001
        logger.error("未捕获异常：\n%s", traceback.format_exc())
        sys.exit(2)

