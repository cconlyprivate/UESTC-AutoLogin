#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""登录一次，用来验证配置对不对。

用法：
    python login_once.py                       # 自动探测 AC 跳转
    python login_once.py "http://110.184.24.61/portal/entry/pc/authenticate;..."   # 手动给跳转 URL

第二种用法是给「自动探测取不到 sessionId」时兜底用的：
断网后浏览器会跳到门户，把地址栏那一整串复制下来贴进参数即可。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import login_options          # noqa: E402
import ruijie_portal                      # noqa: E402

try:
    from close_portal import close_portal_page   # 登录成功后关掉浏览器里的认证页
except Exception:                                # noqa: BLE001
    close_portal_page = None


def main(argv: list[str]) -> int:
    user = login_options['user']
    portal = login_options.get('portal', {})
    if portal.get('base_url'):
        ruijie_portal.PORTAL_BASE = portal['base_url'].rstrip('/')
    if portal.get('page_id'):
        ruijie_portal.DEFAULT_PAGE_ID = portal['page_id']

    portal_url = argv[0] if argv else None
    ok = ruijie_portal.login_once(user.user_id, user.passwd, portal_url=portal_url)
    print("RESULT:", "online" if ok else "failed")
    if ok and login_options.get("close_portal_page", True) and close_portal_page:
        for line in close_portal_page():
            print("   ", line)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
