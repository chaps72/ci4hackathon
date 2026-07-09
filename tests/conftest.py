"""Make the repo root importable (send_digest, fedwatch.*) regardless of how
pytest is invoked."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
