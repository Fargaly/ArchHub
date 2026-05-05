Dim oShell, oFSO, oFile, sResult

Set oShell = CreateObject("WScript.Shell")
Set oFSO = CreateObject("Scripting.FileSystemObject")

' First: delete stale obj\ so restore is forced fresh
Dim objDir
objDir = "C:\Users\fargaly\00.ARCHUB\ArchHub\payload\sources\revit_mcp\obj"
If oFSO.FolderExists(objDir) Then
    oFSO.DeleteFolder objDir, True
End If

' Run the Python build script, wait for it to finish (True), hidden (0)
Dim sCmd
sCmd = "cmd /c ""cd /d C:\Users\fargaly\00.ARCHUB\ArchHub\app && py do_build_2023.py"""
oShell.Run sCmd, 0, True

' Show result
If oFSO.FileExists("C:\Users\fargaly\00.ARCHUB\ArchHub\build_output.txt") Then
    Set oFile = oFSO.OpenTextFile("C:\Users\fargaly\00.ARCHUB\ArchHub\build_output.txt", 1)
    sResult = oFile.ReadAll()
    oFile.Close
    MsgBox sResult, 64, "Revit 2023 Build Result"
Else
    MsgBox "build_output.txt not found. Script may have failed.", 16, "Build Error"
End If
