Option Explicit

Dim fso, shell, scriptDir, overlayPath, pythonPath
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
overlayPath = fso.BuildPath(scriptDir, "overlay.py")
pythonPath = fso.BuildPath(scriptDir, ".venv\Scripts\pythonw.exe")

If Not fso.FileExists(pythonPath) Then
    shell.Popup "Python environment not found. Follow the setup instructions in README.md." & vbCrLf & pythonPath, 0, "System Pulse", 48
    WScript.Quit 1
End If

shell.Run Chr(34) & pythonPath & Chr(34) & " " & Chr(34) & overlayPath & Chr(34), 0, False
