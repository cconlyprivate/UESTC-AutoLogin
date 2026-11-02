# 一键安装计划任务（不需要管理员权限）
#
#   安装：右键"使用 PowerShell 运行"，或在 PowerShell 里执行
#           powershell -ExecutionPolicy Bypass -File install_task.ps1
#   卸载：powershell -ExecutionPolicy Bypass -File install_task.ps1 -Uninstall
#
# 它会自动读取"当前用户"和"本项目所在路径"，生成任务定义并导入，
# 支持系统 Python 或已有虚拟环境，不要求创建 .venv。
# 可用 -PythonPath "D:\Python\python.exe" 指定解释器；迁移目录后重新安装任务。

param(
    [string]$TaskName = 'UESTC-Portal',
    [string]$PythonPath,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

if ($Uninstall) {
    schtasks /Delete /TN $TaskName /F
    if ($LASTEXITCODE -ne 0) { throw "删除任务失败：$TaskName" }
    Write-Host "已删除任务：$TaskName" -ForegroundColor Yellow
    return
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$vbs = Join-Path $root 'run_hidden.vbs'
if (-not (Test-Path -LiteralPath $vbs)) {
    throw "找不到 run_hidden.vbs：$vbs"
}
if (-not (Test-Path -LiteralPath (Join-Path $root 'always_online.py'))) {
    throw "找不到 always_online.py，请确认脚本放在项目根目录"
}

# 在导入任务前确定真实解释器，避免计划任务依赖交互终端的 PATH。
# 不创建虚拟环境、不自动安装软件；用户可选择系统 Python 或已有环境。
function Find-UsablePython {
    $candidates = @()
    if ($PythonPath) {
        if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
            throw "指定的 Python 不存在：$PythonPath"
        }
        $candidates += [pscustomobject]@{ Exe = (Resolve-Path -LiteralPath $PythonPath).Path; Prefix = @() }
    } else {
        $local = Join-Path $root '.venv\Scripts\python.exe'
        if (Test-Path -LiteralPath $local) {
            $candidates += [pscustomobject]@{ Exe = $local; Prefix = @() }
        }
        $py = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($py) { $candidates += [pscustomobject]@{ Exe = $py.Source; Prefix = @('-3') } }
        foreach ($cmd in @(Get-Command python.exe -CommandType Application -All -ErrorAction SilentlyContinue)) {
            $candidates += [pscustomobject]@{ Exe = $cmd.Source; Prefix = @() }
        }
    }
    $probe = "import sys, json, importlib.util; print(json.dumps({'exe':sys.executable,'ok':sys.version_info >= (3,10),'requests':importlib.util.find_spec('requests') is not None}))"
    foreach ($candidate in $candidates) {
        try {
            $prefixArgs = @($candidate.Prefix)
            $raw = & $candidate.Exe @prefixArgs -c $probe 2>$null
            if ($LASTEXITCODE -ne 0) { continue }
            $info = ($raw -join "`n") | ConvertFrom-Json
            if (-not $info.ok) {
                Write-Host "跳过低于 Python 3.10 的解释器：$($info.exe)" -ForegroundColor Yellow
                continue
            }
            if (-not $info.requests) {
                Write-Host "此解释器缺少 requests：$($info.exe)" -ForegroundColor Yellow
                Write-Host "安装命令：& `"$($info.exe)`" -m pip install requests"
                continue
            }
            # 实际导入也必须成功，不能只检查包是否存在。
            & $info.exe -c 'import requests' 2>$null
            if ($LASTEXITCODE -ne 0) {
                Write-Host "requests 无法导入：$($info.exe)，请修复后重新安装任务。" -ForegroundColor Yellow
                continue
            }
            return [string]$info.exe
        } catch {
            Write-Host "无法使用解释器：$($candidate.Exe)" -ForegroundColor Yellow
        }
    }
    throw '没有找到可用的 Python 3.10+ 与 requests。请安装依赖后重试，或使用 -PythonPath 指定 python.exe。无需创建 .venv。'
}

$python = Find-UsablePython
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
if (-not (Test-Path -LiteralPath $wscript)) { throw "找不到 Windows Script Host：$wscript" }
# 路径和用户名可能含 & 等 XML 特殊字符，必须转义。
$userXml = [Security.SecurityElement]::Escape($user)
$taskXml = [Security.SecurityElement]::Escape($TaskName)
$wscriptXml = [Security.SecurityElement]::Escape($wscript)
$argsXml = [Security.SecurityElement]::Escape(('"{0}" "{1}"' -f $vbs, $python))
$rootXml = [Security.SecurityElement]::Escape($root)

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>$userXml</Author>
    <Description>UESTC 电信校园网自动登录：登录 / 解锁 / 唤醒后抢网，并关闭认证页</Description>
    <URI>\$taskXml</URI>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$userXml</UserId>
    </LogonTrigger>
    <SessionStateChangeTrigger>
      <Enabled>true</Enabled>
      <StateChange>SessionUnlock</StateChange>
      <UserId>$userXml</UserId>
    </SessionStateChangeTrigger>
    <EventTrigger>
      <Enabled>true</Enabled>
      <Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="System"&gt;&lt;Select Path="System"&gt;*[System[Provider[@Name='Microsoft-Windows-Kernel-Power'] and EventID=107]]&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription>
      <Delay>PT2S</Delay>
    </EventTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$userXml</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$wscriptXml</Command>
      <Arguments>$argsXml</Arguments>
      <WorkingDirectory>$rootXml</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

# 解析后再写出 UTF-16，临时文件使用独立名称并始终清理。
[xml]$validated = $xml
$tmp = [IO.Path]::GetTempFileName()
try {
    [IO.File]::WriteAllText($tmp, $xml, (New-Object Text.UnicodeEncoding($false, $true)))
    Write-Host "项目目录 : $root"
    Write-Host "运行用户 : $user"
    Write-Host "Python   : $python"
    Write-Host "启动方式 : wscript.exe -> run_hidden.vbs -> 已验证的 python.exe"
    & schtasks.exe /Create /TN $TaskName /XML $tmp /F
    if ($LASTEXITCODE -ne 0) {
        throw '任务导入失败。请检查上方系统错误、当前用户的任务创建权限以及同名任务的所有者。'
    }
} finally {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
}

Write-Host "已创建任务：$TaskName" -ForegroundColor Green
Write-Host "触发器：登录时 / 工作站解锁 / 从睡眠或休眠恢复（Kernel-Power 107）"
Write-Host ""
Write-Host "现在可以试运行一次：" -ForegroundColor Cyan
Write-Host "  schtasks /Run /TN `"$TaskName`""
Write-Host "然后看日志：$root\logs\<日期>.log"

