#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""配置：宽带账号、门户地址、抢网参数、认证页处理参数。

注意：上传到 GitHub 前请确认 user 里不是真实账号密码。
"""

from collections import namedtuple

User = namedtuple('User', ['user_id', 'passwd', 'wechat_openid'])

login_options = {
    # 宽带账号 + 密码（就是门户登录页要填的那两个），换成你自己的
    'user': User('你的宽带账号', '你的密码', None),

    # 门户地址与认证页模板；换校区 / 门户改版时可能需要调整 page_id
    'portal': {
        'base_url': 'http://110.184.24.61',
        'page_id': '5f8dcce7c1904743951c7112e62691b7',
    },

    # ---------- 抢网（一次性：连上就退出） ----------
    'fast_interval': 1,            # 抢网阶段每几秒探测一次
    'startup_timeout': 180,        # 最多抢多久；到点还没连上就退出进程
    'exit_after_connect': True,    # True=连上即退出；False=常驻并持续处理掉线重连
    'check_interval': 20,          # 常驻模式下在线时的探测间隔（秒）
    'retry_interval': 15,          # 常驻模式下登录失败的重试间隔（秒）

    # ---------- 认证页自动关闭 ----------
    'close_portal_page': True,     # 是否自动关闭弹出的认证页
    'close_portal_interval': 2,    # 每隔几秒扫描一次浏览器窗口
    'close_portal_timeout': 30,    # 连上后最多再等多久（秒）
    # 距离上次"从睡眠/休眠恢复"多少秒之内算作唤醒（否则按刚开机处理）
    'resume_window': 300,
    'close_portal_window': 'auto',  # auto=没有其它浏览器窗口才整窗关；window=一律整窗；never=只关标签
}