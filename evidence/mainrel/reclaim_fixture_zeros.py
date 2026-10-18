"""Reclaim only verified zero extents in completed MAINREL fixture journals.

No deletion/truncation. Each reclaimed range is read and verified all-zero
before and after FSCTL_SET_ZERO_DATA; byte length and protected prefix remain.
Microsoft: https://learn.microsoft.com/windows/win32/api/winioctl/ni-winioctl-fsctl_set_zero_data
"""
import ctypes
import hashlib
import json
import msvcrt
from pathlib import Path
import shutil

root = Path(__file__).resolve().parent
allowed = (root / 'court-state/test-profile', root / 'court-state/round3')
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
returned = ctypes.c_ulong()
class ZeroRange(ctypes.Structure):
    _fields_ = [('start',ctypes.c_longlong),('end',ctypes.c_longlong)]
records = []
for parent in allowed:
    if not parent.exists():
        continue
    for path in parent.rglob('archhub-test.universal.sqlite3'):
        if path.is_symlink() or path.is_junction() or path.stat().st_size < 8 * 1024**3:
            continue
        if not path.resolve().is_relative_to(parent.resolve()) or not any(
                name.startswith(('test_three_installs_replace_', 'test_incomplete_owned_stage_')) for name in path.parts):
            raise ValueError('fixture extent reclamation escaped completed test cases')
        free_before = shutil.disk_usage(root).free
        size = path.stat().st_size
        reclaimed = 0
        with path.open('r+b', buffering=0) as stream:
            protected = hashlib.sha256(stream.read(1024 * 1024)).hexdigest()
            handle = ctypes.c_void_p(msvcrt.get_osfhandle(stream.fileno()))
            if not kernel.DeviceIoControl(handle, 0x900C4, None, 0, None, 0, ctypes.byref(returned), None):
                raise ctypes.WinError(ctypes.get_last_error())
            offset = 1024 * 1024
            while offset < size:
                stream.seek(offset)
                chunk = stream.read(min(16 * 1024**2, size-offset))
                if not chunk:
                    raise ValueError('completed fixture size changed')
                if chunk.count(0) == len(chunk):
                    bounds = ZeroRange(offset,offset+len(chunk))
                    if not kernel.DeviceIoControl(handle,0x980C8,ctypes.byref(bounds),ctypes.sizeof(bounds),None,0,ctypes.byref(returned),None):
                        raise ctypes.WinError(ctypes.get_last_error())
                    stream.seek(offset)
                    if stream.read(len(chunk)) != chunk:
                        raise ValueError('zero-extent readback differs')
                    reclaimed += len(chunk)
                offset += len(chunk)
            stream.seek(0)
            if hashlib.sha256(stream.read(1024*1024)).hexdigest() != protected or path.stat().st_size != size:
                raise ValueError('fixture prefix/length changed')
        row = dict(file=str(path),bytes=size,verified_zero_bytes=reclaimed,
                   free_before=free_before,free_after=shutil.disk_usage(root).free)
        records.append(row)
        print(json.dumps(row),flush=True)
(root / 'round3-zero-extent-reclamation.json').write_text(json.dumps(records,indent=2)+'\n')
