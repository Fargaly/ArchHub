"""Run targeted courts with every user-state path confined to synthetic fixtures."""
import os
from pathlib import Path
import sys
import pytest

root = Path(__file__).resolve().parents[1]
fixture = root / 'evidence/agentlink2/court-state-environment'
fixture.mkdir(parents=True, exist_ok=True)
for key in ('LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP', 'HOME', 'USERPROFILE'):
    os.environ[key] = str(fixture)
sys.path.insert(0, str(root))
if __name__ == '__main__':
    raise SystemExit(pytest.main(sys.argv[1:]))
