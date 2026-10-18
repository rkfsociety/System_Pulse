Option Explicit

Dim fso, scriptDir, overlayPath
Dim wmi, processes, process, shell
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
overlayPath = fso.BuildPath(scriptDir, "overlay.py")
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set processes = wmi.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name = 'pythonw.exe'")

For Each process In processes
    If InStr(1, process.CommandLine, overlayPath, vbTextCompare) > 0 Then
        WScript.Quit 0
    End If
Next

Set shell = CreateObject("WScript.Shell")
shell.Run "pythonw.exe " & Chr(34) & overlayPath & Chr(34), 0, False
