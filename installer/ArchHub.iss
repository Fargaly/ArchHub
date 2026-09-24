; ArchHub installer -- one double-click for a colleague.
;
; It carries the application, fetches Python 3.14.7 from python.org (pinned
; SHA-256, per-user, no PATH change) when the machine has no usable Python,
; and leaves a Start-menu and Desktop entry. It does NOT install the
; Python packages: the FIRST open of either shortcut runs ArchHub.bat, which
; runs colleague_setup.py against requirements.txt (the DESKTOP list; server
; packages are in requirements-cloud.txt and never ship) in a window the
; person can read, installing from the wheelhouse this installer carries, so
; no internet or proxy is needed, and only then opens the application. Saying the installer installed
; them sent colleagues looking for a broken install when the real work had
; simply not run yet.
; Not signed (code-signing is geo-blocked for the founder's region);
; distributed on the firm share. The setup never runs a bare-named program.

#define AppName "ArchHub"
#define AppVersion "0"
; Every build has its own identity even though the beta ships under one label:
; the launcher compares BUILD_ID with the latest release to update quietly.
#ifndef BuildId
#error Build with installer/build_release.ps1: BuildId is required.
#endif
#ifndef RequirementsSha256
#error Build with installer/build_release.ps1: RequirementsSha256 is required.
#endif
#ifndef BuildMetadataPath
#error Build with installer/build_release.ps1: BuildMetadataPath is required.
#endif
#ifndef NodeRuntimePath
#error Build with installer/build_release.ps1: pinned NodeRuntimePath is required.
#endif
#ifndef NodeLicensePath
#error Build with installer/build_release.ps1: NodeLicensePath is required.
#endif
; Every desktop wheel for CPython 3.14 win_amd64, fetched by build_release.ps1
; from requirements.txt; colleague_setup.py installs from it with --no-index.
#ifndef WheelhousePath
#error Build with installer/build_release.ps1: WheelhousePath is required.
#endif
; The authenticated Revit add-in, compiled per Revit year by
; installer/build_revit_bridge.ps1 (bridges/revit/<year>/ + HOST_ARTIFACTS.json).
; Setup registers a year only when its manifest carries the custody review.
#ifndef HostPayloadPath
#error Build with installer/build_release.ps1: HostPayloadPath is required.
#endif
#define BundledNodeSha256 GetSHA256OfFile(NodeRuntimePath)
#define PayloadExcludes "__pycache__\*,*.pyc,*.pyo,.env,.env.*,*.sqlite3,*.sqlite3-*,*.db,*.db-*,*.key,*.pem"
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
CompressionThreads=1
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
; ArchHub owns its explicit update handoff. Restart Manager must not close
; or restart other applications when this installer runs silently.
CloseApplications=no
RestartApplications=no
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#NodeRuntimePath}"; DestDir: "{app}\runtime"; DestName: "node.exe"; Flags: ignoreversion; Check: NodeRuntimeNeedsInstall
Source: "{#NodeLicensePath}"; DestDir: "{app}\runtime"; DestName: "Node-LICENSE.txt"; Flags: ignoreversion
Source: "..\nodelang\*"; DestDir: "{app}\nodelang"; Excludes: "{#PayloadExcludes}"; Flags: recursesubdirs ignoreversion
Source: "..\launch_archhub_test.py"; DestDir: "{app}"; Flags: ignoreversion
; Generated once for this exact build; pairs with BUILD_ID after installation.
Source: "{#BuildMetadataPath}"; DestDir: "{app}"; DestName: "BUILD_METADATA.json"; Flags: ignoreversion
; Public credential-store code only. Every user's protected data stays local.
Source: "..\app\secrets_store.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\credential_lock.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\__init__.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\packaging\windows\licenses\ArchHub-components-MIT.txt"; DestDir: "{app}\licenses"; Flags: ignoreversion
; Read-only physical observer closure; no Brain server or background launcher.
Source: "..\personal_brain\__init__.py"; DestDir: "{app}\personal_brain"; Flags: ignoreversion
Source: "..\personal_brain\hook_coverage.py"; DestDir: "{app}\personal_brain"; Flags: ignoreversion
Source: "..\personal_brain\installer.py"; DestDir: "{app}\personal_brain"; Flags: ignoreversion
Source: "..\personal_brain\ambient_policy.py"; DestDir: "{app}\personal_brain"; Flags: ignoreversion
Source: "..\bridges\rhino\archhub_mcp.py"; DestDir: "{app}\bridges\rhino"; Flags: ignoreversion
Source: "..\bridges\blender\archhub_mcp\__init__.py"; DestDir: "{app}\bridges\blender\archhub_mcp"; Flags: ignoreversion
Source: "..\bridges\sources\max_mcp\max_mcp_startup.py"; DestDir: "{app}\bridges\max"; Flags: ignoreversion
; Compiled add-in closure per Revit year the build machine carries; none when it carries none.
Source: "{#HostPayloadPath}\bridges\revit\*"; DestDir: "{app}\bridges\revit"; Flags: recursesubdirs createallsubdirs ignoreversion skipifsourcedoesntexist
Source: "{#HostPayloadPath}\HOST_ARTIFACTS.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\colleague_setup.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#WheelhousePath}\*.whl"; DestDir: "{app}\wheelhouse"; Flags: ignoreversion
Source: "ArchHub.bat"; DestDir: "{app}"; Flags: ignoreversion
; Replaces the previous launcher of the same name. Existing user state and
; old installation files are not recursively deleted by this package.
Source: "ArchHub.vbs"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\archhub.ico"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; Retired launchers target app/main.py; supported shortcuts use ArchHub.vbs.
Type: files; Name: "{app}\ArchHub.cmd"
Type: files; Name: "{app}\ArchHub-silent.cmd"
; Superseded installer helpers recreate those retired app/main.py launchers.
; The supported package owns setup and shortcuts directly; no directory sweep.
Type: files; Name: "{app}\installer\install_gui.ps1"
Type: files; Name: "{app}\installer\make_shortcuts.ps1"
Type: files; Name: "{app}\installer\setup.iss"
; Exact retired implementation only. Keep the current connector owner,
; credentials, databases and unrelated installed files intact on upgrade.
Type: files; Name: "{app}\nodelang\cell_baboom_connector_execution.py"
Type: files; Name: "{app}\nodelang\cell_baboom_connector_execution.pyc"
Type: files; Name: "{app}\nodelang\cell_baboom_connector_execution.pyo"
Type: files; Name: "{app}\nodelang\__pycache__\cell_baboom_connector_execution.*.pyc"
; The wheelhouse is this build's alone; an older build's wheels never mix in.
Type: files; Name: "{app}\wheelhouse\*.whl"

[Icons]
Name: "{group}\ArchHub"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\archhub.ico"
Name: "{group}\Uninstall ArchHub"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ArchHub"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\archhub.ico"; Tasks: desktopicon

[Run]
; The first open prepares the machine before any window appears; a plain
; "Open ArchHub now" left people staring at a setup window they did not expect.
Filename: "{app}\{#AppExe}"; Description: "Open ArchHub now (the first open installs what it needs, in a window you can read)"; Flags: shellexec postinstall nowait skipifsilent

[Code]
#include "legacy_sweep.iss"

(* Uninstall removes only the Revit add-in registrations THIS installation made:
  a per-user RevitMCP.addin whose text loads the add-in from the install folder's
  bridges\revit\. Registrations that load from anywhere else (another install, a v1
  payload\, a developer build) are foreign and stay. Revit reads the change at its
  next start. *)
procedure RemoveOwnRevitRegistrations();
var
  Base, Owned: String;
  Years: TFindRec;
  Manifest: String;
  Text: AnsiString;
begin
  Base := ExpandConstant('{userappdata}') + '\Autodesk\Revit\Addins';
  Owned := Lowercase(ExpandConstant('{app}') + '\bridges\revit\');
  if FindFirst(Base + '\*', Years) then
  begin
    try
      repeat
        if ((Years.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) and
           (Years.Name <> '.') and (Years.Name <> '..') then
        begin
          Manifest := Base + '\' + Years.Name + '\RevitMCP.addin';
          if FileExists(Manifest) and LoadStringFromFile(Manifest, Text) and
             (Pos(Owned, Lowercase(String(Text))) > 0) then
          begin
            if DeleteFile(Manifest) then
              Log('Removed ArchHub Revit add-in registration ' + Manifest)
            else
              Log('Could not remove ArchHub Revit add-in registration ' + Manifest);
          end;
        end;
      until not FindNext(Years);
    finally
      FindClose(Years);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RemoveOwnRevitRegistrations();
end;

function NodeRuntimeNeedsInstall(): Boolean;
var
  InstalledRuntime: String;
begin
  InstalledRuntime := ExpandConstant('{app}\runtime\node.exe');
  Result := True;
  if FileExists(InstalledRuntime) then
  begin
    { Session Link may still use this executable after the desktop closes.
      Keep identical bytes in place; an unreadable file fails installation. }
    Result := CompareText(GetSHA256OfFile(InstalledRuntime), '{#BundledNodeSha256}') <> 0;
    if not Result then
      Log('Bundled Node runtime already matches SHA-256; preserving active Session Link processes.');
  end;
end;

function VersionScore(Name: String): Integer;
var
  I, Major, Minor: Integer;
  Digits: String;
  SeenDot: Boolean;
begin
  { "Python314" -> 314, "Python39" -> 39, "pythoncore-3.14-64" -> 314,
    "Python3" -> 3: enough to rank a fresh 3.14 above an older 3.x that
    sorts after it alphabetically (Python39 > Python314 as strings). }
  Major := 0; Minor := 0; Digits := ''; SeenDot := False;
  for I := 1 to Length(Name) do
  begin
    if (Name[I] >= '0') and (Name[I] <= '9') then
      Digits := Digits + Name[I]
    else if (Name[I] = '.') and (Digits <> '') and not SeenDot then
    begin
      Major := StrToIntDef(Digits, 0); Digits := ''; SeenDot := True;
    end
    else if Digits <> '' then
      break;
  end;
  if SeenDot then
    Result := Major * 100 + StrToIntDef(Digits, 0)
  else
    Result := StrToIntDef(Digits, 0);
end;

function PythonRuns(Py: String): Boolean;
var
  Code: Integer;
begin
  Result := Exec(Py, '-c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"',
                 '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

function BestPythonUnder(Base, Pattern: String): String;
var
  Rec: TFindRec;
  Best: Integer;
  Candidate: String;
begin
  { Every matching folder is a candidate; the highest version that really
    answers 3.11+ wins. The old code kept whichever folder FindNext listed
    last, so a fresh Python314 lost to an older sibling (audit 2026-09-06). }
  Result := ''; Best := -1;
  if FindFirst(Base + '\' + Pattern, Rec) then
  begin
    try
      repeat
        if (Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0) then
        begin
          Candidate := Base + '\' + Rec.Name + '\python.exe';
          if FileExists(Candidate) and (VersionScore(Rec.Name) > Best) and PythonRuns(Candidate) then
          begin
            Best := VersionScore(Rec.Name);
            Result := Candidate;
          end;
        end;
      until not FindNext(Rec);
    finally
      FindClose(Rec);
    end;
  end;
end;

function FindPython(): String;
begin
  { Absolute paths only. A bare 'py' or 'python' is resolved from the
    installer's own folder first, so a file planted beside the setup on a
    share would run before the person has consented to anything. The three
    places python.org and the Python install manager write to, per user
    first, then all users. }
  Result := BestPythonUnder(ExpandConstant('{localappdata}') + '\Python', 'pythoncore*');
  if Result <> '' then exit;
  Result := BestPythonUnder(ExpandConstant('{localappdata}') + '\Programs\Python', 'Python3*');
  if Result <> '' then exit;
  Result := BestPythonUnder(ExpandConstant('{pf}'), 'Python3*');
end;

function PythonPresent(): Boolean;
begin
  { FindPython only returns a python.exe that already answered 3.11+. }
  Result := FindPython() <> '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ReadyPath: String;
  ReadyIdentity: AnsiString;
begin
  { Match the private-environment receipt schema used by colleague_setup.py.
    Preserve a same-build receipt; invalidate older setup BEFORE replacing
    application files. The launcher independently validates the environment. }
  if CurStep = ssInstall then
  begin
    { v1.x left its whole code tree beside this one; sweep it once, guarded. }
    SweepLegacyV1(ExpandConstant('{app}'));
    ReadyPath := ExpandConstant('{app}\.archhub-ready');
    if FileExists(ReadyPath) then
      if (not LoadStringFromFile(ReadyPath, ReadyIdentity)) or
         (Trim(String(ReadyIdentity)) <> 'venv-v1:{#BuildId}:{#RequirementsSha256}') then
        if not DeleteFile(ReadyPath) then
          RaiseException('The previous ArchHub setup marker could not be reset. Close ArchHub and retry setup.');
  end;
  { The installed build's identity, read by setup and the quiet updater. }
  if CurStep = ssPostInstall then
    if not SaveStringToFile(ExpandConstant('{app}\BUILD_ID'), '{#BuildId}', False) then
      RaiseException('The ArchHub build identity could not be saved. Run setup again.');
end;

{ A colleague without Python is not sent away: the setup fetches the
  python.org installer (pinned by SHA-256, over HTTPS) and runs it quietly
  for this user only, no PATH change, no py launcher; FindPython then finds
  it in the per-user Programs\Python folder. Same Python the founder runs. }
const
  PythonUrl = 'https://www.python.org/ftp/python/3.14.7/python-3.14.7-amd64.exe';
  PythonFile = 'python-3.14.7-amd64.exe';
  PythonSha256 = '9d9eb2709ef81bf5cd30db3c2096bdbc4ea10087c22e62f27d356b36f6ae9649';
  { CPython's WiX/Burn bootstrapper honors /norestart. The outer Inno
    restart controls do not propagate into this prerequisite process.
    Sources: github.com/wixtoolset/wix3/blob/develop/src/burn/engine/core.cpp
    and github.com/python/cpython/blob/3.14/Tools/msi/bundle/bootstrap/PythonBootstrapperApplication.cpp }
  PythonArgs = '/quiet /norestart InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0 Shortcuts=0';

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
      if PythonPage.AbortedByUser then
        SuppressibleMsgBox('You stopped the Python download, so ArchHub was not installed.' + #13#10 +
          'Run this setup again when you are ready, or install Python 3.11 or newer from python.org first.',
          mbInformation, MB_OK, IDOK)
      else
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
  { CPython returns Windows ERROR_SUCCESS_REBOOT_REQUIRED (3010) or
    ERROR_SUCCESS_REBOOT_INITIATED (1641), not proof of a usable runtime.
    See learn.microsoft.com/en-us/windows/win32/msi/error-codes.
    Never request an outer restart or continue installation on either result. }
  if Code = 3010 then
  begin
    Log('Python prerequisite requires a restart (3010); ArchHub installation cannot continue yet.');
    SuppressibleMsgBox('Python requires a Windows restart to finish installation. ArchHub setup will not continue yet.' + #13#10 +
      'Save your work and restart Windows when you choose, then run this setup again.',
      mbInformation, MB_OK, IDOK);
    exit;
  end;
  if Code = 1641 then
  begin
    Log('Python prerequisite reported restart initiated (1641) despite /norestart; stopping ArchHub installation.');
    SuppressibleMsgBox('The Python installer reported that a Windows restart was initiated despite restart suppression.' + #13#10 +
      'ArchHub setup will not continue. Check the system state before running setup again.',
      mbCriticalError, MB_OK, IDOK);
    exit;
  end;
  if Code <> 0 then
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
