; ArchHub Installer — Inno Setup script.
; Builds a single double-clickable installer that bundles Python, all
; dependencies, the connector payloads, and ArchHub itself.
;
; Build via installer\build.bat (which downloads Python embeddable, pip-installs
; deps into it, then invokes Inno Setup Compiler to produce dist\ArchHub-Setup.exe).

#define MyAppName "ArchHub"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "Fargool / Bayaty"
#define MyAppURL "https://archhub.app"
#define MyAppExeName "ArchHub.exe"

[Setup]
AppId={{B6C0E10F-1F8E-4AAB-9A8F-4F2E3A2C4BAE}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\{#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ArchHub-Setup
SetupIconFile=..\app\assets\archhub.ico
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startupshortcut"; Description: "&Launch ArchHub when I sign in to Windows"; GroupDescription: "Startup options:"; Flags: checkedonce
Name: "desktopicon";    Description: "&Create a desktop shortcut";                  GroupDescription: "Shortcuts:";       Flags: checkedonce

[Files]
; Bundled Python embeddable distribution + pre-installed packages
; (downloaded and prepared by build.bat)
Source: "..\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs ignoreversion

; ArchHub Python source
Source: "..\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs ignoreversion

; Connector payloads (DLLs, addon scripts)
Source: "..\payload\*"; DestDir: "{app}\payload"; Flags: recursesubdirs ignoreversion

; Top-level launcher (built by PyInstaller in build.bat)
Source: "..\dist-staging\ArchHub.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\{#MyAppName}";  Filename: "{app}\{#MyAppExeName}"
Name: "{userdesktop}\{#MyAppName}";   Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}";   Filename: "{app}\{#MyAppExeName}"; Parameters: "--silent"; Tasks: startupshortcut

[Run]
Filename: "{app}\{#MyAppExeName}"; \
    Description: "Launch {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent
