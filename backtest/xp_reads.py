"""Two guards against a predictor reading data round `load_as_of` (brief section 7, leakage).

* **The read guard** (`forbid_reads`): while a perturbation run calls a predictor, any file
  open, directory listing or process start under the real data folders fails and is recorded.
  The perturbation's scratch copy is reached only by `load_as_of` calls that name no `cfg` or
  `root`; a predictor that read the real checkout directly, or gave the loader its own config,
  would see uncorrupted later data and pass. With the guard it fails instead, even if it
  catches the error, because the hits are recorded. It is a process-wide audit hook
  (`sys.addaudithook`), installed on the first block (a hook can't be removed, and it costs
  about 8% on a loader read). While a block is active it guards every thread, so a read moved
  to a new thread is caught too (the harness itself is single-threaded). Paths are compared
  after `os.path.realpath`, so a junction or link to the real data is caught. C-level readers
  that bypass Python's `open` (pyarrow's Parquet reader) aren't seen, which is one reason for
  the static check.
* **The static check** (`static_findings`): the model's source files, and the `fpl` modules they
  import (except the trusted loader and config modules), must not name a reader that bypasses
  the loader, give `load_as_of` its own `cfg` or `root`, import it under another name, or
  import anything from `backtest` (the snapshot-timing audit reads git history, and no
  predictor may import it: data contract, "Point-in-time loader").
"""

from __future__ import annotations

import ast
import importlib.util
import os
import sys
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

PATH_EVENTS = {"open", "os.listdir", "os.scandir", "glob.glob"}
PROCESS_EVENTS = {"subprocess.Popen", "os.system", "os.exec", "os.spawn", "os.startfile"}
LOADER = "load_as_of"

# The active guard, process-wide: (forbidden roots, hits), or None outside a block.
_GUARD: list[tuple[tuple[str, ...], list[str]] | None] = [None]
# Set while the hook itself resolves a path, so the resolving can't recurse into the hook.
_RESOLVING = threading.local()


class ReadOutsideCopyError(RuntimeError):
    """A predictor read the real data, not the perturbation's scratch copy."""


def _norm(path: object) -> str:
    """The path with links and junctions resolved, in a case-normalised form."""
    return os.path.normcase(os.path.realpath(os.fsdecode(path)))


def _audit(event: str, args: tuple) -> None:
    """The audit hook. Outside a `forbid_reads` block it does nothing. Inside one, it records
    and refuses (by raising `ReadOutsideCopyError` in the caller) every process start, and
    every open, listing or glob whose path resolves under a forbidden root."""
    guard = _GUARD[0]
    if guard is None or getattr(_RESOLVING, "on", False):
        return
    roots, hits = guard
    if event in PROCESS_EVENTS:
        hits.append(f"{event} {args[0] if args else ''}".strip())
        raise ReadOutsideCopyError(f"a predictor started a process ({event})")
    if event not in PATH_EVENTS or not args or not isinstance(args[0], str | bytes | os.PathLike):
        return
    _RESOLVING.on = True
    try:
        path = _norm(args[0])
    finally:
        _RESOLVING.on = False
    if any(path == r or path.startswith(r + os.sep) for r in roots):
        hits.append(path)
        raise ReadOutsideCopyError(f"read outside the scratch copy: {path}")


_INSTALLED: list[bool] = []


@contextmanager
def forbid_reads(roots: Sequence[Path]) -> Iterator[list[str]]:
    """Inside the block, fail and record (in the yielded list) every open or listing under
    `roots` and every process started, in any thread. Blocks nest; the innermost applies."""
    if not _INSTALLED:
        sys.addaudithook(_audit)
        _INSTALLED.append(True)
    hits: list[str] = []
    previous = _GUARD[0]
    _GUARD[0] = (tuple(_norm(r) for r in roots), hits)
    try:
        yield hits
    finally:
        _GUARD[0] = previous


def _within(name: str, prefixes: Sequence[str]) -> bool:
    return any(name == p or name.startswith(p + ".") for p in prefixes)


def _package(path: Path) -> str:
    """The dotted package a source file sits in, from the `__init__.py` files above it."""
    parts, folder = [], path.parent
    while (folder / "__init__.py").exists():
        parts.insert(0, folder.name)
        folder = folder.parent
    return ".".join(parts)


def _imports(tree: ast.AST, path: Path) -> list[str]:
    """The modules (and module attributes) a file imports, relative imports resolved
    against its package."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = importlib.util.resolve_name("." * node.level + base, _package(path))
            if base:
                out += [base, *(f"{base}.{a.name}" for a in node.names)]
    return out


def _names(node: ast.AST) -> list[str]:
    """The module, imported, attribute or variable names a node mentions."""
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module or "", *(a.name for a in node.names)]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.Name):
        return [node.id]
    return []


def _aliases(tree: ast.AST) -> dict[str, int]:
    """Names the loader is imported under other than its own, with their lines."""
    return {a.asname: node.lineno for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
            for a in node.names if a.name == LOADER and a.asname not in (None, LOADER)}


def _called(node: ast.Call) -> str | None:
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def _file_findings(tree: ast.AST, forbidden: set[str]) -> set[tuple[int, str]]:
    """(line, finding) for every forbidden name, backtest import, aliased loader and loader
    call given its own `cfg` or `root`."""
    aliases = _aliases(tree)
    hits = {(line, f"{LOADER} imported as {a}") for a, line in aliases.items()}
    loaders = {LOADER, *aliases}
    for node in ast.walk(tree):
        hits |= {(node.lineno, n) for n in _names(node) if n in forbidden
                 or _within(n, ["backtest"])}
        if isinstance(node, ast.Call) and _called(node) in loaders:
            hits |= {(node.lineno, f"{LOADER}({k.arg}=)") for k in node.keywords
                     if k.arg in ("cfg", "root")}
    return hits


def _origin(module: str) -> Path | None:
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError):
        return None
    return Path(spec.origin) if spec and spec.origin and spec.origin.endswith(".py") else None


def static_findings(paths: Sequence[Path], forbidden: Sequence[str], follow: Sequence[str],
                    trusted: Sequence[str]) -> tuple[list[str], list[Path]]:
    """`file:line: finding` over `paths` and every module they import (transitively) whose
    name is within `follow` and not within `trusted`; and the files scanned."""
    queue, seen, hits = [Path(p) for p in paths], set(), set()
    while queue:
        path = queue.pop(0).resolve()
        if path in seen:
            continue
        seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        hits |= {(path.name, line, f) for line, f in _file_findings(tree, set(forbidden))}
        for name in _imports(tree, path):
            if _within(name, follow) and not _within(name, trusted) and (o := _origin(name)):
                queue.append(o)
    return [f"{f}:{line}: {n}" for f, line, n in sorted(hits)], sorted(seen)
