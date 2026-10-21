; Court fixture only: a real Inno [Files] copy of bridges\ into a court folder,
; with the SHIPPED staging rules (installer/host_file_staging.iss). Never packaged.
;   ISCC /DPayloadPath=<folder holding bridges\ and abort.txt>
;   run: /app=<install folder> /done=<file written at the end>

[Setup]
AppName=ArchHub host staging court
AppVersion=1
DefaultDirName={param:app}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
Uninstallable=no
PrivilegesRequired=lowest
; As ArchHub.iss: never close or restart the application holding a file.
CloseApplications=no
RestartApplications=no
OutputBaseFilename=host-staging-harness

[Files]
Source: "{#PayloadPath}\bridges\*"; DestDir: "{app}\bridges"; Flags: recursesubdirs createallsubdirs ignoreversion
; Copied after bridges\; a court that puts a folder at {app}\abort.txt makes this copy
; fail, and the suppressed Abort/Retry/Ignore aborts setup as it did for 8890e2b.
Source: "{#PayloadPath}\abort.txt"; DestDir: "{app}"; Flags: ignoreversion

[Code]
#include "..\installer\host_file_staging.iss"

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    RetireLockedHostFiles(ExpandConstant('{app}'), 'court');
  if CurStep = ssPostInstall then
    HostFilesInstalled();
end;

procedure DeinitializeSetup();
begin
  RestoreRetiredHostFiles();
  SaveStringToFile(ExpandConstant('{param:done}'), 'ran', False);
end;