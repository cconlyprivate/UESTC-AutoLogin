#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""盯住浏览器里的"网络认证"页面：一出现就关掉，超时就放弃。

行为约定
--------
- 后台线程，每 N 秒扫一次浏览器窗口，命中就关掉**那一个标签**（不关浏览器、不碰别的标签）
- 最多监视 M 秒：这段时间里页面一直没弹出来，就安静地放弃，不报错
- 同一时刻只跑一个监视线程（重复调用会被忽略）
- 认不出页面就什么都不做

为什么不能按标题认
------------------
门户页 /portal/entry/pc/authenticate 服务端返回的 <title> 是空的（只有反调试 JS），
浏览器渲染后才变成「连网认证」。所以 close_portal_tab.ps1 里同时用了
"地址栏 URL" 和 "标签/窗口标题" 两套判据。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PS1 = HERE / "close_portal_tab.ps1"
PS_EXE = (Path(os.environ.get("SystemRoot", r"C:\Windows"))
          / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")
CREATE_NO_WINDOW = 0x08000000

_lock = threading.Lock()
_closed = threading.Event()   # 本次会话是否已经关掉过认证页


def close_portal_page(timeout: float = 25.0, mode: str = "window") -> list[str]:
    """扫一次；有关掉的页面就返回动作描述列表，没有就返回空列表。"""
    if sys.platform != "win32":
        return []
    if not PS1.is_file() or not PS_EXE.is_file():
        return []
    try:
        proc = subprocess.run(
            [str(PS_EXE), "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
             "-File", str(PS1), "-CloseWindow", mode],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=CREATE_NO_WINDOW,
        )
    except Exception:                       # noqa: BLE001  超时/被拦都不该影响登录
        return []

    actions = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith(("CLOSE_TAB", "CLOSE_CTRLW", "FAIL")):
            actions.append(line.replace("\t", " | "))
    return actions


def wait_and_close(timeout: float = 30.0, interval: float = 2.0,
                   mode: str = "window", logger=None) -> bool:
    """同步等待并关闭认证页：命中返回 True，超时返回 False。"""
    deadline = time.monotonic() + timeout
    warned = False
    while time.monotonic() < deadline:
        acts = close_portal_page(mode=mode)
        done = [a for a in acts if a.startswith(("CLOSE_TAB", "CLOSE_WINDOW", "CLOSE_CTRLW"))]
        failed = [a for a in acts if a.startswith("FAIL")]
        if done:
            _closed.set()
            if logger:
                logger.info("已关闭认证页：%s", "; ".join(done))
            return True
        if failed and not warned:
            warned = True
            if logger:
                logger.warning("发现认证页但没关掉，继续重试：%s", "; ".join(failed))
        time.sleep(interval)
    if logger:
        logger.info("等待 %.0f 秒没有需要关闭的认证页", timeout)
    return False


def _watch(timeout: float, interval: float, mode: str, logger) -> None:
    deadline = time.monotonic() + timeout
    warned = False
    while time.monotonic() < deadline:
        acts = close_portal_page(mode=mode)
        done = [a for a in acts if a.startswith(("CLOSE_TAB", "CLOSE_WINDOW", "CLOSE_CTRLW"))]
        failed = [a for a in acts if a.startswith("FAIL")]
        if done:
            _closed.set()
            if logger:
                logger.info("已关闭认证页：%s", "; ".join(done))
            return
        if failed and not warned:
            warned = True
            if logger:
                logger.warning("发现认证页但没关掉，继续重试：%s", "; ".join(failed))
        time.sleep(interval)
    if logger:
        logger.info("监视 %.0f 秒没等到可关闭的认证页，停止监视", timeout)


def start_watch(timeout: float = 120.0, interval: float = 2.0, mode: str = "window", logger=None) -> bool:
    """在后台开始监视（最多 timeout 秒）。已经在看的时候返回 False。"""
    if sys.platform != "win32" or not PS1.is_file() or not PS_EXE.is_file():
        return False
    if not _lock.acquire(blocking=False):
        return False
    _closed.clear()

    def runner() -> None:
        try:
            _watch(timeout, interval, mode, logger)
        finally:
            _lock.release()

    threading.Thread(target=runner, name="portal-watch", daemon=True).start()
    return True


if __name__ == "__main__":
    # 手动调试：python close_portal.py [超时秒数]
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    print("开始监视 %.0f 秒…" % limit)
    got = close_portal_page()
    if got:
        print("\n".join(got))
    else:
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            got = close_portal_page()
            if got:
                print("\n".join(got))
                break
            time.sleep(2)
        else:
            print("NONE  (超时，没有发现认证页)")


def was_closed() -> bool:
    """本次会话是否已经成功关掉过认证页。"""
    return _closed.is_set()


def wait_closed(timeout: float) -> bool:
    """等认证页被关掉（最多 timeout 秒），成功返回 True。"""
    return _closed.wait(timeout)