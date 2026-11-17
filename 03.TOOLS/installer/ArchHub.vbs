' ArchHub launcher -- wscript.exe runs this with no console window.
' Same file name as the previous launcher, so existing shortcuts keep
' working; it now starts the node-language application.
Option Explicit
Dim sh, fso, here, py, rc, args, arg, basePy, runError, launcherState
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here
launcherState = LauncherStateRoot()
If launcherState = "" Then WScript.Quit 87

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
' The desktop's update timer never runs while setup is still in this process.
' Start the existing updater now: it checks GitHub Latest, writes launcher.log,
' and installs later when the machine is idle. A second launch finds it already running.
StartUpdateMaintainer
If py <> "" Then
    rc = RunAndWait("""" & py & """ -E -s """ & here & "\colleague_setup.py"" --check-ready", 0)
End If
If rc <> 0 Then
    rc = RunSetupHidden(py)
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
    runError = Err.Number
    If runError <> 0 Then result = 1
    Err.Clear
    On Error GoTo 0
    RunAndWait = result
End Function

Function LauncherStateRoot()
    Dim selected, entry, env, testSelected, absolute
    Set env = sh.Environment("PROCESS")
    For Each entry In env
        If UCase(Left(entry, Len("ARCHHUB_TEST_STATE_DIR="))) = "ARCHHUB_TEST_STATE_DIR=" Then
            testSelected = True
            Exit For
        End If
    Next
    If testSelected Then
        selected = env("ARCHHUB_TEST_STATE_DIR")
    Else
        selected = env("ARCHHUB_STATE_DIR")
        If selected = "~" Or Left(selected, 2) = "~\" Or Left(selected, 2) = "~/" Then
            selected = env("USERPROFILE") & Mid(selected, 2)
        End If
        If selected = "" Then
            selected = env("LOCALAPPDATA")
            If selected = "" Then selected = env("USERPROFILE") & "\AppData\Local"
            selected = selected & "\ArchHub"
        End If
    End If
    Set absolute = New RegExp
    absolute.Pattern = "^([A-Za-z]:[\\/]|[\\/]{2}[^\\/]+[\\/][^\\/]+)"
    If absolute.Test(selected) Then
        LauncherStateRoot = fso.GetAbsolutePathName(selected)
    Else
        LauncherStateRoot = ""
    End If
End Function

Function RunSetupHidden(interpreter)
    Dim command, logs, logPath, attempt, output, result, launchError, oldLog
    logs = launcherState & "\logs"
    attempt = logs & "\archhub-setup-" & fso.GetTempName
    logPath = attempt & ".log"
    oldLog = sh.Environment("PROCESS")("ARCHHUB_SETUP_LOG")
    On Error Resume Next
    If Not fso.FolderExists(launcherState) Then fso.CreateFolder launcherState
    If Not fso.FolderExists(logs) Then fso.CreateFolder logs
    Err.Clear
    On Error GoTo 0

    ' /s strips the outer quote pair. BAT handles its log redirection.
    command = QuoteArgument(sh.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\cmd.exe") _
        & " /d /s /c " & Chr(34) & QuoteArgument(here & "\ArchHub.bat") _
        & " " & QuoteArgument(interpreter) & Chr(34)
    sh.Environment("PROCESS")("ARCHHUB_SETUP_LOG") = attempt
    result = RunAndWait(command, 0)
    launchError = runError
    If oldLog = "" Then
        sh.Environment("PROCESS").Remove "ARCHHUB_SETUP_LOG"
    Else
        sh.Environment("PROCESS")("ARCHHUB_SETUP_LOG") = oldLog
    End If
    TrimSetupTranscript attempt
    On Error Resume Next
    Set output = Nothing
    Set output = fso.OpenTextFile(attempt, 8, True)
    If Not output Is Nothing Then
        If launchError <> 0 Then output.WriteLine "ArchHub could not start setup (Windows error " & launchError & ")."
        output.WriteLine "ArchHub setup exit code: " & result
        output.Close
        Err.Clear
        fso.MoveFile attempt, logPath
        If Err.Number = 0 Then KeepLatestSetupLog logs, logPath
    End If
    Err.Clear
    On Error GoTo 0
    RunSetupHidden = result
End Function

Sub KeepLatestSetupLog(folder, publishedPath)
    Dim published, file, newer
    On Error Resume Next
    Set published = fso.GetFile(publishedPath)
    For Each file In fso.GetFolder(folder).Files
        If LCase(Left(file.Name, Len("archhub-setup-"))) = "archhub-setup-" _
                And LCase(Right(file.Name, Len(".tmp.log"))) = ".tmp.log" Then
            newer = (published.DateLastModified > file.DateLastModified) _
                Or ((published.DateLastModified = file.DateLastModified) _
                    And StrComp(published.Name, file.Name, 1) > 0)
            If newer Then fso.DeleteFile file.Path
        End If
    Next
    Err.Clear
    On Error GoTo 0
End Sub

Sub TrimSetupTranscript(attempt)
    Dim stream, startText, endText
    On Error Resume Next
    If Not fso.FileExists(attempt) Then Exit Sub
    If fso.GetFile(attempt).Size <= 65536 Then Exit Sub
    Set stream = fso.OpenTextFile(attempt)
    startText = stream.Read(16384)
    Do Until stream.AtEndOfStream Or Err.Number <> 0
        endText = stream.Read(16384)
    Loop
    stream.Close
    If Err.Number <> 0 Then Exit Sub
    Set stream = fso.CreateTextFile(attempt, True)
    stream.Write startText
    stream.WriteLine "[Middle of setup output omitted.]"
    stream.Write endText
    stream.Close
    Err.Clear
    On Error GoTo 0
End Sub

Sub StartUpdateMaintainer()
    Dim maintainer, homePy, cfgPath, cfgFile, line, trimmed, eq, homeDir
    maintainer = here & "\.venv\Scripts\pythonw.exe"
    If Not fso.FileExists(maintainer) Then maintainer = here & "\.venv\Scripts\python.exe"
    If Not fso.FileExists(maintainer) Then Exit Sub
    homePy = maintainer
    cfgPath = here & "\.venv\pyvenv.cfg"
    If fso.FileExists(cfgPath) Then
        Set cfgFile = fso.OpenTextFile(cfgPath, 1, False)
        Do While Not cfgFile.AtEndOfStream
            line = cfgFile.ReadLine
            trimmed = LTrim(line)
            eq = InStr(1, trimmed, "=", 1)
            If eq > 1 Then
                If LCase(Trim(Left(trimmed, eq - 1))) = "home" Then
                    homeDir = Trim(Mid(trimmed, eq + 1))
                    If fso.FileExists(homeDir & "\pythonw.exe") Then
                        homePy = homeDir & "\pythonw.exe"
                    ElseIf fso.FileExists(homeDir & "\python.exe") Then
                        homePy = homeDir & "\python.exe"
                    End If
                    Exit Do
                End If
            End If
        Loop
        cfgFile.Close
    End If
    ' The venv pythonw redirector remains a second process with this same
    ' command line for the whole run. The base interpreter is one process,
    ' still bound to this install by __PYVENV_LAUNCHER__.
    If StrComp(homePy, maintainer, vbTextCompare) <> 0 Then
        sh.Environment("PROCESS")("__PYVENV_LAUNCHER__") = maintainer
    End If
    sh.Run QuoteArgument(homePy) & " -E -s " & QuoteArgument(here & "\nodelang\quiet_update.py") _
        & " --maintain " & QuoteArgument(here), 0, False
    If StrComp(homePy, maintainer, vbTextCompare) <> 0 Then
        sh.Environment("PROCESS").Remove "__PYVENV_LAUNCHER__"
    End If
End Sub

Function RecoverFailedUpdate()
    Dim stateDir, result
    RecoverFailedUpdate = False
    If basePy = "" Then Exit Function
    stateDir = launcherState
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
