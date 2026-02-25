"""
SOP Builder - Flask app.
Login (dummy), Index, View All SOPs, View SOP (flowchart), Create SOP with state workflow.
"""
import os
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, flash
import torch

from backend import data_store
from backend import embeddings
from backend import validation

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
app.config["DATA_DIR"] = Path(app.root_path) / "data"


def current_user():
    return session.get("username")


def require_login(f):
    from functools import wraps
    @wraps(f)
    def inner(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return inner


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        if username:
            session["username"] = username
            return redirect(url_for("index"))
        flash("Please enter a username.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("login"))


@app.route("/")
@require_login
def index():
    return render_template("index.html", username=current_user())


@app.route("/sops")
@require_login
def view_all_sops():
    sops = data_store.list_all_sops()
    return render_template("view_sops.html", sops=sops, username=current_user())


@app.route("/sops/<sop_id>")
@require_login
def view_sop(sop_id):
    sop = data_store.load_sop(sop_id)
    if not sop:
        flash("SOP not found.")
        return redirect(url_for("view_all_sops"))
    checks = {c["check_id"]: c for c in data_store.load_check_ids()}
    return render_template("view_sop.html", sop=sop, sop_id=sop_id, checks=checks)


@app.route("/sops/create", methods=["GET", "POST"])
@require_login
def create_sop():
    """Page 1: create a new SOP (id + title only)."""
    username = current_user()

    if request.method == "POST":
        sop_id = (request.form.get("sop_id") or "").strip()
        title = (request.form.get("sop_title") or "").strip()
        if not sop_id:
            flash("SOP ID is required.")
            return render_template("create_sop.html")
        if data_store.load_sop(sop_id):
            flash("An SOP with this ID already exists.")
            return render_template("create_sop.html")
        # Start a fresh draft for this SOP (session + file so it survives redirects)
        draft = {"title": title, "states": [], "sop_id": sop_id, "version": 1}
        session["draft_sop"] = draft
        session.modified = True
        data_store.save_draft_sop(sop_id, draft)
        app.logger.info("User %s started SOP %s (title=%r)", username, sop_id, title)
        return redirect(url_for("build_sop"))

    return render_template("create_sop.html")


@app.route("/sops/build", methods=["GET", "POST"])
@require_login
def build_sop():
    """Page 2: add states to the in-progress SOP and finalize it."""
    username = current_user()
    draft = session.get("draft_sop")
    if not draft or not draft.get("sop_id"):
        flash("Start by creating a new SOP.")
        return redirect(url_for("create_sop"))

    if request.method == "POST":
        action = request.form.get("action")

        if action == "validate_state":
            return _handle_validate_state(username)

        if action == "confirm_proceed":
            return _handle_confirm_proceed(username)

        if action == "confirm_accept":
            return _handle_confirm_accept(username)

        if action == "finalize":
            return _handle_finalize(username)

    # Prefer draft from file (survives redirects); fall back to session
    sop_id = (draft.get("sop_id") or "").strip()
    file_draft = data_store.load_draft_sop(sop_id) if sop_id else None
    if file_draft:
        draft = file_draft
        session["draft_sop"] = draft
    checks = data_store.load_check_ids()
    similar = session.pop("similar_checks", None) or []
    dup_id = session.pop("duplicate_check_id", None)
    # Keep pending_state in session until they submit confirm_accept/confirm_proceed
    pending = session.get("pending_state")
    finalize_errors = session.pop("finalize_errors", None)
    # If duplicate by check_id, add that check to the list so user can accept it
    if dup_id and pending:
        dup_check = data_store.get_check_by_id(pending.get("check_id", ""))
        if dup_check and not any(c.get("check_id") == dup_check.get("check_id") for c, _ in similar):
            similar = [(dup_check, 1.0)] + similar  # show as "exact match"
    # Missing states: referenced in next_state_ids but not yet in the draft
    states = draft.get("states") or []
    current_ids = {s.get("state_id") for s in states if s.get("state_id")}
    referenced = set()
    for s in states:
        for nid in s.get("next_state_ids") or []:
            if nid:
                referenced.add(nid)
    missing_state_ids = sorted(referenced - current_ids)
    return render_template("build_sop.html", draft=draft, checks=checks,
                           similar_checks=similar, duplicate_check_id=dup_id,
                           pending_state=pending, finalize_errors=finalize_errors,
                           missing_state_ids=missing_state_ids)


def _handle_validate_state(username):
    """Validate state (id uniqueness + embedding similarity). If pass and no dup/similar, add state. Else store pending and show confirm UI."""
    draft = session["draft_sop"]
    states = list(draft.get("states") or [])
    state_id = (request.form.get("state_id") or "").strip()
    role = request.form.get("role", "neither")  # start | end | neither
    is_start = role == "start"
    is_end = role == "end"

    app.logger.info(
        "User %s adding state %s (role=%s, is_start=%s, is_end=%s) to SOP %s",
        username,
        state_id,
        role,
        is_start,
        is_end,
        draft.get("sop_id"),
    )

    if is_end:
        # End state: only state_id required; no check, no transition, no next states
        check_id = ""
        check_text = ""
        trans_desc = ""
        next_state_ids = []
    else:
        check_id = (request.form.get("check_id") or "").strip()
        check_text = (request.form.get("check_text") or "").strip()
        trans_desc = (request.form.get("transition_function_description") or "").strip()
        next_raw = request.form.get("next_state_ids", "")
        next_state_ids = [x.strip() for x in next_raw.replace(",", " ").split() if x.strip()]

    has_start = any(s.get("is_start") for s in states)

    # Structural validation
    errs = validation.validate_new_state(states, state_id, is_start, is_end, next_state_ids, has_start)
    if errs:
        app.logger.warning(
            "Add state failed structural validation for user %s, SOP %s, state %s: %s",
            username,
            draft.get("sop_id"),
            state_id,
            "; ".join(errs),
        )
        for e in errs:
            flash(e)
        return redirect(url_for("build_sop"))

    if not is_end and (not check_id or not check_text):
        app.logger.warning(
            "Add state failed content validation (missing check_id/check_text) for user %s, SOP %s, state %s",
            username,
            draft.get("sop_id"),
            state_id,
        )
        flash("Check ID and Check text are required for non-end states.")
        return redirect(url_for("build_sop"))

    if is_end:
        # Add end state only; no canonical check or embedding
        states.append({
            "state_id": state_id, "is_start": False, "is_end": True,
            "transition_function_description": "", "next_state_ids": [],
        })
        new_draft = {**draft, "states": states}
        session["draft_sop"] = new_draft
        session.modified = True
        data_store.save_draft_sop(draft.get("sop_id", ""), new_draft)
        flash("End state added.")
        app.logger.info(
            "End state %s added for user %s, SOP %s",
            state_id,
            username,
            draft.get("sop_id"),
        )
        return redirect(url_for("build_sop"))

    # Non-end state: duplicate check_id? / similar embeddings?
    dup_id = validation.check_duplicate_check_id(check_id)
    similar = validation.get_similar_checks(check_text) if check_text else []

    pending = {
        "state_id": state_id, "check_id": check_id, "check_text": check_text,
        "is_start": is_start, "is_end": False,
        "transition_function_description": trans_desc, "next_state_ids": next_state_ids,
    }

    if dup_id or similar:
        session["similar_checks"] = similar
        session["duplicate_check_id"] = dup_id
        session["pending_state"] = pending
        app.logger.info(
            "Duplicate/similar checks found when adding state %s for user %s, SOP %s, check_id=%s, similar_count=%d",
            state_id,
            username,
            draft.get("sop_id"),
            check_id,
            len(similar),
        )
        return redirect(url_for("build_sop"))

    # No duplicate/similar: add canonical check if new, then add state
    _append_check_and_embed_if_new(check_id, check_text)
    states.append({
        "state_id": state_id, "check_id": check_id, "is_start": is_start, "is_end": False,
        "transition_function_description": trans_desc, "next_state_ids": next_state_ids,
    })
    new_draft = {**draft, "states": states}
    session["draft_sop"] = new_draft
    session.modified = True
    data_store.save_draft_sop(draft.get("sop_id", ""), new_draft)
    flash("State added.")
    app.logger.info(
        "State %s added for user %s, SOP %s with check_id=%s",
        state_id,
        username,
        draft.get("sop_id"),
        check_id,
    )
    return redirect(url_for("build_sop"))


def _handle_confirm_proceed(username):
    pending = session.pop("pending_state", None)
    if not pending:
        flash("No pending state.")
        app.logger.warning("confirm_proceed called with no pending_state for user %s", username)
        return redirect(url_for("build_sop"))
    # User insists check is new: ensure check_id is unique, append check + embedding, add state
    check_id = (pending.get("check_id") or "").strip()
    check_text = (pending.get("check_text") or "").strip()
    if validation.check_duplicate_check_id(check_id):
        flash("That check_id is already in the library. Choose a different check_id or accept an existing check.")
        session["pending_state"] = pending
        session["similar_checks"] = session.get("similar_checks")
        session["duplicate_check_id"] = True
        app.logger.warning(
            "confirm_proceed failed: chosen check_id already exists for user %s: %s",
            username,
            check_id,
        )
        return redirect(url_for("build_sop"))
    _append_check_and_embed_if_new(check_id, check_text)
    draft = session.get("draft_sop") or {}
    states = list(draft.get("states") or [])
    # Carry over all form data; use the new check_id/check_text from the form
    next_ids = pending.get("next_state_ids")
    if not isinstance(next_ids, list):
        next_ids = list(next_ids) if next_ids else []
    states.append({
        "state_id": pending["state_id"],
        "check_id": check_id,
        "is_start": pending.get("is_start", False),
        "is_end": pending.get("is_end", False),
        "transition_function_description": pending.get("transition_function_description") or "",
        "next_state_ids": next_ids,
    })
    new_draft = {**draft, "states": states}
    session["draft_sop"] = new_draft
    session.modified = True
    data_store.save_draft_sop(draft.get("sop_id", ""), new_draft)
    flash("State added with new canonical check.")
    app.logger.info(
        "State %s confirmed with new canonical check %s for user %s, SOP %s",
        pending["state_id"],
        check_id,
        username,
        draft.get("sop_id"),
    )
    return redirect(url_for("build_sop"))


def _handle_confirm_accept(username):
    pending = session.pop("pending_state", None)
    accepted_check_id = request.form.get("accepted_check_id", "").strip()
    # If no radio was selected, use first similar check when we have pending + similar list
    if not accepted_check_id and pending:
        similar = session.get("similar_checks") or []
        if similar:
            accepted_check_id = (similar[0][0].get("check_id") or "").strip()
    if not pending or not accepted_check_id:
        flash("Select a check to accept.")
        if pending:
            session["pending_state"] = pending
            session["similar_checks"] = session.get("similar_checks")
            session["duplicate_check_id"] = session.get("duplicate_check_id")
        app.logger.warning("confirm_accept failed: no selection or no pending state for user %s", username)
        return redirect(url_for("build_sop"))
    if not data_store.get_check_by_id(accepted_check_id):
        flash("Invalid check selected.")
        session["pending_state"] = pending
        app.logger.warning(
            "confirm_accept failed: invalid check_id %s for user %s",
            accepted_check_id,
            username,
        )
        return redirect(url_for("build_sop"))
    draft = session.get("draft_sop") or {}
    states = list(draft.get("states") or [])
    # Carry over all form data; only the check is the selected existing one
    next_ids = pending.get("next_state_ids")
    if not isinstance(next_ids, list):
        next_ids = list(next_ids) if next_ids else []
    states.append({
        "state_id": pending["state_id"],
        "check_id": accepted_check_id,
        "is_start": pending.get("is_start", False),
        "is_end": pending.get("is_end", False),
        "transition_function_description": pending.get("transition_function_description") or "",
        "next_state_ids": next_ids,
    })
    # Build a new dict and persist to file so redirect shows the new state
    new_draft = {
        "title": draft.get("title", ""),
        "sop_id": draft.get("sop_id", ""),
        "version": draft.get("version", 1),
        "states": states,
    }
    session["draft_sop"] = new_draft
    session.modified = True
    data_store.save_draft_sop(draft.get("sop_id", ""), new_draft)
    flash("State added using existing check.")
    app.logger.info(
        "State %s confirmed using existing check %s for user %s, SOP %s",
        pending["state_id"],
        accepted_check_id,
        username,
        draft.get("sop_id"),
    )
    return redirect(url_for("build_sop"))


def _append_check_and_embed_if_new(check_id: str, check_text: str):
    if data_store.get_check_by_id(check_id):
        return
    # Log cosine similarity to every existing check (before appending the new one)
    all_sims = embeddings.get_cosine_similarities_to_all(check_text)
    checks = data_store.load_check_ids()
    for idx, sim in all_sims:
        existing_id = checks[idx].get("check_id", "") if idx < len(checks) else ""
        app.logger.info(
            "New check %r cosine similarity to existing check %r: %.4f",
            check_id,
            existing_id,
            sim,
        )
    data_store.append_canonical_check(check_id, check_text)
    vec = embeddings.embed_text(check_text)
    t = embeddings.load_embeddings_tensor()
    new_row = torch.from_numpy(vec).unsqueeze(0).to(t.dtype)
    t = torch.cat([t, new_row], dim=0)
    embeddings.save_embeddings_tensor(t)


def _handle_finalize(username):
    draft = session.get("draft_sop", {})
    sop_id = (draft.get("sop_id") or "").strip()
    if not sop_id:
        flash("Create an SOP first (set SOP ID and title).")
        app.logger.warning("Finalize called with no sop_id for user %s", username)
        return redirect(url_for("create_sop"))
    errs = validation.validate_sop_final(draft)
    if errs:
        for e in errs:
            flash(e)
        app.logger.warning(
            "Finalize failed validation for user %s, SOP %s: %s",
            username,
            sop_id,
            "; ".join(errs),
        )
        # Persist errors so the build page can show an unavoidable alert
        session["finalize_errors"] = errs
        return redirect(url_for("build_sop"))
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sop_data = {
        "title": draft.get("title", ""),
        "created_at": now,
        "version": draft.get("version", 1),
        "states": draft.get("states", []),
    }
    data_store.save_sop(sop_id, sop_data)
    data_store.delete_draft_sop(sop_id)
    session.pop("draft_sop", None)
    flash("SOP saved successfully.")
    app.logger.info(
        "SOP %s saved for user %s with %d states",
        sop_id,
        username,
        len(sop_data.get("states") or []),
    )
    return redirect(url_for("view_sop", sop_id=sop_id))


def _mermaid_id(s: str) -> str:
    """Mermaid-safe node ID: prefix with 's_' to avoid reserved words (e.g. end, start)."""
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in (s or ""))
    return "s_" + safe if safe else "s_empty"


@app.template_filter("sop_mermaid")
def sop_mermaid(sop):
    """Generate Mermaid flowchart definition from SOP states."""
    lines = ["flowchart LR", "    classDef startNode fill:#3fb950,stroke:#2ea043,color:#fff", "    classDef endNode fill:#f85149,stroke:#da3633,color:#fff"]
    states = sop.get("states") or []
    for s in states:
        sid = s.get("state_id", "")
        mid = _mermaid_id(sid)
        label = sid.replace('"', '\\"')
        if s.get("is_start"):
            lines.append(f'    {mid}(["{label}"])')
        elif s.get("is_end"):
            lines.append(f'    {mid}[["{label}"]]')
        else:
            lines.append(f'    {mid}["{label}"]')
    for s in states:
        src_id = _mermaid_id(s.get("state_id", ""))
        for nid in s.get("next_state_ids") or []:
            if nid:
                tgt_id = _mermaid_id(nid)
                lines.append(f"    {src_id} --> {tgt_id}")
    for s in states:
        mid = _mermaid_id(s.get("state_id", ""))
        if s.get("is_start"):
            lines.append(f"    class {mid} startNode")
        elif s.get("is_end"):
            lines.append(f"    class {mid} endNode")
    return "\n".join(lines)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(debug=True, port=port)
