# UESTC 电信校园网自动登录

## 一、简介

这是一个为**电子科技大学（UESTC）电信校园网**写的自动登录脚本。

寝室的电信宽带走的是「锐捷 ePortal + 统一身份认证（CAS）」：插网线或连 WiFi 后会被 AC 拦截，浏览器弹出认证页，要手动输入宽带账号密码才能上网。

这个脚本把这件事自动化了：

- **自动登录**：抓取 AC 跳转拿到 `sessionId` → 走 CAS 登录（密码用页面下发的 `croypto` 做 AES-128-ECB 加密）→ 调 `userOnline` 让 NAS 放行
- **自动关认证页**：登录后把浏览器里弹出的那个认证窗口关掉
- **开机即抢网**：进桌面后每 1 秒探测一次，一般几秒内就能联网

判断能不能上网用的是 HTTP 204 探针而不是 ping —— 被 AC 拦住时 ping 往往是通的，但实际打不开网页。

## 二、安装依赖

| 依赖 | 说明 |
|---|---|
| Windows 10 / 11 | 用到任务计划程序与 UI Automation，仅 Windows 可用 |
| Python 3.9+ | 建议 3.10 及以上 |
| `requests` | 唯一的第三方包 |
| Windows PowerShell 5.1 | 系统自带，用来关认证页，无需安装 |

创建虚拟环境并安装依赖：

```powershell
cd C:\AutoLogin-uestc
python -m venv .venv
.venv\Scripts\pip install requests
```

## 三、测试前填写自己的账号密码

打开项目根目录的 `config.py`，把这一行换成你自己的宽带账号和密码：

```python
'user': User('你的宽带账号', '你的密码', None),
```

例如：

```python
'user': User('18100000000', 'your-password', None),
```

注意两点：

- 账号就是你在认证页上填的那个（寝室电信一般是**手机号**），**不要**加 `@dx`、`@cmcc` 之类的后缀
- 密码原样填写，不需要转义

## 四、测试时运行哪个文件

**1）先跑 `login_once.py`（单次登录，用来验证账号密码对不对）**

```powershell
.venv\Scripts\python.exe login_once.py
```

看到 `RESULT: online` 就说明账号密码和门户地址都没问题。

**2）可选：`selftest.py`（断网自检，全过程写日志）**

断开网络后再运行：

```powershell
.venv\Scripts\python.exe selftest.py
```

它会依次完成「等离线 → 抓跳转链 → 打印 sessionId / userIp / nasIp → 登录 → 复检连通性」，过程写进 `logs\selftest-<时间>.txt`，出问题时方便排查。

**3）日常使用：`always_online.py`（正式抢网）**

```powershell
.venv\Scripts\pythonw.exe always_online.py
```

用 `pythonw` 启动不会弹出黑窗口。运行逻辑：

```
每 1 秒探测一次 → 断网就登录 → 连上后关掉认证页 → 退出进程
180 秒仍没连上 → 直接退出（不留后台进程）
```

日志写在 `logs\<日期>.log`。

## 五、如何设置开机自启

**最简单：一条命令**

```powershell
powershell -ExecutionPolicy Bypass -File install_task.ps1
```

它会自动读取「当前用户」和「项目所在路径」，生成任务定义并导入，不用手改任何东西。

卸载：

```powershell
powershell -ExecutionPolicy Bypass -File install_task.ps1 -Uninstall
```

任务实际执行的是 `wscript.exe run_hidden.vbs`。这个启动器会优先使用项目里的 `.venv`，找不到就用 PATH 上的 `pythonw.exe`，所以任务本身不依赖固定的解释器路径，把项目换个目录重新跑一次安装脚本即可。

---

**手动方式（想自己建任务的话）**

用 Windows 自带的「任务计划程序」，不需要管理员权限。`Win+R` 输入 `taskschd.msc`，在右侧点「创建任务」。

**常规**

- 名称填 `UESTC-Portal`
- 选中 **只在用户登录时运行**
- 不要勾「使用最高权限运行」

**触发器**（三个都加，覆盖开机 / 解锁 / 睡眠唤醒）

| 触发条件 | 设置 |
|---|---|
| 登录时 | 指定当前用户 |
| 会话状态更改 | 工作站解锁 |
| 事件发生时 | 日志 `System`、来源 `Microsoft-Windows-Kernel-Power`、事件 ID `107`，延迟 2 秒 |

> 第三个触发器用于「从睡眠/休眠恢复」。如果电脑账户没有设密码，唤醒后不会停在锁屏，也就没有“解锁”事件，这时必须靠它来触发。

**操作**

- 程序或脚本：`C:\AutoLogin-uestc\.venv\Scripts\pythonw.exe`
- 添加参数：`always_online.py`
- 起始于：`C:\AutoLogin-uestc`

**设置**

- 「如果任务已在运行」选 **请勿启动新实例**
- 取消「如果任务运行时间超过…停止任务」（默认 3 天会结束进程）

**条件**

- 取消「只有在计算机使用交流电源时才启动此任务」
- 取消「如果计算机改用电池电源，则停止」

保存后右键任务点「运行」，看 `logs` 目录里是否出现新日志，确认配置生效。

本仓库也附带了 `UESTC-Portal.xml`（已包含上面三个触发器），可以直接在「任务计划程序」里用「导入任务」加载。导入前把文件里的 `YOUR-PC\YOUR-USERNAME` 改成你自己的 `计算机名\用户名`。
