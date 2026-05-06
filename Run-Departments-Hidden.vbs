' Launches Run-Departments.bat with no visible console window so the
' departments daemon can run 24/7 without a console hogging the
' taskbar. Pair with Stop-Departments.bat to shut it down.
'
' Usage:
'   Double-click this file. Nothing visibly happens, but the daemon is
'   running in the background. Check `agents\logs\` for activity.
'
'   To run it on every login, drop a shortcut to this .vbs into:
'     %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
'
' To stop: double-click Stop-Departments.bat (or kill python.exe running
' "agents.run" in Task Manager).

Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here
' 0 = hidden, False = don't wait for completion.
sh.Run """" & here & "\Run-Departments.bat""", 0, False
