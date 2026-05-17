import json
import os
from pathlib import Path

SCENARIOS_DIR = Path(__file__).parent / "scenarios"


def _ensure_dir():
    SCENARIOS_DIR.mkdir(exist_ok=True)


def list_scenarios() -> list[str]:
    _ensure_dir()
    return sorted(p.stem for p in SCENARIOS_DIR.glob("*.json"))


def save_scenario(name: str, profile: dict, assumptions: dict, accounts: list[dict], roth_conversion: dict | None = None) -> None:
    _ensure_dir()
    safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip()
    if not safe_name:
        raise ValueError("Scenario name cannot be empty.")
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
