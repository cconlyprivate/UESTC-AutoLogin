# UESTC 电信校园网自动登录

用于电子科技大学寝室电信校园网的 Windows 一次性自动联网工具，适配本项目实现的锐捷 ePortal + CAS 认证流程。其他校区或门户版本可能需要调整地址、认证页模板或登录流程。

登录桌面、解锁或从睡眠/休眠恢复后，脚本探测网络，必要时登录，并处理弹出的认证页。确认联网后退出，不常驻后台。任务在用户登录后运行，不是 Windows 登录前的系统服务。

## 运行要求

| 项目 | 要求 |
| --- | --- |
| 系统 | Windows 10 / 11，当前用户已登录桌面 |
| Python | 3.10 或以上 |
| Python 包 | `requests`，安装到实际使用的解释器中 |
| 系统组件 | Windows PowerShell 5.1、Windows Script Host、任务计划程序 |
| 网络 | 已连接目标校园网的网线或 WiFi，能够访问认证门户 |

**不强制使用 `.venv`。** 可以使用系统 Python、项目的虚拟环境或指定位置的 Python。安装脚本会验证版本和 `requests`，并把真实解释器路径写入任务，运行时无需激活环境，也无需在任务中依赖 PATH。

## 快速安装：使用系统 Python

### 1. 下载并解压

将完整项目解压到一个准备长期保留的目录。以下以 `C:\AutoLogin-uestc` 为例，也可以放在其他盘符或含空格的目录。

打开 PowerShell，进入实际目录：

```powershell
cd 'C:\AutoLogin-uestc'
```

### 2. 安装依赖

已经安装 Python Launcher（`py`）时：

```powershell
py -3 --version
py -3 -m pip install requests
```

没有 `py`，但 `python` 命令可用时：

```powershell
python --version
python -m pip install requests
```

确认版本为 3.10 或以上。多个 Python 环境之间的依赖不共享；如果自动检测找不到合适环境，可以使用下文的 `-PythonPath`。

### 3. 填写账号密码

编辑 `config.py`：

```python
'user': User('你的宽带账号', '你的密码', None),
```

账号填写认证页所用的宽带账号（寝室电信通常是手机号），按当前门户要求填写，不自行添加运营商后缀。密码按 Python 字符串语法填写，包含引号、反斜杠时正确转义。提交修改到公开仓库前，恢复示例账号密码。

### 4. 手动验证登录

使用刚安装依赖的解释器：

```powershell
py -3 login_once.py
```

如果使用的是 `python` 命令，则执行 `python login_once.py`。

`RESULT: online` 表示 HTTP 204 探针已确认联网。如果原本已经在线，脚本会直接返回，不会重新验证账号密码。需要验证认证流程时，应通过门户注销后，保持网线或 WiFi 连接再测试；拔掉网线后无法访问认证门户。

### 5. 安装开机任务

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_task.ps1
```

安装脚本按以下顺序查找**版本和依赖均可用**的解释器：

1. 项目内 `.venv\Scripts\python.exe`（如果存在）。
2. `py.exe -3` 实际选择的解释器。
3. 当前 PATH 中发现的 `python.exe`。

脚本检查 Python 版本、`requests` 是否能够导入，然后读取当前 Windows 用户和项目路径，生成 XML 并调用 `schtasks.exe` 导入。没有可用环境时会显示原因及依赖安装提示，停止导入；不会自动创建 `.venv` 或安装依赖。

成功时会显示最终采用的 Python 路径。默认任务名为 `UESTC-Portal`；重新执行会更新同名任务。

### 6. 试运行并确认

```powershell
schtasks /Run /TN "UESTC-Portal"
schtasks /Query /TN "UESTC-Portal" /V /FO LIST
```

查看项目下 `logs\<日期>.log`。任务完成后应退出；通常在未出现认证页时，还会等待最多 30 秒。导入成功只表示任务创建成功，不能代替实际登录验证。

## 自选 Python 或虚拟环境

### 指定已有 Python

适用于 Python 没有加入 PATH，或电脑上安装了多个版本：

```powershell
& 'D:\Python\python.exe' -m pip install requests
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_task.ps1 -PythonPath 'D:\Python\python.exe'
```

请指定真实的 `python.exe`，不要指定 `py.exe`、`pythonw.exe` 或文件夹。任务由 Windows Script Host 隐藏启动普通的 `python.exe`，不要求安装 `pythonw.exe`。

### 可选：使用项目虚拟环境

```powershell
py -3 -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install requests
& '.\.venv\Scripts\python.exe' login_once.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_task.ps1
```

无需执行 `Activate.ps1`。指定 `-PythonPath` 时只检查指定解释器，失败后不会自动换到其他环境。

## 自动联网和认证页处理

运行流程：

```text
启动认证页监视 → HTTP 204 探测 → 必要时登录 CAS / 调用 userOnline
→ 最长约 15 秒复检外网 → 确认联网 → 等待认证页处理 → 退出
```

默认在登录、解锁和 Kernel-Power 107 睡眠/休眠恢复事件（延迟 2 秒）时触发。没有密码的账户在恢复后可能没有解锁事件，因此保留独立的恢复触发器。

认证页处理规则：

- **电脑重启/开机**：发现认证页后，关闭它所在的浏览器窗口。该窗口的其他标签也会一起关闭。
- **睡眠/休眠恢复**：只有一个浏览器窗口且只有一个认证标签时关闭窗口；存在其他窗口或标签时只关闭认证标签。
- 唤醒判断使用本次开机后的 Kernel-Power 107 记录。日志读取失败且开机已超过两分钟时，按唤醒规则处理。
- 无法识别标签数量时，不自动整窗关闭；找不到认证标签的关闭按钮时，保留页面并记录日志。

关闭操作依赖浏览器的 UI Automation 支持。脚本处理识别出的认证窗口或标签，不会终止全部浏览器进程。

`config.py` 中可调整：

| 配置 | 默认值 | 含义 |
| --- | --- | --- |
| `portal.base_url` | 文件中的门户地址 | 当前认证服务地址 |
| `portal.page_id` | 文件中的模板 ID | 换校区或门户改版时可能需要调整 |
| `fast_interval` | 1 秒 | 两轮检查之间的等待时间，网络请求耗时另计 |
| `startup_timeout` | 180 秒 | 总体联网尝试窗口，当前请求结束后检查是否超时 |
| `close_portal_page` | `True` | 是否处理认证页 |
| `close_portal_interval` | 2 秒 | 页面监视的扫描间隔，另计扫描耗时 |
| `close_portal_timeout` | 30 秒 | 联网后等待认证页处理的时间 |

任务完成后再掉线，需要下一次触发或手动运行。本项目不提供常驻模式。

## 管理、迁移与卸载

卸载任务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_task.ps1 -Uninstall
```

自定义任务名时，安装和卸载使用同一个名称：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_task.ps1 -TaskName 'My-UESTC-Portal'
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_task.ps1 -TaskName 'My-UESTC-Portal' -Uninstall
```

移动项目目录、更换 Python 路径或删除虚拟环境后，需要重新执行安装脚本。虚拟环境通常不能直接搬迁使用，应在新位置重新创建。卸载仅删除任务，不删除项目、Python 或日志。

任务执行链：

```text
任务计划程序 → wscript.exe → run_hidden.vbs → 已验证的 python.exe → always_online.py
```

VBS 等待 Python 结束，向任务计划程序返回运行结果；配合“忽略新实例”，避免任务尚在联网时重复启动。启动失败或 Python 非零退出会写入 `logs\launcher-error.log`。

## 手动导入 XML（可选）

优先使用安装脚本，它会验证环境并处理路径。`UESTC-Portal.xml` 是手工填写用的模板，直接导入占位符版本不能正常运行。

导入前替换所有对应值：

| 模板内容 | 替换为 |
| --- | --- |
| `YOUR-PC\YOUR-USERNAME` | 当前 Windows 用户，可用 `whoami` 查询 |
| `C:\AutoLogin-uestc` | 实际项目目录 |
| `C:\Path\To\Python\python.exe` | 已安装 `requests` 的 Python 3.10+ 解释器 |
| `C:\Windows\System32\wscript.exe` | 若 Windows 不在 C 盘，改成实际系统路径 |

路径包含 `&` 时，在 XML 中写为 `&amp;`；保存为 UTF-8，与模板声明一致。可以在任务计划程序中选择“导入任务”，或运行：

```powershell
schtasks /Create /TN "UESTC-Portal" /XML .\UESTC-Portal.xml /F
```

手动创建任务时，操作填写为：

- 程序：`C:\Windows\System32\wscript.exe`
- 参数：`"C:\AutoLogin-uestc\run_hidden.vbs" "D:\Python\python.exe"`
- 起始于：`C:\AutoLogin-uestc`

使用当前用户、仅用户登录时运行、无需最高权限；配置登录/解锁/恢复三个触发器，允许电池供电运行，并选择不启动新实例。真实的路径需要按本机修改。

## 诊断与常见问题

| 现象 | 检查方法 |
| --- | --- |
| 没有 `.venv`，能否安装？ | 可以。安装脚本会查找系统 Python，也可用 `-PythonPath` 指定解释器。 |
| 提示没有可用 Python | 确认版本为 3.10+，使用真实 `python.exe` 路径，避免 Microsoft Store 的命令占位符。 |
| `No module named requests` | 用任务显示的同一个解释器执行 `-m pip install requests`，然后重新安装任务。 |
| 导入失败 / Access denied | 查看系统原始错误，检查任务创建权限和同名任务所有者；不要把导入成功当作运行成功。 |
| 任务运行却没有正常日志 | 查看任务参数中的路径和 `logs\launcher-error.log`；确认 Windows Script Host 未被系统策略禁用。 |
| 任务结果为非零 | 查阅启动器和 Python 日志；联网超时、环境损坏或脚本异常均可能导致失败。 |
| 修改路径后无法启动 | 在新位置重新执行安装脚本，必要时重建虚拟环境。 |
| 网络通了但认证页没关 | 检查 `close_portal_page` 和日志；浏览器可能不暴露可操作的标签关闭按钮。 |
| CAS 页面解析失败 | 确认连接的是目标校园网，检查门户地址和 page ID，门户改版也可能需要更新代码。 |

现场诊断（保持校园网物理连接，在门户未认证时运行）：

```powershell
py -3 selftest.py --no-login
py -3 selftest.py
```

第一条只抓门户跳转，第二条尝试登录并复检。若使用指定解释器或虚拟环境，将 `py -3` 换成对应的 `python.exe`。报告保存在 `logs\selftest-<时间>.txt`；分享前检查账号、IP 和会话信息。

## 许可证

[MIT License](LICENSE)。
