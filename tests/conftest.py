"""Make custom_components.cgesp submodules importable without a Home Assistant install.

The package's own __init__.py (and other platform modules) import real
`homeassistant` symbols at module load time, which isn't available in a plain
test environment. We register lightweight stub packages for
`custom_components` and `custom_components.cgesp` so submodules such as
`cge_scrape`, `cge_data` and `cge_data_forecast` — which only need
`homeassistant` for type hints guarded by `TYPE_CHECKING` — can be imported
and unit tested directly.
"""
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
COMPONENT_DIR = REPO_ROOT / "custom_components" / "cgesp"


def _register_stub_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


_register_stub_package("custom_components", REPO_ROOT / "custom_components")
_register_stub_package("custom_components.cgesp", COMPONENT_DIR)
