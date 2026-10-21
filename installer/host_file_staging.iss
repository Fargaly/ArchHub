// Host broker files a running host has loaded (Revit, AutoCAD, 3ds Max, ...).
//
// A loaded DLL cannot be overwritten or deleted, so replacing it aborted the
// whole install (release 8890e2b, Revit 2027 open). restartreplace needs admin
// rights and this setup runs as the user, so it cannot help. Windows does let a
// loaded file be MOVED within its volume: before [Files] copies, every file
// under {app}\bridges\ that is locked is moved to {app}\.retired-host-files\<tag>\
// with its relative path kept. The running host keeps its old image; the new
// file lands at the same path and the host loads it on its next start. Nothing
// is closed or restarted, no registration changes, and bridges\ holds exactly
// the shipped files, so the reviewed tree digest is unchanged.
// If setup does not finish, each moved file goes back where its path is empty.

var
  HostRetiredFrom: TStringList;
  HostRetiredTo: TStringList;
  HostInstallFinished: Boolean;

function HostFileLocked(const Path: String): Boolean;
var
  Stream: TFileStream;
begin
  Result := False;
  try
    Stream := TFileStream.Create(Path, fmOpenReadWrite or fmShareExclusive);
    Stream.Free;
  except
    Result := True;
  end;
end;

procedure RetireLockedHostFilesIn(const Dir, Relative, RetireRoot: String);
var
  Found: TFindRec;
  Source, Target: String;
begin
  if not FindFirst(AddBackslash(Dir) + '*', Found) then
    exit;
  try
    repeat
      if (Found.Name <> '.') and (Found.Name <> '..') then
      begin
        Source := AddBackslash(Dir) + Found.Name;
        if (Found.Attributes and $400) <> 0 then
          { A redirected entry is never followed or moved. }
        else if (Found.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
          RetireLockedHostFilesIn(Source, Relative + Found.Name + '\', RetireRoot)
        else if HostFileLocked(Source) then
        begin
          Target := RetireRoot + '\' + Relative + Found.Name;
          if not ForceDirectories(ExtractFileDir(Target)) then
            RaiseException('A host file in use could not be set aside: ' + Relative + Found.Name);
          if not RenameFile(Source, Target) then
            RaiseException('A host file in use could not be set aside: ' + Relative + Found.Name +
                           '. Close that host application, then run setup again.');
          HostRetiredFrom.Add(Source);
          HostRetiredTo.Add(Target);
          Log('Host file in use set aside: ' + Source + ' -> ' + Target);
        end;
      end;
    until not FindNext(Found);
  finally
    FindClose(Found);
  end;
end;

procedure RetireLockedHostFiles(const App, Tag: String);
var
  Root: String;
begin
  HostRetiredFrom := TStringList.Create;
  HostRetiredTo := TStringList.Create;
  HostInstallFinished := False;
  Root := AddBackslash(App) + '.retired-host-files';
  { Earlier set-aside copies go once their host has let go; locked ones stay. }
  if DirExists(Root) then
    DelTree(Root, True, True, True);
  if DirExists(AddBackslash(App) + 'bridges') then
    RetireLockedHostFilesIn(AddBackslash(App) + 'bridges', '',
                            Root + '\' + Tag + '-' + GetDateTimeString('yyyymmddhhnnss', #0, #0));
end;

procedure HostFilesInstalled();
begin
  HostInstallFinished := True;
end;

procedure RestoreRetiredHostFiles();
var
  I: Integer;
begin
  if (HostRetiredFrom = nil) or HostInstallFinished then
    exit;
  for I := HostRetiredFrom.Count - 1 downto 0 do
    if (not FileExists(HostRetiredFrom[I])) and FileExists(HostRetiredTo[I]) then
      if RenameFile(HostRetiredTo[I], HostRetiredFrom[I]) then
        Log('Host file restored after an unfinished setup: ' + HostRetiredFrom[I]);
end;