"""Makes the four module directories importable so `pytest` works from the
repository root, without every test file needing its own sys.path prelude.

Without this, `pytest` collected from the root fails on `import detector`
-- the modules live in sibling directories rather than an installed
package, and pytest only puts each test file's own directory on the path.
(`python -m pytest` happens to work from inside a module directory because
that adds the working directory, but that is a subtle difference to hand a
reviewer as a run instruction.)
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

for _module_dir in ("pii-detector", "masking-generator", "rag", "agent"):
    _path = str(_ROOT / _module_dir)
    if _path not in sys.path:
        sys.path.insert(0, _path)

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
