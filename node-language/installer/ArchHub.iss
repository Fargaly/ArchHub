; ArchHub installer -- one double-click for a colleague.
;
; It carries the application, checks for a usable Python, installs the
; packages that are missing, and leaves a Start-menu and Desktop entry.
; Not signed (code-signing is geo-blocked for the founder's region);
; distributed on the firm share. The setup never runs a bare-named program.

#define AppName "ArchHub"
#define AppVersion "0"
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
Filename: "{app}\{#AppExe}"; Description: "Open ArchHub now"; Flags: postinstall nowait skipifsilent

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

function InitializeSetup(): Boolean;
begin
  { A colleague without Python is told plainly, never handed a broken app.
    A silent install proceeds and the launcher reports it on first run. }
  Result := True;
  if PythonPresent() then
    exit;
  if not WizardSilent() then
  begin
    MsgBox('ArchHub needs Python 3.11 or newer.' + #13#10 +
           'Install it from python.org (tick "Add python.exe to PATH"), then run this again.',
           mbInformation, MB_OK);
    Result := False;
  end;
end;
