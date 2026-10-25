# 关闭"网络认证门户页"
#
# 识别依据（命中任一）：
#   1) 浏览器地址栏 URL 匹配门户地址（110.184.24.61 / 10.253.0.235 ...）
#   2) 窗口标题匹配「连网认证 / 电子科技大学 / 上网登录 ...」
#   3) 任一标签页标题匹配同一组词（后台标签也能认）
#
# 关闭粒度 -CloseWindow：
#   auto   （默认）除它之外没有别的浏览器窗口 -> 整窗关掉；
#                  已经有别的浏览器窗口在开着      -> 只关这一个标签
#   window 一律整窗关
#   never  一律只关标签
#
# 输出：CLOSE_WINDOW / CLOSE_TAB / FAIL / LIST / NONE，Tab 分隔

param(
    [string]$UrlPattern    = '110\.184\.24\.61|10\.253\.0\.235|aaa\.uestc\.edu\.cn|/cas-sso|srun_portal',
    [string]$TitlePattern  = '连网认证|电子科技大学|上网登录|登录网络|网络登录|上网认证|锐捷认证',
    [string]$ProcessFilter = 'chrome|msedge|edge|browser|firefox|opera|brave|360|sogou|qq|2345|maxthon|liebao|\buc\b',
    [ValidateSet('auto', 'window', 'always', 'never')][string]$CloseWindow = 'auto',
    [switch]$List,
    [switch]$All
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms

if (-not ('PortalWin32' -as [type])) {
Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class PortalWin32 {
    public delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern bool SwitchToThisWindow(IntPtr h, bool alt);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
    public static bool CloseWindowMsg(IntPtr h) { return PostMessage(h, 0x0010, IntPtr.Zero, IntPtr.Zero); }
    public static List<long> Visible() {
        var list = new List<long>();
        EnumWindows((h, l) => { if (IsWindowVisible(h)) list.Add(h.ToInt64()); return true; }, IntPtr.Zero);
        return list;
    }
    public static string Title(long h) {
        var sb = new StringBuilder(512);
        GetWindowTextW(new IntPtr(h), sb, 512);
        return sb.ToString();
    }
    public static uint Pid(long h) {
        uint pid; GetWindowThreadProcessId(new IntPtr(h), out pid); return pid;
    }
}
"@
}

$AE = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]
$CT = [System.Windows.Automation.ControlType]

$tabCond  = New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $CT::TabItem)
$btnCond  = New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $CT::Button)
$editCond = New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $CT::Edit)

function Close-BrowserWindow([IntPtr]$h, [string]$procName, [string]$shown) {
    try {
        $el = $AE::FromHandle($h)
        $el.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern).Close()
    } catch {
        [PortalWin32]::CloseWindowMsg($h) | Out-Null
    }
    "CLOSE_WINDOW`t$procName`t$shown"
    Start-Sleep -Milliseconds 300
}

# ---------- 第一遍：登记所有浏览器窗口 ----------
$targets = @()
foreach ($hv in [PortalWin32]::Visible()) {
    $h = [IntPtr]$hv
    $title = [PortalWin32]::Title($hv)
    if (-not $title) { continue }
    try { $procName = (Get-Process -Id ([PortalWin32]::Pid($hv)) -ErrorAction Stop).ProcessName } catch { continue }
    if (-not $All -and $procName -notmatch $ProcessFilter) { continue }

    $url = $null; $tabHit = $null; $tabName = ''; $tabCount = 0
    try {
        $root = $AE::FromHandle($h)
        foreach ($e in @($root.FindAll($TS::Descendants, $editCond))) {
            try { $v = $e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value } catch { continue }
            if ($v -match '://' -and $v -match $UrlPattern) { $url = $v; break }
        }
        $tabs = @($root.FindAll($TS::Descendants, $tabCond))
        $tabCount = $tabs.Count
        foreach ($tab in $tabs) {
            try { $nm = $tab.Current.Name } catch { continue }
            if ($nm -match $TitlePattern) { $tabHit = $tab; $tabName = $nm; break }
        }
    } catch { }

    $why = ''
    if ($url) { $why = 'url' }
    elseif ($title -match $TitlePattern) { $why = 'win-title' }
    elseif ($tabHit) { $why = 'tab-name' }

    $targets += [pscustomobject]@{
        Hwnd     = $h
        Proc     = $procName
        Title    = $title
        Url      = $url
        TabHit   = $tabHit
        TabName  = $tabName
        TabCount = $tabCount
        Matched  = [bool]$why
        Why      = $why
    }
}

$winTotal = $targets.Count
$hits = 0

foreach ($t in @($targets | Where-Object { $_.Matched })) {
    $hits++
    $shown = if ($t.Url) { $t.Url } else { $t.Title }
    $others = $winTotal - 1

    $action = 'tab'
    if ($CloseWindow -in @('window', 'always')) { $action = 'window' }
    elseif ($CloseWindow -eq 'auto' -and $others -le 0) { $action = 'window' }

    if ($List) {
        "LIST`t$($t.Proc)`t$shown`t($($t.Why))`ttabs=$($t.TabCount)`ttab=[$($t.TabName)]`tothers=$others`t->$action"
        continue
    }

    if ($action -eq 'window') {
        Close-BrowserWindow $t.Hwnd $t.Proc $shown
        continue
    }

    $done = $false
    if ($t.TabHit) {
        try {
            foreach ($b in @($t.TabHit.FindAll($TS::Descendants, $btnCond))) {
                if ($b.Current.Name -match '关闭|Close') {
                    $b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
                    "CLOSE_TAB`t$($t.Proc)`t$shown"
                    $done = $true; break
                }
            }
        } catch { }
    }
    if (-not $done) { "FAIL`t$($t.Proc)`t$shown`t(no close button on target tab)" }
    Start-Sleep -Milliseconds 250
}

if ($hits -eq 0) { "NONE`twindows=$winTotal" }
exit 0
