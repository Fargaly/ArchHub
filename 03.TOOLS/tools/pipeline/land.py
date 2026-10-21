"""Land admission uses the same compiler contract as release builds.

Pass ``--base REF`` for a lane or ``--commit HEAD`` for an exact landed commit;
an optional command after ``--`` runs only after the gate passes.
"""
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.pipeline.build import main


if __name__ == "__main__":
    sys.exit(main())
