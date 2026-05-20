import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.parent.resolve()
STATE_FILE = SCRIPT_DIR / "logs" / "state.json"


def _load():
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text())


def _save(state):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def is_done(name):
    return _load().get(name) in ("done", "skipped")


def mark_done(name):
    state = _load()
    state[name] = "done"
    _save(state)


def mark_skipped(name):
    state = _load()
    state[name] = "skipped"
    _save(state)


def mark_failed(name):
    state = _load()
    state[name] = "failed"
    _save(state)


def reset(name):
    """Remove a single step so it re-runs next time."""
    state = _load()
    state.pop(name, None)
    _save(state)


def reset_all():
    """Wipe all state — forces a full re-run."""
    _save({})
