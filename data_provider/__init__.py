# -*- coding: utf-8 -*-
"""Provider package namespace with lazy compatibility exports.

Importing a provider submodule must not eagerly import every optional provider
and its third-party dependencies. Legacy package-root imports remain available
through PEP 562 lazy attribute resolution.
"""

from __future__ import annotations

from importlib import import_module

_LAZY_EXPORTS = {
    "BaseFetcher": (".base", "BaseFetcher"),
    "DataFetcherManager": (".base", "DataFetcherManager"),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
