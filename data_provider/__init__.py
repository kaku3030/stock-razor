# -*- coding: utf-8 -*-
"""Provider package namespace.

Keep package import intentionally lightweight. Runtime/provider modules must be
imported explicitly from their defining submodules. Importing this package must
not eagerly import optional A-share/US providers and their independent third-
party dependencies into isolated runtimes such as the read-only Futures worker.
"""

__all__: list[str] = []
