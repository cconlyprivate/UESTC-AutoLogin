#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""断网自测：一次跑完「抓跳转链 -> 解析 -> 登录 -> 验证」，全过程写进日志。

用法（断网后在项目目录运行）：
    python selftest.py
    python selftest.py --no-login     # 只探测，不提交账号

日志写在 logs\\selftest-<时间>.txt，重新联网后把这个文件发出来即可。
"""

from __future__ import annotations

import json
import socket
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from config import login_options          # noqa: E402
import ruijie_portal as rp                # noqa: E402

REPORT: list[str] = []


def emit(line: str = "") -> None:
    print(line, flush=True)
    REPORT.append(line)


def local_ipv4() -> list[str]:
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("114.114.114.114", 53))
        ip = s.getsockname()[0]
        if ip not in ips:
            ips.append(ip)
        s.close()
    except OSError:
        pass
    return ips


def wait_offline(max_rounds: int = 3, gap: int = 8) -> bool:
    for i in range(1, max_rounds + 1):
        if not rp.is_online():
            emit(f"[离线检查] 第 {i} 轮：已离线，开始抓跳转")
            return True
        emit(f"[离线检查] 第 {i} 轮：仍然在线（AC 会话可能还没过期），{gap}s 后重试")
        time.sleep(gap)
    return False


def main(argv: list[str]) -> int:
    do_login = "--no-login" not in argv
    user = login_options["user"]
    portal = login_options.get("portal", {})
    if portal.get("base_url"):
        rp.PORTAL_BASE = portal["base_url"].rstrip("/")
    if portal.get("page_id"):
        rp.DEFAULT_PAGE_ID = portal["page_id"]

    emit("=" * 70)
    emit(f"UESTC 电信门户 断网自测    {time.strftime('%Y-%m-%d %H:%M:%S')}")
    emit(f"主机: {socket.gethostname()}   本机 IPv4: {', '.join(local_ipv4()) or '未取到'}")
    emit(f"门户: {rp.PORTAL_BASE}   认证页模板: {rp.DEFAULT_PAGE_ID}")
    emit("=" * 70)

    if not wait_offline():
        emit("")
        emit("[结论] 一直是在线状态，AC 不会拦，抓不到跳转。")
        emit("       请先确认网线已拔出 / WiFi 已断开 / 门户已注销，再重跑本脚本。")
        return 3

    emit("")
    emit("[1] 抓 AC 跳转链")
    try:
        ctx = rp.discover(verbose=True)
    except RuntimeError as exc:
        emit("")
        emit(f"[结论] 抓不到可用的门户会话: {exc}")
        emit("       把本文件发出来即可。")
        return 4

    chain = ctx.pop("_chain", [])
    pool = ctx.pop("_raw_pool", {})
    ctx.pop("_raw_url", None)

    emit("")
    emit("[2] 跳转链（最后一跳才是带 sessionId 的）")
    for i, hop in enumerate(chain, 1):
        emit(f"  [{i}] {hop}")

    emit("")
    emit("[3] 解析结果")
    emit("  " + json.dumps(ctx, ensure_ascii=False))
    emit("  全部参数:")
    for k, v in pool.items():
        emit(f"    {k} = {v}")

    if not ctx.get("sessionId"):
        emit("")
        emit("[结论] 链里没有 sessionId，请把 [2] 的跳转链发我。")
        return 5

    if not do_login:
        emit("")
        emit("[4] 按 --no-login 跳过登录")
        return 0

    emit("")
    emit("[4] 登录")
    s = rp.new_session()
    try:
        ticket = rp.cas_login(s, ctx, user.user_id, user.passwd)
        emit(f"  CAS 通过，ticket = {ticket[:50]}")
        res = rp.user_online(s, ctx)
        emit("  userOnline -> " + json.dumps(res, ensure_ascii=False))
        data = res.get("data") or {}
        emit(f"  online = {data.get('online')}   userIndex = {data.get('userIndex')}")
        if not data.get("online"):
            emit("  注意：userOnline 没返回 online=true，继续复检连通性")
    except Exception:                                   # noqa: BLE001
        emit("  登录失败：")
        emit(traceback.format_exc())
        emit("")
        emit("[结论] 登录没成功。请用浏览器手动登录恢复网络，再把本文件发出来。")
        return 6

    emit("")
    emit("[5] 复检连通性")
    time.sleep(2)
    online = rp.is_online()
    emit(f"  is_online = {online}")
    emit("")
    emit("[结论] " + ("登录成功，网络已恢复。" if online
                       else "userOnline 说在线但仍连不上，问题在 NAS 放行，日志里有原始返回。"))
    return 0 if online else 7


if __name__ == "__main__":
    code = 9
    try:
        code = main(sys.argv[1:])
    except Exception:                                   # noqa: BLE001
        emit("脚本自身异常：")
        emit(traceback.format_exc())
    finally:
        logs = HERE / "logs"
        logs.mkdir(exist_ok=True)
        out = logs / f"selftest-{time.strftime('%Y%m%d-%H%M%S')}.txt"
        out.write_text("\n".join(REPORT), encoding="utf-8")
        print()
        print(f"报告已保存: {out}")
        print(f"退出码: {code}")
    sys.exit(code)
