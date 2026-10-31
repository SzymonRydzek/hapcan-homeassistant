"""Make the Home-Assistant-free modules importable without Home Assistant.

The package ``__init__`` imports Home Assistant, so a bare package object is
registered instead; ``hapcan.protocol``, ``hapcan.blind_model`` and
``hapcan.const`` then import normally.
"""

from pathlib import Path
import sys
import types

PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "hapcan"

pkg = types.ModuleType("hapcan")
pkg.__path__ = [str(PKG_DIR)]
sys.modules.setdefault("hapcan", pkg)
