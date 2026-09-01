; ArchHub installer -- one double-click for a colleague.
;
; It carries the application, checks for a usable Python, installs the
; packages that are missing, and leaves a Start-menu and Desktop entry.
; Nothing is signed yet, so the package is meant to travel on the firm
; share, where Windows attaches no mark-of-the-web and raises no warning.

#define AppName "ArchHub"
#define AppVersion "1.5.0"
#define AppPublisher "Fargaly"
#define AppExe "ArchHub.bat"

[Setup]
AppId={{8B6A2E31-3F4C-4E77-9C21-ARCHHUB000001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\ArchHub
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
Source: "..\..\12.PRODUCTION\app\assets\archhub.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\ArchHub"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\archhub.ico"
Name: "{group}\Uninstall ArchHub"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ArchHub"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\archhub.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open ArchHub now"; Flags: postinstall nowait skipifsilent

[Code]
function PythonPresent(): Boolean;
var
  Code: Integer;
begin
  { Two honest attempts, no shell operators: the launcher and the plain
    interpreter. Either answering 3.11+ is enough. }
  Result := False;
  if Exec('py', '-3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"',
          '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0) then
  begin
    Result := True;
    exit;
  end;
  if Exec('python', '-c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"',
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
