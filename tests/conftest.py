"""Make the test suite independent of the working directory it is invoked from.

Without this, `pytest` run from anywhere but the repository root fails at COLLECTION with

    ModuleNotFoundError: No module named 'autoe2e'

because the repo root is not on sys.path -- and that error reads exactly like a missing
third-party dependency, which sends you looking for an uninstalled package instead of a path
problem. The tests also read files under `configs/`, which must resolve against the repository,
not the caller's cwd.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Prepend, so a checkout is always preferred over an installed copy of the same package.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope='session')
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope='session')
def configs_dir(repo_root) -> Path:
    return repo_root / 'configs'
