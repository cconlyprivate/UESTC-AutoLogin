' Launch always_online.py with no visible window.
' Prefers the project-local venv pythonw; falls back to pythonw.exe on PATH.
' Used by the scheduled task so it never depends on a fixed interpreter path.

Option Explicit

Dim fso, sh, base, exe, script, errLog
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

base   = fso.GetParentFolderName(WScript.ScriptFullName)
script = base & "\always_online.py"

If fso.FileExists(base & "\.venv\Scripts\pythonw.exe") Then
    exe = base & "\.venv\Scripts\pythonw.exe"
Else
    exe = "pythonw.exe"
End If

sh.CurrentDirectory = base

On Error Resume Next
sh.Run """" & exe & """ """ & script & """", 0, False
If Err.Number <> 0 Then
    If Not fso.FolderExists(base & "\logs") Then fso.CreateFolder(base & "\logs")
    Set errLog = fso.OpenTextFile(base & "\logs\launcher-error.log", 8, True)
    errLog.WriteLine Now & "  launch failed: " & Err.Description & "  (python=" & exe & ")"
    errLog.Close
End If
