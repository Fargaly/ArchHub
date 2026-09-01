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
DefaultDirName={autopf}\ArchHub
DefaultGroupName=ArchHub
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=ArchHub-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
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
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  { A colleague without Python gets told plainly, not a broken app. }
  if not Exec('cmd.exe', '/c py -3 --version >nul 2>&1 || python --version >nul 2>&1',
              '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
  begin
    MsgBox('ArchHub needs Python 3.11 or newer.' + #13#10 +
           'Install it from python.org (tick "Add python.exe to PATH"), then run this again.',
           mbInformation, MB_OK);
    Result := False;
    exit;
  end;
  Result := True;
end;
