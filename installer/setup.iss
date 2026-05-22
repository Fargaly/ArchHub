; ArchHub Installer — Inno Setup script.
;
; To build the installer:
;   1. Install Inno Setup 6 from https://jrsoftware.org/isdl.php (free, ~15 MB)
;   2. Open this file in Inno Setup Compiler (or right-click → Compile)
;   3. Out pops dist\ArchHub-Setup.exe
;
; That's it. No external build steps, no Python bundling, no PyInstaller.
; The .exe expects the user to have Python 3.10+ already installed (links
; them to python.org if not).

#define MyAppName       "ArchHub"
#define MyAppPublisher  "Fargool"
#define MyAppURL        "https://archhub.io"

; Read version string from the VERSION file at compile time
#define MyAppVersion Trim(FileRead(FileOpen(SourcePath + "..\VERSION")))

[Setup]
AppId={{B6C0E10F-1F8E-4AAB-9A8F-4F2E3A2C4BAE}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

DefaultDirName={localappdata}\{#MyAppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest

OutputDir=..\dist
OutputBaseFilename=ArchHub-Setup-{#MyAppVersion}

Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

UninstallDisplayName={#MyAppName}
UninstallFilesDir={app}\uninstall
; ArchHub handles closing itself in [Code] for normal installs. Staged
; background updates pass /NOCLOSEAPPLICATIONS and /ARCHHUB_STAGE=1 so the
; running app can keep working until the user clicks Restart.
CloseApplications=no
RestartApplications=no

SetupIconFile=..\app\assets\archhub.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Place a desktop icon"; \
    GroupDescription: "Shortcuts:"; Flags: checkedonce
Name: "startupshortcut"; Description: "Launch ArchHub when I sign in to Windows"; \
    GroupDescription: "Startup options:"; Flags: checkedonce

[Files]
; Application code
Source: "..\app\*";       DestDir: "{app}\app";       Flags: recursesubdirs ignoreversion
Source: "..\payload\*";   DestDir: "{app}\payload";   Flags: recursesubdirs ignoreversion
Source: "..\installer\*"; DestDir: "{app}\installer"; Flags: recursesubdirs ignoreversion

; Top-level files
Source: "..\VERSION";          DestDir: "{app}"
Source: "..\requirements.txt"; DestDir: "{app}"
Source: "..\README.md";        DestDir: "{app}"; Flags: skipifsourcedoesntexist
Source: "..\LICENSE";          DestDir: "{app}"; Flags: skipifsourcedoesntexist

; Launcher .cmd files written at runtime by [Code] section below.

[Icons]
; Shortcuts launch via wscript.exe + ArchHub.vbs so there is NO
; console window. .cmd-based shortcuts inherit a CMD host window
; even when they call pythonw, which is why we route through a
; .vbs. The .cmd launchers stay around for power users / `--diagnose`
; from a manually-opened terminal.
Name: "{userprograms}\{#MyAppName}"; Filename: "wscript.exe"; \
    Parameters: """{app}\ArchHub.vbs"""; \
    WorkingDir: "{app}"; Comment: "Open ArchHub"; \
    IconFilename: "{app}\app\assets\archhub.ico"
Name: "{userdesktop}\{#MyAppName}";  Filename: "wscript.exe"; \
    Parameters: """{app}\ArchHub.vbs"""; \
    WorkingDir: "{app}"; Tasks: desktopicon; \
    IconFilename: "{app}\app\assets\archhub.ico"
Name: "{userstartup}\{#MyAppName}";  Filename: "wscript.exe"; \
    Parameters: """{app}\ArchHub.vbs"" --silent"; \
    WorkingDir: "{app}"; Tasks: startupshortcut; \
    IconFilename: "{app}\app\assets\archhub.ico"

[Run]
; Install Python dependencies. Quiet, user-scoped, won't fail the install.
Filename: "python"; Parameters: "-m pip install --user --upgrade --quiet --disable-pip-version-check -r ""{app}\requirements.txt"""; \
    StatusMsg: "Installing Python packages (this happens once)..."; \
    Flags: runhidden waituntilterminated; \
    BeforeInstall: VerifyPythonExists

; Optional final launch from the wizard's Finish page
Filename: "{app}\ArchHub.cmd"; Description: "Launch {#MyAppName}"; \
    WorkingDir: "{app}"; \
    Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
; Wipe non-tracked runtime files on uninstall (caches, version stamp).
; Workflows, state.json, secrets.dat, and built payload binaries are deliberately
; preserved by NOT listing payload/revit, payload/autocad, payload/max,
; workflows, state.json, or secrets.dat here.
Type: files;          Name: "{app}\version.json"
Type: files;          Name: "{app}\ArchHub.cmd"
Type: files;          Name: "{app}\ArchHub-silent.cmd"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\app\__pycache__"

[Code]
function PythonOnPath: Boolean;
var
  ResultCode: Integer;
begin
  // Try `python --version` silently; success means it's on PATH.
  Result := Exec('cmd.exe', '/c python --version >nul 2>&1', '',
                 SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
  if not Result then
    Result := Exec('cmd.exe', '/c py --version >nul 2>&1', '',
                   SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function IsStageInstall: Boolean;
begin
  Result := ExpandConstant('{param:ARCHHUB_STAGE|0}') = '1';
end;

procedure VerifyPythonExists;
var
  Answer: Integer;
begin
  if not PythonOnPath then
  begin
    Answer := MsgBox(
      'ArchHub needs Python 3.10 or newer.' + #13#10 + #13#10 +
      'It looks like Python isn''t installed yet.' + #13#10 +
      'Click OK to open the Python download page, then run this installer again.' + #13#10 + #13#10 +
      'Or click Cancel to continue anyway (the install will finish but the app won''t launch).',
      mbConfirmation, MB_OKCANCEL);
    if Answer = IDOK then
      ShellExec('open', 'https://www.python.org/downloads/', '', '', SW_SHOW, ewNoWait, Answer);
  end;
end;

procedure StopRunningArchHub;
var
  ResultCode: Integer;
begin
  // Stop any running ArchHub before we replace files. Match by command line.
  Exec('powershell.exe',
       '-NoProfile -WindowStyle Hidden -Command "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like ''*ArchHub\app\main.py*'' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1500);
end;

procedure WriteVbsLauncher;
var
  AppDir, VbsPath, Contents: string;
begin
  AppDir := ExpandConstant('{app}');
  VbsPath := AppDir + '\ArchHub.vbs';
  Contents :=
    '''' + ' ArchHub launcher — wscript.exe runs this with no console.' + #13#10 +
    '''' + ' pythonw.exe inherits the no-console state, so the GUI starts clean.' + #13#10 +
    'Option Explicit' + #13#10 +
    'Dim sh, fso, here, py, args, i, cmd' + #13#10 +
    'Set sh  = CreateObject("WScript.Shell")' + #13#10 +
    'Set fso = CreateObject("Scripting.FileSystemObject")' + #13#10 +
    'here = fso.GetParentFolderName(WScript.ScriptFullName)' + #13#10 +
    'sh.CurrentDirectory = here' + #13#10 +
    'args = ""' + #13#10 +
    'For i = 0 To WScript.Arguments.Count - 1' + #13#10 +
    '    args = args & " """ & WScript.Arguments(i) & """"' + #13#10 +
    'Next' + #13#10 +
    'py = "pythonw"' + #13#10 +
    'On Error Resume Next' + #13#10 +
    'sh.Run "cmd /c where pythonw >nul 2>&1", 0, True' + #13#10 +
    'If Err.Number <> 0 Then py = "py -3w"' + #13#10 +
    'On Error GoTo 0' + #13#10 +
    'cmd = py & " """ & here & "\app\main.py""" & args' + #13#10 +
    'sh.Run cmd, 0, False' + #13#10;
  SaveStringToFile(VbsPath, Contents, False);
end;

procedure WriteLauncherFiles;
var
  AppDir, PyExe, PyWExe, LauncherPath, SilentPath, Contents: string;
begin
  AppDir := ExpandConstant('{app}');

  // Two binaries:
  //   PyExe  — has a console attached; used only for `--diagnose` /
  //            stderr-on-crash situations from the .cmd fallback.
  //   PyWExe — windowed launcher, no console window. Default UX.
  if PythonOnPath then
  begin
    PyExe  := 'python';
    PyWExe := 'pythonw';
  end
  else
  begin
    // `py -3w` is the windowed equivalent of `py`.
    PyExe  := 'py';
    PyWExe := 'py -3w';
  end;

  // Main launcher: pythonw, no console window. `start "" /b` keeps
  // .cmd from inheriting any console focus when double-clicked.
  LauncherPath := AppDir + '\ArchHub.cmd';
  Contents := '@echo off' + #13#10 +
              'cd /d "' + AppDir + '"' + #13#10 +
              'start "" /b ' + PyWExe + ' "' + AppDir + '\app\main.py" %*' + #13#10;
  SaveStringToFile(LauncherPath, Contents, False);

  // Silent / startup launcher — same windowed binary, --silent flag.
  SilentPath := AppDir + '\ArchHub-silent.cmd';
  Contents := '@echo off' + #13#10 +
              'cd /d "' + AppDir + '"' + #13#10 +
              'start "" /b ' + PyWExe + ' "' + AppDir + '\app\main.py" --silent' + #13#10;
  SaveStringToFile(SilentPath, Contents, False);
end;

procedure WriteVersionStamp;
var
  AppDir, VersionPath, Contents, Now: string;
begin
  AppDir := ExpandConstant('{app}');
  VersionPath := AppDir + '\version.json';

  // ISO-8601-ish timestamp (Inno's GetDateTimeString)
  Now := GetDateTimeString('yyyy/mm/dd''T''hh:nn:ss', '-', ':');

  Contents :=
    '{' + #13#10 +
    '  "version": "{#MyAppVersion}",' + #13#10 +
    '  "installed_at": "' + Now + '",' + #13#10 +
    '  "install_dir": "' + AppDir + '",' + #13#10 +
    '  "installer": "inno"' + #13#10 +
    '}' + #13#10;
  SaveStringToFile(VersionPath, Contents, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssInstall) and (not IsStageInstall) then
    StopRunningArchHub
  else if CurStep = ssPostInstall then
  begin
    WriteLauncherFiles;
    WriteVbsLauncher;
    WriteVersionStamp;
  end;
end;
