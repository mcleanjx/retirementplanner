import json
from pathlib import Path

SCENARIOS_DIR = Path(__file__).parent / "scenarios"
TRACKING_DIR = SCENARIOS_DIR / "tracking"


def _ensure_dir():
    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    TRACKING_DIR.mkdir(parents=True, exist_ok=True)


def list_scenarios() -> list[str]:
    _ensure_dir()
    return sorted(p.stem for p in SCENARIOS_DIR.glob("*.json"))


def latest_scenario() -> str | None:
    """Return the stem of the most recently modified scenario file, or None."""
    _ensure_dir()
    files = list(SCENARIOS_DIR.glob("*.json"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime).stem


_LAST_USED_FILE = SCENARIOS_DIR / ".last_used"


def get_last_used_scenario() -> str | None:
    """Return the name of the last explicitly used scenario, falling back to latest by mtime."""
    _ensure_dir()
    if _LAST_USED_FILE.exists():
        name = _LAST_USED_FILE.read_text(encoding="utf-8").strip()
        if name and (SCENARIOS_DIR / f"{name}.json").exists():
            return name
    return latest_scenario()


def set_last_used_scenario(name: str) -> None:
    """Persist the last-used scenario name so it survives page refreshes."""
    _ensure_dir()
    _LAST_USED_FILE.write_text(name, encoding="utf-8")


_VALID_NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-")


def validate_scenario_name(name: str) -> None:
    """Raise ValueError if name contains characters not allowed in scenario names."""
    if not name or not name.strip():
        raise ValueError("Scenario name cannot be empty.")
    bad = sorted(set(c for c in name if c not in _VALID_NAME_CHARS))
    if bad:
        raise ValueError(
            f"Scenario name contains invalid characters: {' '.join(repr(c) for c in bad)}. "
            "Use only letters, numbers, spaces, hyphens, and underscores."
        )


def save_scenario(name: str, profile: dict, assumptions: dict, accounts: list[dict], roth_conversion: dict | None = None) -> None:
    _ensure_dir()
    validate_scenario_name(name)
    safe_name = name.strip()
    path = SCENARIOS_DIR / f"{safe_name}.json"
    payload = {
        "scenario_name": name,
        "profile": profile,
        "assumptions": assumptions,
        "accounts": accounts,
        "roth_conversion": roth_conversion or {},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_scenario(name: str) -> dict:
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip()
    path = SCENARIOS_DIR / f"{safe}.json"
    if not path.exists():
        path = SCENARIOS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Scenario '{name}' not found.")
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"profile", "assumptions", "accounts"}
    if not required.issubset(data.keys()):
        raise ValueError(f"Scenario file is missing required keys: {required - data.keys()}")
    return data


def delete_scenario(name: str) -> None:
    path = SCENARIOS_DIR / f"{name}.json"
    if path.exists():
        path.unlink()


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip()


def load_tracking(name: str) -> dict:
    _ensure_dir()
    path = TRACKING_DIR / f"{_safe_name(name)}_tracking.json"
    if not path.exists():
        # Migrate old tracking file from scenarios/ if it exists there
        old_path = SCENARIOS_DIR / f"{_safe_name(name)}_tracking.json"
        if old_path.exists():
            data = json.loads(old_path.read_text(encoding="utf-8"))
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            old_path.unlink()
            return data
        return {"baseline": None, "checkins": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_tracking(name: str, tracking: dict) -> None:
    _ensure_dir()
    path = TRACKING_DIR / f"{_safe_name(name)}_tracking.json"
    path.write_text(json.dumps(tracking, indent=2), encoding="utf-8")
