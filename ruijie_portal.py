#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""电子科大 寝室电信 新门户（锐捷 ePortal + CAS SSO）登录实现。

和旧的 BitSrunLogin 完全不同：不是深澜 /cgi-bin/srun_portal，而是
    1) 被 AC 拦截 -> 跳 portal 拿 sessionId / userIp / nasIp
    2) GET  /cas-sso/login?...   取 croypto 与 flowkey
    3) POST /cas-sso/login?...   表单登录（AES-128-ECB 加密密码）
    4) POST /eportal/network/userOnline  让 NAS 放行

用法：
    python ruijie_portal.py --status     # 只看通不通
    python ruijie_portal.py --probe      # 只抓门户跳转参数，不提交账号
    python ruijie_portal.py --login      # 完整登录一次
    python ruijie_portal.py --loop       # 常驻守护（掉线自动重登）
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
import urllib.parse

import requests

from aes_ecb import aes_ecb_encrypt_b64

# ---------------------------------------------------------------- 常量

PORTAL_BASE = "http://110.184.24.61"
# 认证页模板 uuid，抓包里是 5f8dcce7c1904743951c7112e62691b7；换校区/换模板会变
DEFAULT_PAGE_ID = "5f8dcce7c1904743951c7112e62691b7"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36")

# 用来触发 AC 拦截（要求返回 204 且不重定向，最干净）
PROBE_URLS = [
    "http://connect.rom.miui.com/generate_204",
    "http://www.gstatic.com/generate_204",
    "http://connect.rom.miui.com/generate_204?x=1",
]

QW_KEYS = {
    "sessionId": ("sessionid", "session_id", "session"),      # 大小写无关匹配
    "userIp": ("wlanuserip", "userip", "user_ip", "ip"),
    "nasIp": ("nasip", "nas_ip", "wlanacip", "acip"),
    "customPageId": ("custompageid", "custom_page_id", "pageid"),
}


# ---------------------------------------------------------------- 会话

def new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "isPortal": "true",
    })
    return s


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- 第一步：连通性

def is_online(timeout: float = 4.0) -> bool:
    """generate_204 返回 204 且无 Location 才算真的通。"""
    s = new_session()
    for url in PROBE_URLS:
        try:
            r = s.get(url, timeout=timeout, allow_redirects=False)
        except requests.RequestException:
            continue
        if r.status_code == 204 and not r.headers.get("Location"):
            return True
    return False


# ---------------------------------------------------------------- 第二步：拿门户参数

def _as_pairs(text: str) -> dict | None:
    """把 'a=1&b=2' 或 '{"a":1}' 统一成小写 key 的 dict。"""
    text = text.strip()
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(obj, dict):
            return {str(k).lower(): v for k, v in obj.items()}
        return None
    if re.match(r"^[\w.\-]+=", text):
        q = urllib.parse.parse_qs(text, keep_blank_values=True)
        return {k.lower(): v[0] for k, v in q.items()}
    return None


def _decode_flow_params(raw: str) -> dict:
    """flowParams 可能是 base64(JSON)、base64(querystring) 或裸的 querystring。"""
    txt = urllib.parse.unquote(raw).strip()

    if txt.startswith("{"):
        return _as_pairs(txt) or {}

    # 先当 base64 试：注意 'a=1' 这类短串不会命中（'=' 在中部），不会被误判
    if re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", txt) and len(txt) % 4 == 0:
        try:
            decoded = base64.b64decode(txt).decode("utf-8")
        except Exception:
            decoded = ""
        if decoded:
            if decoded.startswith("{"):
                return _as_pairs(decoded) or {}
            if re.match(r"^[\w.\-]+=", decoded):
                return _as_pairs(decoded) or {}

    return _as_pairs(txt) or {}


def parse_portal_url(url: str) -> dict:
    """从 AC 跳转 URL 里抽 sessionId / userIp / nasIp / customPageId。

    兼容两种写法：
      http://portal/portal/entry/pc/authenticate?wlanuserip=..&nasip=..&sessionId=..
      http://portal/portal/entry/pc/authenticate;flowParams=<base64>;from=
    """
    pool: dict[str, str] = {}

    # urlparse 会把 ";" 之后的部分塞进 .params，所以这里手工切，别用 .path
    raw = url.split("#", 1)[0]
    before_q, _, query = raw.partition("?")

    # 1) 矩阵参数（分号段），例如 ;flowParams=xxx;from=
    for seg in before_q.split(";"):
        if "=" in seg:
            k, _, v = seg.partition("=")
            pool[k.strip().lower()] = urllib.parse.unquote(v)

    # 2) 常规 query
    for k, v in urllib.parse.parse_qs(query, keep_blank_values=True).items():
        pool[k.lower()] = v[0]

    # 3) flowParams 里可能还有一层
    for key in ("flowparams", "flow_params"):
        if pool.get(key) and pool[key] not in ("undefined", "null", ""):
            for k, v in _decode_flow_params(pool[key]).items():
                pool.setdefault(k, str(v))

    ctx: dict[str, str] = {}
    for field, aliases in QW_KEYS.items():
        for alias in aliases:
            if pool.get(alias):
                ctx[field] = pool[alias]
                break
    ctx["_raw_pool"] = pool
    ctx["_raw_url"] = url
    return ctx


def _follow_portal_chain(s: requests.Session, start: str, timeout: float,
                         verbose: bool = True) -> dict:
    """从 AC 给的地址一路跟下去，找带 sessionId 的那一跳。

    实测链条：
        /eportal/index.jsp?userip=..&nasip=..     (AC 直接给的)
          -> 302 /portal/portal-main?sessionId=..&userIp=..&nasIp=..&customPageId=..&redirectUrl=..
    sessionId 是门户在这一跳现场生成的，只跟一跳会漏掉。
    """
    cur = start
    chain: list[str] = []
    best: dict = {}
    for _ in range(6):
        chain.append(cur)
        ctx = parse_portal_url(cur)
        if ctx.get("sessionId"):
            ctx["_chain"] = chain
            return ctx
        if ctx.get("userIp") or ctx.get("nasIp"):
            best = dict(ctx)
        if PORTAL_BASE.split("//")[1] not in cur:
            break
        try:
            r = s.get(cur, allow_redirects=False, timeout=timeout)
        except requests.RequestException as exc:
            if verbose:
                _log(f"  跟链失败 {cur[:80]}: {exc}")
            break
        nxt = r.headers.get("Location") or ""
        if verbose:
            _log(f"  链 {len(chain)}: {r.status_code} -> {nxt[:140] or '(无跳转)'}")
        if not nxt:
            break
        cur = urllib.parse.urljoin(cur, nxt)
    best["_chain"] = chain
    return best


def discover(timeout: float = 6.0, verbose: bool = True) -> dict:
    """触发 AC 拦截，跟着跳转链拿到门户参数。已被放行则抛 RuntimeError。"""
    s = new_session()
    last_err = "没有拿到跳转"
    for url in PROBE_URLS:
        try:
            r = s.get(url, timeout=timeout, allow_redirects=False)
        except requests.RequestException as exc:
            last_err = f"{url} 请求失败: {exc}"
            continue

        if r.status_code == 204 and not r.headers.get("Location"):
            raise RuntimeError("当前已经在线，不需要登录")

        loc = r.headers.get("Location") or ""
        if not loc:
            m = re.search(r'''location\.(?:href|replace)\s*=?\s*["']([^"']+)["']''', r.text or "")
            loc = m.group(1) if m else ""
        if verbose:
            _log(f"probe {url} -> {r.status_code} {loc[:160] or '(无 Location)'}")
        if not loc:
            last_err = f"{url} 返回 {r.status_code} 但没有 Location，可能已放行或 AC 行为不同"
            continue

        ctx = _follow_portal_chain(s, urllib.parse.urljoin(url, loc), timeout, verbose)
        if ctx.get("sessionId"):
            return ctx
        last_err = f"跳转链里没有 sessionId，最后一跳: {(ctx.get('_chain') or ['?'])[-1]}"
    raise RuntimeError(last_err)


# ---------------------------------------------------------------- 第三步：CAS 登录

def _cas_url(ctx: dict) -> str:
    q = {
        "flowSessionId": ctx.get("sessionId", ""),
        "customPageId": ctx.get("customPageId", DEFAULT_PAGE_ID),
        "preview": "false",
        "appType": "normal",
        "language": "zh-CN",
        "timer": str(int(time.time() * 1000)),
        "nasIp": ctx.get("nasIp", ""),
        "userIp": ctx.get("userIp", ""),
        "accept-language": "zh-CN",
    }
    return f"{PORTAL_BASE}/cas-sso/login?" + urllib.parse.urlencode(q)


def fetch_cas_tokens(s: requests.Session, ctx: dict) -> tuple[str, str, str]:
    """返回 (croypto, execution, login_url)。"""
    url = _cas_url(ctx)
    r = s.get(url, timeout=8)
    r.raise_for_status()
    html = r.text

    def grab(pattern: str) -> str:
        m = re.search(pattern, html, re.S)
        return m.group(1).strip() if m else ""

    croypto = grab(r'id="login-croypto"[^>]*>\s*([^<]+)')
    flowkey = grab(r'id="login-page-flowkey"[^>]*>\s*([^<]+)')
    vendor = grab(r'id="recaptchaVendor"[^>]*>\s*([^<]+)')

    if not croypto or not flowkey:
        raise RuntimeError(
            "CAS 页面解析失败（没找到 login-croypto / login-page-flowkey）。"
            f"status={r.status_code} len={len(html)} url={url}；"
            "多半是 sessionId 或 customPageId 不对")
    _log(f"CAS 页面 OK: croypto={croypto} flowkey={flowkey[:40]}... captcha_vendor={vendor or '-'}")
    return croypto, flowkey, url


def cas_login(s: requests.Session, ctx: dict, username: str, password: str) -> str:
    croypto, flowkey, url = fetch_cas_tokens(s, ctx)
    data = {
        "username": username,
        "password": aes_ecb_encrypt_b64(croypto, password),
        "croypto": croypto,
        "captcha_payload": aes_ecb_encrypt_b64(croypto, "{}"),
        "captcha_code": "",
        "type": "UsernamePassword",
        "_eventId": "submit",
        "execution": flowkey,
        "geolocation": "",
    }
    r = s.post(url, data=data, timeout=10, allow_redirects=False)
    loc = r.headers.get("Location", "")
    if r.status_code in (301, 302, 303) and "ticket=" in loc:
        ticket = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query).get("ticket", [""])[0]
        _log(f"CAS 登录成功，ticket={ticket[:40]}...")
        return ticket

    if r.status_code >= 500:
        # 实测：密码对、但 flowSessionId 是编的或已过期时，CAS 返回 500 而不是 401
        raise RuntimeError(
            f"CAS 返回 {r.status_code}：账号密码这一步过了，但 flowSessionId 无效或已过期。"
            "session 必须来自 AC 拦截后的跳转，自己生成的不行")

    # 失败：尽量把服务端的话捞出来
    reason = ""
    try:
        j = r.json()
        reason = j.get("message") or j.get("msg") or json.dumps(j, ensure_ascii=False)[:200]
    except ValueError:
        m = re.search(r'id="error[^"]*"[^>]*>\s*([^<]{1,200})', r.text or "")
        reason = m.group(1).strip() if m else (r.text or "")[:200]
    raise RuntimeError(f"CAS 登录失败 status={r.status_code} reason={reason}")


# ---------------------------------------------------------------- 第四步：让 NAS 放行

def user_online(s: requests.Session, ctx: dict) -> dict:
    r = s.post(f"{PORTAL_BASE}/eportal/network/userOnline",
               json={"sessionId": ctx.get("sessionId")}, timeout=10)
    try:
        return r.json()
    except ValueError:
        raise RuntimeError(f"userOnline 返回非 JSON: {r.status_code} {r.text[:200]}")


def online_info(s: requests.Session, ctx: dict) -> dict:
    r = s.get(f"{PORTAL_BASE}/eportal/adaptor/getOnlineUserInfo",
              params={"sessionId": ctx.get("sessionId", ""), "_t": int(time.time() * 1000)}, timeout=8)
    try:
        return (r.json().get("data") or {}).get("portalOnlineUserInfo") or {}
    except ValueError:
        return {}


# ---------------------------------------------------------------- 对外主流程

def login_once(username: str, password: str, verbose: bool = True,
               portal_url: str | None = None) -> bool:
    s = new_session()
    if portal_url:
        ctx = parse_portal_url(portal_url)
        if not ctx.get("sessionId"):
            raise RuntimeError("你给的 URL 里没有 sessionId，把浏览器地址栏那一整串发我")
    else:
        try:
            ctx = discover(verbose=verbose)
        except RuntimeError as exc:
            if "已经在线" in str(exc):
                if verbose:
                    _log("当前已经在线，不需要登录")
                return True
            raise
    if verbose:
        _log(f"门户参数: sessionId={ctx.get('sessionId')} userIp={ctx.get('userIp')} "
             f"nasIp={ctx.get('nasIp')} page={ctx.get('customPageId')}")
    cas_login(s, ctx, username, password)
    res = user_online(s, ctx)
    data = res.get("data") or {}
    if verbose:
        _log(f"userOnline: {json.dumps(res, ensure_ascii=False)[:300]}")
    # userOnline 里的 data.online 才是权威判断；getOnlineUserInfo 有时返回过期视图
    online = bool(data.get("online"))
    if not online and verbose:
        info = online_info(s, ctx)
        _log(f"onlineInfo 参考: {info.get('result')} {info.get('message') or ''}")
    return online


def wait_offline(retries: int = 3) -> None:
    for _ in range(retries):
        if not is_online():
            return
        time.sleep(3)


def loop(username: str, password: str, interval: int = 30) -> None:
    _log("守护启动")
    while True:
        try:
            if is_online():
                time.sleep(interval)
                continue
            _log("检测到断网，开始登录")
            ok = login_once(username, password)
            if ok:
                _log("登录成功")
            else:
                _log("登录流程跑完但未确认在线，30s 后重试")
                time.sleep(30)
        except Exception as exc:                      # noqa: BLE001
            _log(f"出错: {exc}")
            time.sleep(20)


# ---------------------------------------------------------------- CLI

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="UESTC 电信门户自动登录（锐捷 ePortal + CAS）")
    ap.add_argument("--status", action="store_true", help="只检查是否在线")
    ap.add_argument("--probe", action="store_true", help="只抓门户跳转参数，不提交账号")
    ap.add_argument("--login", action="store_true", help="登录一次")
    ap.add_argument("--loop", action="store_true", help="常驻守护")
    ap.add_argument("-u", "--userid", help="宽带账号（手机号）")
    ap.add_argument("-p", "--password", help="宽带密码")
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--url", help="已知的门户跳转 URL（跳过自动探测）")
    args = ap.parse_args(argv)

    if args.status:
        print("online" if is_online() else "offline")
        return 0

    if args.probe:
        try:
            if args.url:
                ctx = parse_portal_url(args.url)
            else:
                ctx = discover()
            pool = ctx.pop("_raw_pool", {})
            print(json.dumps(ctx, ensure_ascii=False, indent=2))
            print("--- 跳转里的全部参数 ---")
            print(json.dumps(pool, ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:                      # noqa: BLE001
            print(f"probe 失败: {exc}")
            return 1

    if not args.userid or not args.password:
        ap.error("--login / --loop 需要 -u 和 -p")

    if args.login:
        return 0 if login_once(args.userid, args.password, portal_url=args.url) else 2

    if args.loop:
        loop(args.userid, args.password, args.interval)
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
