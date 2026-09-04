' ArchHub launcher -- wscript.exe runs this with no console window.
' Same file name as the previous launcher, so existing shortcuts keep
' working; it now starts the node-language application.
Option Explicit
Dim sh, fso, here, py
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here

' Absolute interpreter only. A bare "pythonw" would be resolved from this
' folder first, and this folder is user-writable: a planted pythonw.exe would
' run as the person. No interpreter found = the setup window says so.
Function FindPython(kind)
    Dim base, folder, found
    found = ""
    base = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Python"
    If fso.FolderExists(base) Then
        For Each folder In fso.GetFolder(base).SubFolders
            If LCase(Left(folder.Name, 10)) = "pythoncore" Then
                If fso.FileExists(folder.Path & "\" & kind & ".exe") Then found = folder.Path & "\" & kind & ".exe"
            End If
        Next
    End If
    If found = "" Then
        base = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python"
        If fso.FolderExists(base) Then
            For Each folder In fso.GetFolder(base).SubFolders
                If LCase(Left(folder.Name, 6)) = "python" Then
                    If fso.FileExists(folder.Path & "\" & kind & ".exe") Then found = folder.Path & "\" & kind & ".exe"
                End If
            Next
        End If
    End If
    If found = "" Then
        base = sh.ExpandEnvironmentStrings("%ProgramFiles%")
        If fso.FolderExists(base) Then
            For Each folder In fso.GetFolder(base).SubFolders
                If LCase(Left(folder.Name, 6)) = "python" Then
                    If fso.FileExists(folder.Path & "\" & kind & ".exe") Then found = folder.Path & "\" & kind & ".exe"
                End If
            Next
        End If
    End If
    FindPython = found
End Function

If Not fso.FileExists(here & "\.archhub-ready") Then
    ' First run: the setup window gets the same absolute interpreter.
    sh.Run "cmd /c """ & here & "\ArchHub.bat"" """ & FindPython("python") & """", 1, False
    WScript.Quit
End If
py = FindPython("pythonw")
If py = "" Then
    sh.Run "cmd /c """ & here & "\ArchHub.bat"" """"", 1, False
    WScript.Quit
End If
sh.Run """" & py & """ """ & here & "\launch_archhub_test.py""", 0, False
