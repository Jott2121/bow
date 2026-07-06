"""Each pattern directory is self-contained; make its module importable from its tests."""
import sys
from pathlib import Path

for d in Path(__file__).parent.iterdir():
    if d.is_dir():
        sys.path.insert(0, str(d))
