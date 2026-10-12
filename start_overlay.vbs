Option Explicit

Dim fso, shell, scriptDir, pythonPath, overlayPath
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
overlayPath = fso.BuildPath(scriptDir, "overlay.py")
pythonPath = "C:\Users\USSR\AppData\Local\Programs\Python\Python312\pythonw.exe"

shell.Run Chr(34) & pythonPath & Chr(34) & " " & Chr(34) & overlayPath & Chr(34), 0, False
