#ifndef AppVersion
  #error AppVersion must be supplied by build.ps1
#endif
#ifndef BundleDir
  #error BundleDir must be supplied by build.ps1
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by build.ps1
#endif

#define AppName "ArchHub"
#define AppPublisher "ArchHub"
#define AppURL "https://archhub.io"
#define AppId "{{24DE810A-4D34-4FD6-96E5-6008FC09B9B4}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=ArchHub-Setup-{#AppVersion}-x64
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ChangesEnvironment=no
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\ArchHub.exe
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} per-user installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "Launch-ArchHub.vbs"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\Launch-ArchHub.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\ArchHub.exe"; Comment: "Open ArchHub"
Name: "{userdesktop}\{#AppName}"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\Launch-ArchHub.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\ArchHub.exe"; Tasks: desktopicon; Comment: "Open ArchHub"

[Run]
Filename: "{sys}\wscript.exe"; Parameters: """{app}\Launch-ArchHub.vbs"""; WorkingDir: "{app}"; Description: "Open {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeUninstall(): Boolean;
begin
  { The WIP graph is deliberately outside the installation directory. }
  Result := True;
end;
