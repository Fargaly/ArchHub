"""Land admission uses the same compiler contract as release builds.

Pass ``--base REF`` for a lane or ``--commit HEAD`` for an exact landed commit;
an optional command after ``--`` runs only after the gate passes.
"""
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path[:0] = [str(Path(__file__).resolve().parents[3] / area) for area in ("01.APP", "02.TESTS", "03.TOOLS", "06.CLOUD")]

from tools.pipeline.build import main


if __name__ == "__main__":
    sys.exit(main())
