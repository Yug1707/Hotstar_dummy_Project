import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # harness modules
sys.path.insert(0, str(HERE))  # fakes
os.environ.setdefault("HSL_STATE_DIR", str(HERE / ".state"))
