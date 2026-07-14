"""Shared pytest fixtures for the CMA valuation-engine unit tests.

These tests are deterministic, network-free, and DB-free: they exercise the
pure valuation math in ``scripts/build_cma.py`` and the comp-scoring helpers in
``mls_bot.analytics.cma_compset`` using only synthetic subject/comp dicts. No
parquet, no DuckDB, and no AVM model file are ever read.

``build_cma.py`` lives under ``scripts/`` (not an importable package), so it is
loaded from its file path via importlib. It MUST be registered in
``sys.modules`` before ``exec_module`` because the module defines dataclasses
with forward references, which the stdlib resolves through
``sys.modules[cls.__module__]``.

``cma_compset`` imports normally once ``src/`` is on ``sys.path`` (mirroring the
project's ``PYTHONPATH=src`` convention).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC = _PROJECT_ROOT / "src"
_BUILD_CMA = _PROJECT_ROOT / "scripts" / "build_cma.py"

# Ensure `from mls_bot.analytics import cma_compset` resolves (PYTHONPATH=src).
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _load_build_cma():
    """Load scripts/build_cma.py as an importable module object.

    Registers it in sys.modules under its spec name first so dataclass
    forward-reference resolution (which reads sys.modules) succeeds.
    """
    spec = importlib.util.spec_from_file_location("build_cma", _BUILD_CMA)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_cma"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def build_cma_mod():
    """The loaded ``scripts/build_cma.py`` module."""
    return _load_build_cma()


@pytest.fixture(scope="session")
def compset_mod():
    """The ``mls_bot.analytics.cma_compset`` module."""
    from mls_bot.analytics import cma_compset
    return cma_compset
