from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


def _load_root_module():
    root_init = Path(__file__).resolve().parents[1] / "__init__.py"
    spec = importlib.util.spec_from_file_location("viralforge", root_init)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PackageExportTests(unittest.TestCase):
    def test_root_package_exposes_version(self) -> None:
        module = _load_root_module()
        self.assertTrue(hasattr(module, "__version__"))
        self.assertEqual(module.__version__, "1.0.0")


if __name__ == "__main__":
    unittest.main()
