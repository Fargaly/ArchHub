' ArchHub launcher -- wscript.exe runs this with no console window.
' Same file name as the previous launcher, so existing shortcuts keep
' working; it now starts the node-language application.
Option Explicit
Dim sh, fso, here, py, rc, args, arg, basePy
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here

' Absolute interpreter only. A bare "pythonw" would be resolved from this
' folder first, and this folder is user-writable: a planted pythonw.exe would
' run as the person. No interpreter found = the setup window says so.
Function FindPython(kind)
    Dim base, folder, found, candidate
    found = ""
    base = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Python"
    If fso.FolderExists(base) Then
        For Each folder In fso.GetFolder(base).SubFolders
            If LCase(Left(folder.Name, 10)) = "pythoncore" Then
                candidate = folder.Path & "\" & kind & ".exe"
                If PythonUsable(candidate) Then
                    found = candidate
                    Exit For
                End If
            End If
        Next
    End If
    If found = "" Then
        base = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python"
        If fso.FolderExists(base) Then
            For Each folder In fso.GetFolder(base).SubFolders
                If LCase(Left(folder.Name, 6)) = "python" Then
                    candidate = folder.Path & "\" & kind & ".exe"
                    If PythonUsable(candidate) Then
                        found = candidate
                        Exit For
                    End If
                End If
            Next
        End If
    End If
    If found = "" Then
        base = sh.ExpandEnvironmentStrings("%ProgramFiles%")
        If fso.FolderExists(base) Then
            For Each folder In fso.GetFolder(base).SubFolders
                If LCase(Left(folder.Name, 6)) = "python" Then
                    candidate = folder.Path & "\" & kind & ".exe"
                    If PythonUsable(candidate) Then
                        found = candidate
                        Exit For
                    End If
                End If
            Next
        End If
    End If
    FindPython = found
End Function

Function PythonUsable(candidate)
    Dim status
    PythonUsable = False
    If Not fso.FileExists(candidate) Then Exit Function
    ' Match the installer's version pin: the bundled wheelhouse is cp314 only. Folder iteration can put
    ' Python39 after Python311; an old or broken candidate must not block setup.
    On Error Resume Next
    status = sh.Run(QuoteArgument(candidate) & " -E -s -c " _
        & QuoteArgument("import sys; raise SystemExit(0 if sys.version_info[:2] == (3,14) else 1)"), 0, True)
    If Err.Number = 0 Then PythonUsable = (status = 0)
    Err.Clear
    On Error GoTo 0
End Function

sh.Environment("PROCESS").Remove "PYTHONPATH"
sh.Environment("PROCESS").Remove "PYTHONHOME"
sh.Environment("PROCESS")("PYTHONNOUSERSITE") = "1"
py = FindPython("python")
basePy = py
rc = 1
If py <> "" Then
    rc = RunAndWait("""" & py & """ -E -s """ & here & "\colleague_setup.py"" --check-ready", 0)
End If
If rc <> 0 Then
    ' /s /c removes the outer quote pair; preserve the quotes around both
    ' paths inside it. Use the system command processor, never a local cmd.exe.
    rc = RunAndWait(QuoteArgument(sh.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\cmd.exe") _
        & " /d /s /c " & Chr(34) & QuoteArgument(here & "\ArchHub.bat") _
        & " " & QuoteArgument(py) & Chr(34), 1)
    If rc <> 0 Then
        If RecoverFailedUpdate() Then WScript.Quit 0
        WScript.Quit rc
    End If
End If
args = ""
For Each arg In WScript.Arguments
    args = args & " " & QuoteArgument(arg)
Next
py = here & "\.venv\Scripts\pythonw.exe"
rc = RunAndWait("""" & py & """ -E -s """ & here & "\nodelang\launcher.py""" & args, 0)
If rc <> 0 Then
    If RecoverFailedUpdate() Then WScript.Quit 0
End If
WScript.Quit rc

Function RunAndWait(command, windowStyle)
    Dim result
    result = 1
    On Error Resume Next
    result = sh.Run(command, windowStyle, True)
    If Err.Number <> 0 Then result = 1
    Err.Clear
    On Error GoTo 0
    RunAndWait = result
End Function

Function RecoverFailedUpdate()
    Dim stateDir, result
    RecoverFailedUpdate = False
    If basePy = "" Then Exit Function
    stateDir = sh.Environment("PROCESS")("ARCHHUB_TEST_STATE_DIR")
    If stateDir = "" Then stateDir = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\ArchHub"
    If Not fso.FileExists(stateDir & "\updates\staged.json") Then Exit Function
    ' File entry, not -m: recovery imports no application package or failed setup dependency.
    result = RunAndWait(QuoteArgument(basePy) & " -E -s " & QuoteArgument(here & "\nodelang\quiet_update.py") _
        & " --recover-failed-launch " & QuoteArgument(here) & " --state-dir " & QuoteArgument(stateDir), 0)
    RecoverFailedUpdate = (result = 0)
End Function

Function QuoteArgument(value)
    Dim result, slashes, i, ch
    result = Chr(34)
    slashes = 0
    For i = 1 To Len(value)
        ch = Mid(value, i, 1)
        If ch = Chr(92) Then
            slashes = slashes + 1
        Else
            If ch = Chr(34) Then
                result = result & String(slashes * 2 + 1, Chr(92)) & ch
            Else
                result = result & String(slashes, Chr(92)) & ch
            End If
            slashes = 0
        End If
    Next
    QuoteArgument = result & String(slashes * 2, Chr(92)) & Chr(34)
End Function
