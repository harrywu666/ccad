from __future__ import annotations

import asyncio
import gc
import inspect
import sys
import warnings

import pytest


if getattr(asyncio, "iscoroutinefunction", None) is not inspect.iscoroutinefunction:
    asyncio.iscoroutinefunction = inspect.iscoroutinefunction


warnings.filterwarnings(
    "ignore",
    message=r"builtin type SwigPyPacked has no __module__ attribute",
    category=DeprecationWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"builtin type SwigPyObject has no __module__ attribute",
    category=DeprecationWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"builtin type swigvarlink has no __module__ attribute",
    category=DeprecationWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r".*deprecated - use .*",
    category=DeprecationWarning,
    module=r"ezdxf\.queryparser",
)
warnings.filterwarnings(
    "ignore",
    message=r".*iscoroutinefunction.*inspect\.iscoroutinefunction.*",
    category=DeprecationWarning,
)


@pytest.fixture(autouse=True)
def _dispose_sqlite_engines_between_tests():
    yield

    database_module = sys.modules.get("database")
    if database_module is not None:
        dispose_db_engine = getattr(database_module, "dispose_db_engine", None)
        if callable(dispose_db_engine):
            try:
                dispose_db_engine()
            except Exception:
                pass

    gc.collect()
