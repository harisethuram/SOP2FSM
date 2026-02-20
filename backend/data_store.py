"""File-based storage: check_ids.yaml, embeddings.pt, user SOPs."""
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
import yaml

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CHECK_IDS_PATH = DATA_DIR / "check_ids.yaml"


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_check_ids():
    """Load canonical checks from data/check_ids.yaml. Return list of dicts."""
    if not CHECK_IDS_PATH.exists():
        return []
    with open(CHECK_IDS_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if data is not None else []


def save_check_ids(checks: list):
    _ensure_data_dir()
    with open(CHECK_IDS_PATH, "w", encoding="utf-8") as f:
        yaml.dump(checks, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def get_check_by_id(check_id: str):
    checks = load_check_ids()
    for c in checks:
        if c.get("check_id") == check_id:
            return c
    return None


def get_checks_by_indices(indices: list):
    """Return list of check dicts for given row indices (0-based)."""
    checks = load_check_ids()
    return [checks[i] for i in indices if 0 <= i < len(checks)]


def append_canonical_check(check_id: str, check_text: str):
    """Append one canonical check and return it."""
    checks = load_check_ids()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {
        "check_id": check_id,
        "check_text": check_text,
        "created_at": now,
    }
    checks.append(entry)
    save_check_ids(checks)
    return entry


def sop_dir_for_user(username: str) -> Path:
    return DATA_DIR / username / "sops"


def sop_path(username: str, sop_id: str) -> Path:
    return sop_dir_for_user(username) / f"{sop_id}.yaml"


def load_sop(username: str, sop_id: str) -> Optional[dict]:
    p = sop_path(username, sop_id)
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_sop(username: str, sop_id: str, sop_data: dict):
    d = sop_dir_for_user(username)
    d.mkdir(parents=True, exist_ok=True)
    with open(sop_path(username, sop_id), "w", encoding="utf-8") as f:
        yaml.dump(sop_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def list_all_sops():
    """List all SOPs across all users. Return list of (username, sop_id, sop_data)."""
    result = []
    if not DATA_DIR.exists():
        return result
    for user_dir in DATA_DIR.iterdir():
        if not user_dir.is_dir() or user_dir.name in ("check_ids.yaml", "embeddings.pt"):
            continue
        sops_dir = user_dir / "sops"
        if not sops_dir.exists():
            continue
        for f in sops_dir.glob("*.yaml"):
            sop_id = f.stem
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = yaml.safe_load(fp)
                result.append((user_dir.name, sop_id, data or {}))
            except Exception:
                result.append((user_dir.name, sop_id, {}))
    return result
