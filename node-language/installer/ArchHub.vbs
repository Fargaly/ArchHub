' ArchHub launcher -- wscript.exe runs this with no console window.
' Same file name as the previous launcher, so existing shortcuts keep
' working; it now starts the node-language application.
Option Explicit
Dim sh, fso, here, py, baseDir, folder
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here
If Not fso.FileExists(here & "\.archhub-ready") Then
    sh.Run "cmd /c """ & here & "\ArchHub.bat""", 1, False
    WScript.Quit
End If
py = ""
baseDir = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Python"
If fso.FolderExists(baseDir) Then
    For Each folder In fso.GetFolder(baseDir).SubFolders
        If LCase(Left(folder.Name, 10)) = "pythoncore" Then
            If fso.FileExists(folder.Path & "\pythonw.exe") Then py = folder.Path & "\pythonw.exe"
        End If
    Next
End If
If py = "" Then py = "pythonw"
sh.Run """" & py & """ """ & here & "\launch_archhub_test.py""", 0, False
