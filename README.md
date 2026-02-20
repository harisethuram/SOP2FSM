# SOP Builder

A local web app to create and visualize **Standard Operating Procedures (SOPs)** as directed graphs (finite-state style). Supports a global canonical check library and embedding-based duplicate detection.

## Setup

```bash
cd c:\DevCode\503_project
pip install -r requirements.txt
```

Requirements: Python 3.10+, Flask, PyYAML, sentence-transformers, torch.

## Run

```bash
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). Log in with any username (password is ignored for the demo).

## Features

- **Login** — Enter a username (no real auth).
- **Home** — Links to “View All SOPs” and “Create SOP”.
- **View All SOPs** — List of all SOPs (all users); each links to its flowchart view.
- **View SOP** — Flowchart of states and transitions; start state in green, end states in red; state details listed below.
- **Create SOP** — Create a new SOP by ID/title, then add states one by one. Each state has:
  - State ID, Check ID, Check text
  - Role: start / end / neither
  - Transition description and next state IDs
  - On submit: structural validation, then embedding similarity check (≥0.95). If duplicate or similar checks are found, you can accept an existing check or proceed with a new one (unique check_id). Canonical checks and embeddings are stored in `data/check_ids.yaml` and `data/embeddings.pt`. When done, click “Save SOP” to finalize.

## Data layout

- `data/check_ids.yaml` — Canonical checks (check_id, check_text, created_at).
- `data/embeddings.pt` — Torch tensor of normalized embeddings for those checks.
- `data/<username>/sops/<sop_id>.yaml` — One SOP file per user/SOP.

See `design.md` for the full specification.
