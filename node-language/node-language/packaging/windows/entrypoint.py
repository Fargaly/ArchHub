"""PyInstaller entry point for the supervised node-native ArchHub desktop."""
import sys

from nodelang.desktop import main as desktop_main
from nodelang.desktop_supervisor import supervise


if __name__ == "__main__":
    if "--desktop-worker" in sys.argv[1:]:
        raise SystemExit(desktop_main())
    raise SystemExit(supervise())
