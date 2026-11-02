' Launch the validated Python interpreter hidden and keep the task running.
Option Explicit

Dim fso, sh, base, exe, script, code, message, errLog
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)
script = base & "\always_online.py"

If WScript.Arguments.Count > 0 Then
    exe = WScript.Arguments(0)
ElseIf fso.FileExists(base & "\.venv\Scripts\python.exe") Then
    exe = base & "\.venv\Scripts\python.exe"
Else
    Fail "No interpreter configured. Run install_task.ps1, optionally with -PythonPath."
End If

If Not fso.FileExists(exe) Then Fail "Python not found: " & exe & ". Re-run install_task.ps1."
If Not fso.FileExists(script) Then Fail "Script not found: " & script
sh.CurrentDirectory = base
On Error Resume Next
' Wait for Python so Task Scheduler IgnoreNew covers the entire login process.
code = sh.Run("""" & exe & """ """ & script & """", 0, True)
If Err.Number <> 0 Then
    message = Err.Description
    On Error GoTo 0
    Fail "Launch failed: " & message
End If
On Error GoTo 0
If code <> 0 Then Fail "Python exited with code " & code & ". Check logs; interpreter: " & exe
WScript.Quit 0

Sub Fail(detail)
    On Error Resume Next
    If Not fso.FolderExists(base & "\logs") Then fso.CreateFolder(base & "\logs")
    Set errLog = fso.OpenTextFile(base & "\logs\launcher-error.log", 8, True, -1)
    errLog.WriteLine Now & "  " & detail
    errLog.Close
    WScript.Quit 1
End Sub
