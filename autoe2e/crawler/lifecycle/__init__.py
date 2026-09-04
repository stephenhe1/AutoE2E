"""Lifecycle hook resolution and execution.

`lifecycle.on_visit` in a subject config was parsed by LifecycleConfig but read nowhere, so
it did nothing. This package makes it real. A spec entry is:

    [module, ClassName]            # no parameters
    [module, ClassName, {params}]  # with parameters

`module` may be a dotted import path, or the empty string / "autoe2e" for a built-in hook in
`autoe2e.crawler.lifecycle.hooks`. The two-element form is still accepted so existing configs
keep parsing.
"""
from __future__ import annotations

import importlib

from autoe2e.utils import logger
from autoe2e.crawler.lifecycle.hooks import ClientState, FormLogin, Hook

_BUILTINS = {
    'FormLogin': FormLogin,
    'ClientState': ClientState,
}


def resolve_hook(spec):
    """Turn one config entry into (instance, label). Raises on a bad spec."""
    if not isinstance(spec, (list, tuple)) or len(spec) < 2:
        raise RuntimeError(f"lifecycle: malformed hook spec {spec!r}")

    module, name = spec[0], spec[1]
    params = spec[2] if len(spec) > 2 else {}
    if not isinstance(params, dict):
        raise RuntimeError(f"lifecycle: params for {name} must be an object, got {type(params).__name__}")

    if not module or module == 'autoe2e':
        if name not in _BUILTINS:
            raise RuntimeError(
                f"lifecycle: unknown built-in hook {name!r}; known: {sorted(_BUILTINS)}"
            )
        cls = _BUILTINS[name]
    else:
        cls = getattr(importlib.import_module(module), name)

    return cls(**params), f"{module or 'autoe2e'}.{name}"


def run_hooks(specs, crawl_context, phase: str = 'on_visit') -> None:
    """Run every hook in order. A hook that raises aborts the crawl, by design."""
    if not specs:
        return
    logger.info(f"lifecycle[{phase}]: {len(specs)} hook(s) to run")
    for spec in specs:
        hook, label = resolve_hook(spec)
        logger.info(f"lifecycle[{phase}]: running {label}")
        hook.run(crawl_context)
        logger.info(f"lifecycle[{phase}]: {label} done")


__all__ = ['Hook', 'FormLogin', 'ClientState', 'resolve_hook', 'run_hooks']
