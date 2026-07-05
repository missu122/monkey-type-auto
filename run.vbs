Option Explicit

Dim shell
Dim fso
Dim baseDir
Dim pythonwPath
Dim scriptPath
Dim command

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonwPath = fso.GetAbsolutePathName(fso.BuildPath(baseDir, "..\..\work\ck_mvp_venv\Scripts\pythonw.exe"))
scriptPath = fso.BuildPath(fso.BuildPath(baseDir, "src"), "text_typer.py")

shell.CurrentDirectory = baseDir

If fso.FileExists(pythonwPath) Then
    command = """" & pythonwPath & """ """ & scriptPath & """"
Else
    command = "pyw -3 """ & scriptPath & """"
End If

shell.Run command, 0, False
