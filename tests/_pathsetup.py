"""Adds this project's script directories to sys.path so test modules can
import from geometry/, batch/, elmer/ the same way those scripts import
from each other (they're run as standalone scripts, not an installed
package -- see docs/reference.md). Import this before any project import,
e.g.:

    import _pathsetup  # noqa: F401
    from analyze_plane_crossings import _crossed
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("geometry", "batch", "elmer"):
    _path = os.path.join(_REPO_ROOT, _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)
