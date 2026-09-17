"""Operation-local evidence reuse; never persist or trust metadata instead of SHA256."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
import hashlib
import json
from pathlib import Path


_active = ContextVar("evidence_read_operation", default=None)


def raw_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha(path):
    session = _active.get()
    if session is None:
        return raw_sha(path)
    key = str(Path(path).resolve())
    if key not in session["hashes"]:
        session["hashes"][key] = raw_sha(key)
    return session["hashes"][key]


def read_json(path):
    session = _active.get()
    if session is None:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    key = str(Path(path).resolve())
    if key not in session["json"]:
        payload = Path(key).read_bytes()
        fingerprint = hashlib.sha256(payload).hexdigest()
        if key in session["hashes"] and session["hashes"][key] != fingerprint:
            raise ValueError(f"Evidence changed during operation; rerun with current files: {key}")
        # Hash the exact bytes being parsed, not a separate preceding file read.
        session["hashes"][key] = fingerprint
        session["json"][key] = json.loads(payload.decode("utf-8-sig"))
    return deepcopy(session["json"][key])


@contextmanager
def evidence_operation():
    """Share reads inside one operation, rehash every dependency before returning.

    A changed/deleted dependency aborts the operation even if size and timestamps
    were restored. No cache survives success or failure. Do not enclose writes to
    source files or project saves; complete this scope before committing state.
    """
    if _active.get() is not None:
        yield
        return
    session = {"hashes": {}, "json": {}, "values": {}}
    token = _active.set(session)
    try:
        yield
        for path, expected in session["hashes"].items():
            if raw_sha(path) != expected:
                raise ValueError(f"Evidence changed during operation; rerun with current files: {path}")
    finally:
        _active.reset(token)


def verified_read(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with evidence_operation():
            return fn(*args, **kwargs)
    return wrapped


def memo_read(fn):
    """Memoize read-only calculations by complete inputs, only inside a scope.

    Deep copies prevent callers from altering cached values; complete inputs
    ensure in-memory script, review or selection changes cannot reuse old results.
    Files read on a cache miss are all rehashed by the owning operation on exit.
    """
    @wraps(fn)
    def wrapped(*args, **kwargs):
        session = _active.get()
        if session is None:
            return fn(*args, **kwargs)
        encoded = json.dumps([args, kwargs], sort_keys=True, ensure_ascii=False,
                             default=lambda value: str(value) if isinstance(value, Path) else _unsupported(value))
        key = (fn.__module__, fn.__qualname__, hashlib.sha256(encoded.encode()).hexdigest())
        if key not in session["values"]:
            session["values"][key] = deepcopy(fn(*args, **kwargs))
        return deepcopy(session["values"][key])
    return wrapped


def _unsupported(value):
    raise TypeError(f"Unsupported evidence cache input: {type(value).__name__}")
