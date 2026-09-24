(* Host registrations this installation owns: Revit add-in manifests and the
  3ds Max startup script. Shared by ArchHub.iss and its behavioural court
  (tests_replica/host_uninstall_harness.iss).

  Revit add-in registrations.

  Setup (colleague_setup.register_revit_add_ins, through
  nodelang/host_broker_installation.py) writes one per-user
  Addins\<year>\RevitMCP.addin per registered year, UTF-8 XML whose <Assembly>
  lies under the install folder's bridges\revit\. Uninstall removes exactly
  those: a RevitMCP.addin that loads from anywhere else (another install, a
  v1 payload\, a developer build) is foreign and stays. The file is decoded
  as UTF-8, so an install folder with non-ASCII characters still matches, and
  the XML-escaped form of '&' is matched too. Revit reads the change at its
  next start.

  3ds Max startup scripts. Setup (colleague_setup.register_max_startup) copies
  the shipped bridges\max\max_mcp_startup.py into each installed version's
  per-user ENU\scripts\startup folder. Uninstall removes a startup script only
  when it is byte-identical (SHA-256) to the one this installation shipped;
  an edited or foreign script stays. *)

function RevitRegistrationOwned(const Manifest, AppDir: String): Boolean;
var
  Raw: AnsiString;
  Text, Owned, Escaped: String;
begin
  Result := False;
  if not LoadStringFromFile(Manifest, Raw) then
    exit;
  Text := Lowercase(UTF8Decode(Raw));
  Owned := Lowercase(RemoveBackslashUnlessRoot(AppDir) + '\bridges\revit\');
  Escaped := Owned;
  StringChangeEx(Escaped, '&', '&amp;', True);
  Result := (Pos(Owned, Text) > 0) or (Pos(Escaped, Text) > 0);
end;

procedure RemoveOwnRevitRegistrationsIn(const Base, AppDir: String);
var
  Years: TFindRec;
  Manifest: String;
begin
  if FindFirst(Base + '\*', Years) then
  begin
    try
      repeat
        if ((Years.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) and
           (Years.Name <> '.') and (Years.Name <> '..') then
        begin
          Manifest := Base + '\' + Years.Name + '\RevitMCP.addin';
          if FileExists(Manifest) and RevitRegistrationOwned(Manifest, AppDir) then
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

procedure RemoveOwnMaxStartupScriptsIn(const Base, ShippedScript: String);
var
  Versions: TFindRec;
  Script, Shipped: String;
  Same: Boolean;
begin
  if not FileExists(ShippedScript) then
    exit;
  try
    Shipped := GetSHA256OfFile(ShippedScript);
  except
    exit;
  end;
  if FindFirst(Base + '\*', Versions) then
  begin
    try
      repeat
        if ((Versions.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) and
           (Versions.Name <> '.') and (Versions.Name <> '..') then
        begin
          Script := Base + '\' + Versions.Name + '\ENU\scripts\startup\max_mcp_startup.py';
          Same := False;
          if FileExists(Script) then
          try
            Same := CompareText(GetSHA256OfFile(Script), Shipped) = 0;
          except
            Log('Could not read 3ds Max startup script ' + Script);
          end;
          if Same then
          begin
            if DeleteFile(Script) then
              Log('Removed ArchHub 3ds Max startup script ' + Script)
            else
              Log('Could not remove ArchHub 3ds Max startup script ' + Script);
          end;
        end;
      until not FindNext(Versions);
    finally
      FindClose(Versions);
    end;
  end;
end;
