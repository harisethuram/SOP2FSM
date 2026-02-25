"""File-based storage: check_ids.yaml, embeddings.pt, SOPs (global, no users)."""
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
import yaml

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CHECK_IDS_PATH = DATA_DIR / "check_ids.yaml"
SOPS_DIR = DATA_DIR / "sops"
DRAFTS_DIR = DATA_DIR / "drafts"


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


def draft_path(sop_id: str) -> Path:
    return DRAFTS_DIR / f"{sop_id}.yaml"


def save_draft_sop(sop_id: str, draft: dict):
    """Persist in-progress draft to file so it survives redirects."""
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(draft_path(sop_id), "w", encoding="utf-8") as f:
        yaml.dump(draft, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def load_draft_sop(sop_id: str) -> Optional[dict]:
    """Load draft from file if it exists."""
    p = draft_path(sop_id)
    if not p.exists():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def delete_draft_sop(sop_id: str):
    """Remove draft file after SOP is saved."""
    p = draft_path(sop_id)
    if p.exists():
        p.unlink()


def sop_path(sop_id: str) -> Path:
    return SOPS_DIR / f"{sop_id}.yaml"


def load_sop(sop_id: str) -> Optional[dict]:
    """Load SOP by id. Checks global store first, then legacy per-user stores."""
    # New global store
    p = sop_path(sop_id)
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    # Legacy store: data/<username>/sops/<sop_id>.yaml
    if DATA_DIR.exists():
        for user_dir in DATA_DIR.iterdir():
            if not user_dir.is_dir():
                continue
            legacy = user_dir / "sops" / f"{sop_id}.yaml"
            if legacy.exists():
                with open(legacy, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f)
    return None


def save_sop(sop_id: str, sop_data: dict):
    """Save SOP to global store at data/sops/<sop_id>.yaml."""
    SOPS_DIR.mkdir(parents=True, exist_ok=True)
    with open(sop_path(sop_id), "w", encoding="utf-8") as f:
        yaml.dump(sop_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def list_all_sops():
    """List all SOPs (global + legacy). Return list of (sop_id, sop_data)."""
    result = []

    # New global store
    if SOPS_DIR.exists():
        for f in SOPS_DIR.glob("*.yaml"):
            sop_id = f.stem
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = yaml.safe_load(fp)
                result.append((sop_id, data or {}))
            except Exception:
                result.append((sop_id, {}))

    # Legacy per-user store (read-only listing)
    if DATA_DIR.exists():
        for user_dir in DATA_DIR.iterdir():
            if not user_dir.is_dir():
                continue
            legacy_dir = user_dir / "sops"
            if not legacy_dir.exists():
                continue
            for f in legacy_dir.glob("*.yaml"):
                sop_id = f.stem
                # Avoid duplicate listing if it also exists in the global store
                if sop_path(sop_id).exists():
                    continue
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        data = yaml.safe_load(fp)
                    result.append((sop_id, data or {}))
                except Exception:
                    result.append((sop_id, {}))

    # Stable ordering for UI
    result.sort(key=lambda x: x[0].lower())
    return result
