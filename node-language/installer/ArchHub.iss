; ArchHub installer -- one double-click for a colleague.
;
; It carries the application, fetches Python 3.14.7 from python.org (pinned
; SHA-256, per-user, no PATH change) when the machine has no usable Python,
; and leaves a Start-menu and Desktop entry. It does NOT install the
; Python packages: the FIRST open of either shortcut runs ArchHub.bat, which
; runs colleague_setup.py against requirements.txt in a window the person can
; read, and only then opens the application. Saying the installer installed
; them sent colleagues looking for a broken install when the real work had
; simply not run yet.
; Not signed (code-signing is geo-blocked for the founder's region);
; distributed on the firm share. The setup never runs a bare-named program.

#define AppName "ArchHub"
#define AppVersion "0"
; Every build has its own identity even though the beta ships under one label:
; the launcher compares BUILD_ID with the latest release to update quietly.
#ifndef BuildId
#define BuildId GetDateTimeString('yyyymmdd-hhnnss', '', '')
#endif
#define AppPublisher "Fargaly"
; Every shortcut opens ArchHub.vbs: it resolves the installed pythonw itself
; (a bare pythonw fails wherever Python was installed without Add-to-PATH)
; and hands a first run to ArchHub.bat, whose window stays open if setup
; refuses. ArchHub.bat is never a shortcut target.
#define AppExe "ArchHub.vbs"

[Setup]
; The AppId of the install already on every machine (v1.7.0), so Windows
; and Inno treat this as an UPGRADE of that entry -- one ArchHub in
; Apps & Features, same folder -- rather than a second product beside it.
AppId={{B6C0E10F-1F8E-4AAB-9A8F-4F2E3A2C4BAE}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\ArchHub
; The folder is fixed: a chooser would let one user aim the launcher at a
; folder another user can write to.
DisableDirPage=yes
DefaultGroupName=ArchHub
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=ArchHub-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\nodelang\*"; DestDir: "{app}\nodelang"; Flags: recursesubdirs ignoreversion
Source: "..\launch_archhub_test.py"; DestDir: "{app}"; Flags: ignoreversion
; The personal brain daemon (:8473) every user gets; the launcher starts it when none answers.
Source: "..\..\12.PRODUCTION\personal-brain-mcp\src\personal_brain\*"; DestDir: "{app}\personal_brain"; Flags: recursesubdirs ignoreversion
Source: "..\..\12.PRODUCTION\payload\rhino\archhub_mcp.py"; DestDir: "{app}\bridges\rhino"; Flags: ignoreversion
Source: "..\..\12.PRODUCTION\payload\blender\archhub_mcp\*"; DestDir: "{app}\bridges\blender\archhub_mcp"; Flags: recursesubdirs ignoreversion
Source: "..\colleague_setup.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "ArchHub.bat"; DestDir: "{app}"; Flags: ignoreversion
; Replaces the previous launcher of the same name, so every shortcut a
; colleague already has opens the new application. The old app\ tree is
; left in place: it still hosts the brain MCP server on :8473.
Source: "ArchHub.vbs"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\12.PRODUCTION\app\assets\archhub.ico"; DestDir: "{app}"; Flags: ignoreversion
; The skill library travels with the application: a colleague machine has
; no ~/.claude or ~/.codex, and a catalogue that only scanned those reported
; 0 skills everywhere but the founder desk. Snapshotted at build time from
; the machine that builds the installer.
Source: "{#GetEnv("USERPROFILE")}\.claude\skills\*"; DestDir: "{app}\skills\claude"; Flags: recursesubdirs ignoreversion skipifsourcedoesntexist
Source: "{#GetEnv("USERPROFILE")}\.codex\skills\*"; DestDir: "{app}\skills\codex"; Flags: recursesubdirs ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\ArchHub"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\archhub.ico"
Name: "{group}\Uninstall ArchHub"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ArchHub"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\archhub.ico"; Tasks: desktopicon

[Run]
; The first open prepares the machine before any window appears; a plain
; "Open ArchHub now" left people staring at a setup window they did not expect.
Filename: "{app}\{#AppExe}"; Description: "Open ArchHub now (the first open installs what it needs, in a window you can read)"; Flags: postinstall nowait skipifsilent

[Code]
function FindPython(): String;
var
  Base: String;
  Rec: TFindRec;
begin
  { Absolute paths only. A bare 'py' or 'python' is resolved from the
    installer's own folder first, so a file planted beside the setup on a
    share would run before the person has consented to anything. }
  Result := '';
  Base := ExpandConstant('{localappdata}') + '\Python';
  if FindFirst(Base + '\pythoncore*', Rec) then
  begin
    try
      repeat
        if (Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0) and
           FileExists(Base + '\' + Rec.Name + '\python.exe') then
          Result := Base + '\' + Rec.Name + '\python.exe';
      until not FindNext(Rec);
    finally
      FindClose(Rec);
    end;
  end;
  if Result <> '' then exit;
  Base := ExpandConstant('{localappdata}') + '\Programs\Python';
  if FindFirst(Base + '\Python3*', Rec) then
  begin
    try
      repeat
        if FileExists(Base + '\' + Rec.Name + '\python.exe') then
          Result := Base + '\' + Rec.Name + '\python.exe';
      until not FindNext(Rec);
    finally
      FindClose(Rec);
    end;
  end;
  if Result <> '' then exit;
  if FindFirst(ExpandConstant('{pf}') + '\Python3*', Rec) then
  begin
    try
      repeat
        if FileExists(ExpandConstant('{pf}') + '\' + Rec.Name + '\python.exe') then
          Result := ExpandConstant('{pf}') + '\' + Rec.Name + '\python.exe';
      until not FindNext(Rec);
    finally
      FindClose(Rec);
    end;
  end;
end;

function PythonPresent(): Boolean;
var
  Code: Integer;
  Py: String;
begin
  Result := False;
  Py := FindPython();
  if Py = '' then exit;
  if Exec(Py, '-c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"',
          '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0) then
    Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  { The installed build's identity, read by the quiet updater. }
  if CurStep = ssPostInstall then
    SaveStringToFile(ExpandConstant('{app}\BUILD_ID'), '{#BuildId}', False);
end;

{ A colleague without Python is not sent away: the setup fetches the
  python.org installer (pinned by SHA-256, over HTTPS) and runs it quietly
  for this user only, no PATH change, no py launcher; FindPython then finds
  it in the per-user Programs\Python folder. Same Python the founder runs. }
const
  PythonUrl = 'https://www.python.org/ftp/python/3.14.7/python-3.14.7-amd64.exe';
  PythonFile = 'python-3.14.7-amd64.exe';
  PythonSha256 = '9d9eb2709ef81bf5cd30db3c2096bdbc4ea10087c22e62f27d356b36f6ae9649';
  PythonArgs = '/quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0 Shortcuts=0';

var
  PythonPage: TDownloadWizardPage;
  PythonWanted: Boolean;

function OnPythonProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard();
begin
  PythonPage := CreateDownloadPage('Python',
    'ArchHub needs Python and this machine has none: fetching 3.14.7 from python.org.',
    @OnPythonProgress);
end;

function InstallPython(): Boolean;
var
  Code: Integer;
begin
  Result := False;
  PythonPage.Clear;
  PythonPage.Add(PythonUrl, PythonFile, PythonSha256);
  PythonPage.Show;
  try
    try
      PythonPage.Download;
    except
      SuppressibleMsgBox('Python could not be fetched from python.org: ' + GetExceptionMessage + #13#10 +
        'Install Python 3.11 or newer from python.org, then run this setup again.',
        mbCriticalError, MB_OK, IDOK);
      exit;
    end;
  finally
    PythonPage.Hide;
  end;
  if not Exec(ExpandConstant('{tmp}\' + PythonFile), PythonArgs, '', SW_SHOW, ewWaitUntilTerminated, Code) then
  begin
    SuppressibleMsgBox('The Python installer would not start.', mbCriticalError, MB_OK, IDOK);
    exit;
  end;
  if (Code <> 0) and (Code <> 3010) then
  begin
    SuppressibleMsgBox('The Python installer ended with code ' + IntToStr(Code) + '.', mbCriticalError, MB_OK, IDOK);
    exit;
  end;
  Result := PythonPresent();
  if not Result then
    SuppressibleMsgBox('Python was installed but could not be found afterwards. Install Python 3.11 or newer from python.org, then run this setup again.',
      mbCriticalError, MB_OK, IDOK);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpReady) and PythonWanted then
    Result := InstallPython();
end;

function InitializeSetup(): Boolean;
begin
  { No usable Python: the wizard fetches one before it copies ArchHub.
    A silent install proceeds and the launcher reports it on first run. }
  Result := True;
  PythonWanted := not PythonPresent();
  if PythonWanted and (not WizardSilent()) then
    MsgBox('This machine has no Python 3.11 or newer.' + #13#10 +
           'Setup will fetch Python 3.14.7 from python.org (about 33 MB) and install it for you only, before it installs ArchHub.',
           mbInformation, MB_OK);
end;
