' ArchHub installer launcher.
' Opens the GUI installer with no console flash.
'
' This file is the single thing the user clicks.

Option Explicit

Dim shell, fso, scriptDir, versionPath, version, file, cmd

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

versionPath = scriptDir & "\VERSION"
If Not fso.FileExists(versionPath) Then
    MsgBox "ArchHub installer cannot find its files." & vbCrLf & vbCrLf & _
           "Please extract the entire archive (not just this file) before running.", _
           16, "ArchHub"
    WScript.Quit 1
End If

Set file = fso.OpenTextFile(versionPath, 1)
version = Trim(file.ReadLine())
file.Close

' Launch the GUI installer with PowerShell window hidden.
' Run() with bWaitOnReturn=False and intWindowStyle=0 means: invisible, fire-and-forget.
cmd = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass " & _
      "-File """ & scriptDir & "\installer\install_gui.ps1"" " & _
      "-SourceDir """ & scriptDir & """ " & _
      "-NewVersion """ & version & """"

shell.Run cmd, 0, False
