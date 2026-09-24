; Court fixture only: runs the SHIPPED uninstall ownership rules
; (installer/host_registrations.iss, included by ArchHub.iss) against folders
; the court names, then exits without installing anything. Never packaged.
;   /revit=<Addins root> /app=<install folder> /max=<3dsMax root>
;   /shipped=<shipped max_mcp_startup.py> /done=<file written when finished>

[Setup]
AppName=ArchHub uninstall court
AppVersion=1
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
OutputBaseFilename=host-uninstall-harness

[Code]
#include "..\installer\host_registrations.iss"

function InitializeSetup(): Boolean;
begin
  RemoveOwnRevitRegistrationsIn(ExpandConstant('{param:revit}'), ExpandConstant('{param:app}'));
  RemoveOwnMaxStartupScriptsIn(ExpandConstant('{param:max}'), ExpandConstant('{param:shipped}'));
  SaveStringToFile(ExpandConstant('{param:done}'), 'ran', False);
  Result := False;
end;
