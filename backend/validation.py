"""Structural validation and confirmation workflow for states and SOPs."""
from typing import List

from backend import data_store
from backend import embeddings


def validate_new_state(sop_states: list, state_id: str, is_start: bool, is_end: bool,
                       next_state_ids: list, has_existing_start: bool) -> List[str]:
    """Return list of error messages. Empty if valid."""
    errors = []
    state_ids = {s.get("state_id") for s in sop_states if s.get("state_id")}
    if state_id in state_ids:
        errors.append("Duplicate state_id: this SOP already has a state with this id.")
    if has_existing_start and is_start:
        errors.append("This SOP already has a start state; you cannot add another.")
    if is_end and next_state_ids:
        errors.append("End states must not have any next states.")
    # All next_state_ids must exist in SOP (we allow END_* as logical refs; they may be added later)
    valid_next = set(state_ids) | {"END_SUCCESS", "END_INVALID", "END_UNAUTHORIZED"}
    for nid in next_state_ids:
        if nid and nid not in valid_next:
            errors.append(f"next_state_id '{nid}' is not yet in this SOP.")
    return errors


def check_duplicate_check_id(check_id: str) -> bool:
    return data_store.get_check_by_id(check_id) is not None


def get_similar_checks(check_text: str, threshold: float = 0.95):
    """Return list of (check_dict, similarity) for existing checks above threshold."""
    similar = embeddings.find_similar_check_ids(check_text, threshold)
    checks = data_store.load_check_ids()
    return [(checks[i], sim) for i, sim in similar]


def validate_sop_final(sop_data: dict) -> List[str]:
    """After all states added: exactly one start, at least one end, all next_state_ids exist."""
    errors = []
    states = sop_data.get("states") or []
    state_ids = {s.get("state_id") for s in states}
    starts = [s for s in states if s.get("is_start")]
    ends = [s for s in states if s.get("is_end")]
    if len(starts) != 1:
        errors.append("SOP must have exactly one start state.")
    if len(ends) < 1:
        errors.append("SOP must have at least one end state.")
    for s in states:
        for nid in s.get("next_state_ids") or []:
            if nid and nid not in state_ids:
                errors.append(f"next_state_id '{nid}' does not exist in this SOP.")
    return errors
