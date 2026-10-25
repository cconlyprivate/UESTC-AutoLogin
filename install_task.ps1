# 一键安装计划任务（不需要管理员权限）
#
#   安装：右键"使用 PowerShell 运行"，或在 PowerShell 里执行
#           powershell -ExecutionPolicy Bypass -File install_task.ps1
#   卸载：powershell -ExecutionPolicy Bypass -File install_task.ps1 -Uninstall
#
# 它会自动读取"当前用户"和"本项目所在路径"，生成任务定义并导入，
# 所以项目放在哪个目录都能用，不用手改 XML。

param(
    [string]$TaskName = 'UESTC-Portal',
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

if ($Uninstall) {
    schtasks /Delete /TN $TaskName /F
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

$user = "$env:USERDOMAIN\$env:USERNAME"
$wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>$user</Author>
    <Description>UESTC 电信校园网自动登录：登录 / 解锁 / 唤醒后抢网，并关闭认证页</Description>
    <URI>\$TaskName</URI>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$user</UserId>
    </LogonTrigger>
    <SessionStateChangeTrigger>
      <Enabled>true</Enabled>
      <StateChange>SessionUnlock</StateChange>
      <UserId>$user</UserId>
    </SessionStateChangeTrigger>
    <EventTrigger>
      <Enabled>true</Enabled>
      <Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="System"&gt;&lt;Select Path="System"&gt;*[System[Provider[@Name='Microsoft-Windows-Kernel-Power'] and EventID=107]]&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription>
      <Delay>PT2S</Delay>
    </EventTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$user</UserId>
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
      <Command>$wscript</Command>
      <Arguments>"$vbs"</Arguments>
      <WorkingDirectory>$root</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

$tmp = Join-Path $env:TEMP "UESTC-Portal-task.xml"
[IO.File]::WriteAllText($tmp, $xml, (New-Object Text.UnicodeEncoding($false, $true)))

Write-Host "项目目录 : $root"
Write-Host "运行用户 : $user"
Write-Host "启动方式 : $wscript `"$vbs`""
Write-Host ""

$out = schtasks /Create /TN $TaskName /XML $tmp /F 2>&1
$code = $LASTEXITCODE
Remove-Item $tmp -Force -ErrorAction SilentlyContinue

if ($code -ne 0) {
    Write-Host ($out | Out-String) -ForegroundColor Red
    Write-Host "导入失败。如果是 Access denied，说明同名任务已存在且被别处创建，" -ForegroundColor Yellow
    Write-Host "请先在「任务计划程序」里手动删掉 $TaskName 再重试。" -ForegroundColor Yellow
    exit 1
}

Write-Host "已创建任务：$TaskName" -ForegroundColor Green
Write-Host "触发器：登录时 / 工作站解锁 / 从睡眠或休眠恢复（Kernel-Power 107）"
Write-Host ""
Write-Host "现在可以试运行一次：" -ForegroundColor Cyan
Write-Host "  schtasks /Run /TN `"$TaskName`""
Write-Host "然后看日志：$root\logs\<日期>.log"
