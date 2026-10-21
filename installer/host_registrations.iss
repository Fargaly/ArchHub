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
  an edited or foreign script stays.

  AutoCAD bundle. Setup (colleague_setup.register_autocad_add_ins, through
  nodelang/autocad_broker_installation.py) writes the per-user
  ApplicationPlugins\ArchHub.AcadMCP.bundle and lists every file it placed in
  its archhub-bundle.sha256 ("sha256  relative/path" lines). Uninstall deletes
  each listed file whose SHA-256 still matches, then the list, then only the
  folders left empty; a file someone else added or edited stays, and nothing
  is followed through a junction or other reparse point. *)

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

function IsReparsePoint(const Path: String): Boolean;
var
  Rec: TFindRec;
begin
  Result := False;
  if FindFirst(Path, Rec) then
  try
    Result := (Rec.Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0;
  finally
    FindClose(Rec);
  end;
end;

{ True when the bundle or any folder or file on the way to Relative is a
  junction, symlink or other reparse point: uninstall never follows one. }
function BundlePathRedirected(const Bundle, Relative: String): Boolean;
var
  Rest, Current, Part: String;
  Split: Integer;
begin
  Result := IsReparsePoint(Bundle);
  Current := Bundle;
  Rest := Relative;
  while (not Result) and (Rest <> '') do
  begin
    Split := Pos('\', Rest);
    if Split = 0 then
    begin
      Part := Rest;
      Rest := '';
    end else
    begin
      Part := Copy(Rest, 1, Split - 1);
      Rest := Copy(Rest, Split + 1, Length(Rest));
    end;
    Current := Current + '\' + Part;
    Result := IsReparsePoint(Current);
  end;
end;

procedure RemoveOwnAutocadBundle(const Bundle: String);
var
  Lines: TArrayOfString;
  I, Split: Integer;
  Digest, Relative, Path: String;
  Same: Boolean;
begin
  if BundlePathRedirected(Bundle, 'archhub-bundle.sha256') then
  begin
    Log('AutoCAD bundle is redirected; left unchanged ' + Bundle);
    exit;
  end;
  if not LoadStringsFromFile(Bundle + '\archhub-bundle.sha256', Lines) then
    exit;
  for I := 0 to GetArrayLength(Lines) - 1 do
  begin
    Split := Pos('  ', Lines[I]);
    if Split <> 65 then
      continue;
    Digest := Copy(Lines[I], 1, 64);
    Relative := Copy(Lines[I], 67, Length(Lines[I]));
    StringChangeEx(Relative, '/', '\', True);
    if (Relative = '') or (Pos('..', Relative) > 0) or (Pos(':', Relative) > 0) then
      continue;
    if BundlePathRedirected(Bundle, Relative) then
    begin
      Log('Skipped redirected AutoCAD bundle path ' + Relative);
      continue;
    end;
    Path := Bundle + '\' + Relative;
    Same := False;
    if FileExists(Path) then
    try
      Same := CompareText(GetSHA256OfFile(Path), Digest) = 0;
    except
      Log('Could not read AutoCAD bundle file ' + Path);
    end;
    if Same then
    begin
      if DeleteFile(Path) then
        Log('Removed ArchHub AutoCAD bundle file ' + Path)
      else
        Log('Could not remove ArchHub AutoCAD bundle file ' + Path);
      RemoveDir(ExtractFileDir(Path));
    end;
  end;
  DeleteFile(Bundle + '\archhub-bundle.sha256');
  if not IsReparsePoint(Bundle + '\Contents') then
    RemoveDir(Bundle + '\Contents');
  if RemoveDir(Bundle) then
    Log('Removed ArchHub AutoCAD bundle ' + Bundle);
end;