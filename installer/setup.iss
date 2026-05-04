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
#define MyAppURL        "https://archhub.app"

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
CloseApplications=force
RestartApplications=no

; Optional: SetupIconFile=..\app\assets\archhub.ico  (when icon is designed)

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
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
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\ArchHub.cmd"; \
    WorkingDir: "{app}"; Comment: "Open ArchHub"
Name: "{userstartup}\{#MyAppName}";  Filename: "{app}\ArchHub-silent.cmd"; \
    WorkingDir: "{app}"; Tasks: startupshortcut

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

procedure WriteLauncherFiles;
var
  AppDir, PyExe, LauncherPath, SilentPath, Contents: string;
begin
  AppDir := ExpandConstant('{app}');

  // Prefer 'python', fall back to 'py'
  if PythonOnPath then
    PyExe := 'python'
  else
    PyExe := 'py';

  LauncherPath := AppDir + '\ArchHub.cmd';
  Contents := '@echo off' + #13#10 +
              'cd /d "' + AppDir + '"' + #13#10 +
              PyExe + ' "' + AppDir + '\app\main.py" %*' + #13#10;
  SaveStringToFile(LauncherPath, Contents, False);

  SilentPath := AppDir + '\ArchHub-silent.cmd';
  Contents := '@echo off' + #13#10 +
              'cd /d "' + AppDir + '"' + #13#10 +
              'start /min "" ' + PyExe + ' "' + AppDir + '\app\main.py" --silent' + #13#10;
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
  if CurStep = ssInstall then
    StopRunningArchHub
  else if CurStep = ssPostInstall then
  begin
    WriteLauncherFiles;
    WriteVersionStamp;
  end;
end;
