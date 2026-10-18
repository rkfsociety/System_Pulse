Option Explicit

Dim fso, shell, scriptDir, overlayPath
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
overlayPath = fso.BuildPath(scriptDir, "overlay.py")
shell.Run "pythonw.exe " & Chr(34) & overlayPath & Chr(34), 0, False
