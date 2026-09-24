(* One guarded sweep of the v1.x code an upgrade inherits.

  The v1 installer (same AppId, same folder) copied its application into
  {app}\app, {app}\payload and {app}\installer. This build ships none of it
  except app\__init__.py, app\secrets_store.py and app\credential_lock.py.

  ALLOWLIST ONLY: the sweep deletes a file only when its path relative to the
  install folder is one the v1 installer shipped (legacy_v1_files.iss). Any
  other file -- .env, cloud.json, logs, tokens, databases, anything a person
  or a later build put there -- is kept, and so is app\assets (v1 shortcuts
  still take their icon from it). A directory is removed only when it is
  empty afterwards.

  Guards, every one required:
  * {app}\app\main.py exists (v1's entry point; this build never ships it).
  * A v1 INSTALL marker: {app}\VERSION reads 1.x, or the ArchHub uninstall
    entry still reports DisplayVersion 1.x. A source checkout has neither.
  * The folder is named ArchHub, is not ArchHub-Test (the person's graph),
    and holds no .git: a checkout is never swept, and no file is deleted from
    under a directory that holds .git or through a link.
  * payload\ files stay while any Revit add-in manifest, per user
    (%APPDATA%) or for all users (%ProgramData%), still loads from payload\. *)

#include "legacy_v1_files.iss"

const
  LegacyReparsePoint = $400;
  LegacyUninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{B6C0E10F-1F8E-4AAB-9A8F-4F2E3A2C4BAE}_is1';

function LegacyEndsWith(const Text, Suffix: String): Boolean;
begin
  Result := (Length(Text) >= Length(Suffix)) and
    (CompareText(Copy(Text, Length(Text) - Length(Suffix) + 1, Length(Suffix)), Suffix) = 0);
end;

function LegacyIsV1Version(const Value: String): Boolean;
begin
  Result := Copy(Trim(Value), 1, 2) = '1.';
end;

{ The uninstall entry counts only when it was registered for THIS folder. }
function LegacyHasV1InstallMarker(const Root: String): Boolean;
var
  Version: AnsiString;
  Registered, Location: String;
begin
  Result := (LoadStringFromFile(Root + '\VERSION', Version) and LegacyIsV1Version(String(Version))) or
    (RegQueryStringValue(HKCU, LegacyUninstallKey, 'DisplayVersion', Registered) and
     LegacyIsV1Version(Registered) and
     RegQueryStringValue(HKCU, LegacyUninstallKey, 'InstallLocation', Location) and
     (CompareText(RemoveBackslashUnlessRoot(Trim(Location)), RemoveBackslashUnlessRoot(Root)) = 0));
end;

{ A manifest path in one comparable form: lower case, backslashes, and the
  %APPDATA% / %LOCALAPPDATA% / %PROGRAMDATA% / %USERPROFILE% forms expanded. }
function LegacyNormalPath(const Value: String): String;
begin
  Result := Value;
  StringChangeEx(Result, '/', '\', True);
  StringChangeEx(Result, '%APPDATA%', GetEnv('APPDATA'), True);
  StringChangeEx(Result, '%appdata%', GetEnv('APPDATA'), True);
  StringChangeEx(Result, '%LOCALAPPDATA%', GetEnv('LOCALAPPDATA'), True);
  StringChangeEx(Result, '%localappdata%', GetEnv('LOCALAPPDATA'), True);
  StringChangeEx(Result, '%PROGRAMDATA%', GetEnv('ProgramData'), True);
  StringChangeEx(Result, '%ProgramData%', GetEnv('ProgramData'), True);
  StringChangeEx(Result, '%programdata%', GetEnv('ProgramData'), True);
  StringChangeEx(Result, '%USERPROFILE%', GetEnv('USERPROFILE'), True);
  StringChangeEx(Result, '%userprofile%', GetEnv('USERPROFILE'), True);
  StringChangeEx(Result, '\\', '\', True);
  Result := Lowercase(Result);
end;

function LegacyHoldsGit(const Dir: String): Boolean;
begin
  Result := DirExists(Dir + '\.git') or FileExists(Dir + '\.git');
end;

{ True when Dir exists as a plain directory: no link, no .git inside it. }
function LegacyPlainDir(const Dir: String): Boolean;
var
  Rec: TFindRec;
begin
  Result := False;
  if FindFirst(Dir, Rec) then
  begin
    try
      Result := ((Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) and
                ((Rec.Attributes and LegacyReparsePoint) = 0);
    finally
      FindClose(Rec);
    end;
  end;
  Result := Result and not LegacyHoldsGit(Dir);
end;

{ Every directory from Root down to the file is plain, and the file is a plain file. }
function LegacyPlainPath(const Root, Rel: String): Boolean;
var
  Rest, Dir: String;
  Cut: Integer;
  Rec: TFindRec;
begin
  Result := False;
  Dir := Root;
  Rest := Rel;
  Cut := Pos('\', Rest);
  while Cut > 0 do
  begin
    Dir := Dir + '\' + Copy(Rest, 1, Cut - 1);
    Rest := Copy(Rest, Cut + 1, Length(Rest));
    if not LegacyPlainDir(Dir) then
      exit;
    Cut := Pos('\', Rest);
  end;
  if FindFirst(Root + '\' + Rel, Rec) then
  begin
    try
      Result := ((Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0) and
                ((Rec.Attributes and LegacyReparsePoint) = 0);
    finally
      FindClose(Rec);
    end;
  end;
end;

function LegacyManifestsIn(const Base, Target: String): Boolean;
var
  Years, Manifests: TFindRec;
  Text: AnsiString;
begin
  Result := False;
  if FindFirst(Base + '\*', Years) then
  begin
    try
      repeat
        if ((Years.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) and
           (Years.Name <> '.') and (Years.Name <> '..') and
           FindFirst(Base + '\' + Years.Name + '\*.addin', Manifests) then
        begin
          try
            repeat
              if LoadStringFromFile(Base + '\' + Years.Name + '\' + Manifests.Name, Text) and
                 (Pos(LegacyNormalPath(Target), LegacyNormalPath(String(Text))) > 0) then
                Result := True;
            until Result or not FindNext(Manifests);
          finally
            FindClose(Manifests);
          end;
        end;
      until Result or not FindNext(Years);
    finally
      FindClose(Years);
    end;
  end;
end;

{ True when a Revit add-in manifest, per user or for all users, names Target. }
function LegacyAddinsReference(const Target: String): Boolean;
begin
  Result := LegacyManifestsIn(ExpandConstant('{userappdata}') + '\Autodesk\Revit\Addins', Target) or
            LegacyManifestsIn(ExpandConstant('{commonappdata}') + '\Autodesk\Revit\Addins', Target);
end;

procedure SweepLegacyV1(const Root: String);
var
  Files, Dirs: TStringList;
  I, Cut, Removed: Integer;
  Rel, Dir: String;
  KeepPayload: Boolean;
begin
  if not FileExists(Root + '\app\main.py') then
    exit;
  if not LegacyPlainDir(Root) then
  begin
    Log('Legacy sweep refused: ' + Root + ' is a link, a junction or a source checkout');
    exit;
  end;
  if (not LegacyEndsWith(Root, '\ArchHub')) or (Pos('archhub-test', Lowercase(Root)) > 0) then
  begin
    Log('Legacy sweep refused: unexpected install root ' + Root);
    exit;
  end;
  if not LegacyHasV1InstallMarker(Root) then
  begin
    Log('Legacy sweep refused: no v1 install marker (VERSION 1.x or uninstall entry 1.x) at ' + Root);
    exit;
  end;
  if LegacyHoldsGit(Root) or LegacyHoldsGit(Root + '\app') then
  begin
    Log('Legacy sweep refused: ' + Root + ' is a source checkout (.git present)');
    exit;
  end;
  KeepPayload := LegacyAddinsReference(Root + '\payload');
  if KeepPayload then
    Log('Legacy sweep keeps payload\: a Revit add-in still loads from it.');
  Files := TStringList.Create;
  Dirs := TStringList.Create;
  try
    LegacyV1AddFiles(Files);
    Removed := 0;
    for I := 0 to Files.Count - 1 do
    begin
      Rel := Files[I];
      if KeepPayload and (CompareText(Copy(Rel, 1, 8), 'payload\') = 0) then
        continue;
      if not LegacyPlainPath(Root, Rel) then
        continue;
      if DeleteFile(Root + '\' + Rel) then
      begin
        Removed := Removed + 1;
        Dir := Rel;
        Cut := Length(Dir);
        while Cut > 0 do
        begin
          if Dir[Cut] = '\' then
          begin
            Dir := Copy(Dir, 1, Cut - 1);
            if Dirs.IndexOf(Dir) < 0 then
              Dirs.Add(Dir);
          end;
          Cut := Cut - 1;
        end;
      end
      else
        Log('Legacy sweep could not remove ' + Root + '\' + Rel);
    end;
    { Deepest first; RemoveDir only removes a directory that is now empty. }
    Dirs.Sort;
    for I := Dirs.Count - 1 downto 0 do
      RemoveDir(Root + '\' + Dirs[I]);
    Log('Legacy sweep removed ' + IntToStr(Removed) + ' v1 file(s) under ' + Root);
  finally
    Files.Free;
    Dirs.Free;
  end;
end;
