Option Explicit

' Portable, no-console launcher installed beside the bundled ArchHub.exe.
Dim shell, fso, appDir, executable, stateDir, statePath, command, dryRun
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
executable = fso.BuildPath(appDir, "ArchHub.exe")
stateDir = fso.BuildPath(shell.ExpandEnvironmentStrings("%LOCALAPPDATA%"), "ArchHub")
statePath = fso.BuildPath(stateDir, "node-native-wip.json.gz")
command = Chr(34) & executable & Chr(34)
dryRun = WScript.Arguments.Count = 1 And LCase(WScript.Arguments(0)) = "--dry-run"

If dryRun Then
    WScript.Echo "executable=" & executable
    WScript.Echo "working_directory=" & appDir
    WScript.Echo "state_path=" & statePath
    WScript.Echo "window_style=0"
    WScript.Echo "wait=false"
    WScript.Quit 0
End If

If Not fso.FileExists(executable) Then
    MsgBox "ArchHub.exe is missing. Repair or reinstall ArchHub.", 16, "ArchHub"
    WScript.Quit 2
End If

If Not fso.FolderExists(stateDir) Then fso.CreateFolder(stateDir)
shell.Environment("PROCESS")("ARCHHUB_STATE_PATH") = statePath
shell.CurrentDirectory = appDir
shell.Run command, 0, False
