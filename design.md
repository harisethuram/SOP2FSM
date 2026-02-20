
# SOP Builder – Local MVP with Embedding-Based Duplicate Detection


# 1. Overview

This system enables users to create and visualize Standard Operating Procedures (SOPs) as directed graphs of states (finite-state-machine style).

Key goals:
- Represent SOPs as graph/FSM workflows.Specifically,
	-  Each state consists of two components. A canonical check dictating the logic of the state, and a transition function. 
	- An SOP has exactly one start state and at least one end state. 

- We maintain a **global canonical check library** (identified by check text/check id). 

- Prevent semantically redundant canonical checks using high-quality embeddings, between and within SOPs.

- Store everything locally using YAML + embedding tensors.

- Keep implementation simple and file-based for MVP speed.

No orgs. No database. Fully local (for quick implementation sake).

---
# 2. Core Concepts
## 2.1 Canonical Check

A **Canonical Check** represents a logical condition or validation step. Example:

```yaml
check_id: token_verify
check_text: "Verify that the token is valid"
created_at: 2025-01-12T12:00:00
```

Identity is based solely on:
-  `check_text`
-  `check_id`

Transition behavior is NOT part of identity.

This allows:
- Same check reused across multiple SOPs
- Different SOPs to branch differently after the same check, using SOP-specific transition functions.

## 2.2 SOP

An SOP is a graph referencing canonical checks. For each state, an SOP stores only:
- A `state_id`, a unique identifier for each state **within** an SOP.
- Which canonical check the state references (by `check_id`)
- Whether that state is a start or end (or neither) state
- The description of the **transition function**, which dictates the next state to go to given the outcome of the current canonical check. 
- A list of the `state_id`'s that this state can transition to (this information is also present in the transition function).

# 3. Storage 
## 3.1 Layout (Local File System)
```
project_root/
│
├── backend/
│
├── data/
│ ├── check_ids.yaml
│ ├── embeddings.pt
│ └── <username>/
│ └── sops/
│ └── example_sop.yaml
```
## 3.2 Canonical Check Library Storage
### `data/check_ids.yaml`
Ordered list of canonical checks, ordered by creation time. Example: 
```yaml
- check_id: "verify_token"
  check_text: "Verify that the authentication token is valid and not expired"
  created_at: "2026-02-19T13:05:00Z"

- check_id: "permission_verify"
  check_text: "Ensure the user has the required role permissions to perform this action"
  created_at: "2026-02-19T13:07:30Z"

- check_id: "fields_present"
  check_text: "Confirm that all required input fields are present and correctly formatted"
  created_at: "2026-02-19T13:10:12Z"
```
All `check_id` values must be unique, and all checks must serve a distinct purpose (which we try to enforce using embeddings).

### `data/embeddings.pt`
A torch tensor consisting of embedding representations of the canonical checks (derived from each check's `check_text`. 
- shape = (num_canonical_checks, embedding_dim)
- dtype = float32
- normalized (unit vectors)
- Row `i` corresponds to `check_ids.yaml[i]`
- Order must match the creation date order in `check_ids.yaml`
- `len(check_ids) == embeddings.shape[0]`

## 3.3 SOP File Format

Stored at `data/username/sop_name.yaml`
Example:
```yaml
title: "User Access Validation Flow"
created_at: "2026-02-19T13:20:00Z"
version: 1

states:
  - state_id: "token_validity"
    is_start: true
    is_end: false
    check_id: "verify_token"
    transition_function_description: "If check is true, proceed to permission_validity. If false, terminate."
    next_state_ids:
      - "permission_validity"      
      - "END_INVALID"  # Logical end reference (see below)

  - state_id: "permission_validity"
    is_start: false
    is_end: false
    check_id: "verify_permission"
    transition_function_description: "If check is true, proceed to input validation. Otherwise terminate."
    next_state_ids:
      - "END_SUCCESS"
      - "END_INVALID"

  - state_id: "END_SUCCES"
    is_start: false
    is_end: true
    next_state_ids: []

  - state_id: "END_UNEND_INVALIDAUTHORIZED"
    is_start: false
    is_end: true
    next_state_ids: []
```

# 4. Embeddings
To prevent different canonical checks with the same or similar logic to exist, we create an embedding for each canonical check. When users enter SOPs state by state, we compare the normalized embedding of the `check_text` and dot it with the tensor in `data/embeddings.pt`. If any of the dot products are > 0.95, we show the user the pre-existing similar checks and get their confirmation if they want to reuse one of those checks or still proceed with adding the new one. 

We want:
- a model that can generate high-quality semantic embeddings, suitable for cosine similarity.
	- Output vector normalized to unit length
	- Cosine similarity computed as dot product.
	- Stored as float32.
- to embed the only `check_text` of a canonical check (we do not embed transition functions, or any other component of a state).




# 5. New State Workflow
When the user adds a new state to a SOP, they submit:
- `state_id` - str
- `check_id` - str
- `check_text` - str
- `is_start`, `is_end` - bools, submitted as three choice radio start/end/neither (the default)
- `transition_function_description` - str
- `next_state_ids` - list of state ids. 
  
When they enter submit for the SOP state, trigger the Structural Validation (5.1) and its following workflows (5.2, 5.3)
## 5.1. Structural Validation
First, some rule-based checks:
1. Enforce no duplicate `state_id` i.e. there isn't already a state with the same id in this SOP.
2. Enforce exactly one start state is entered.
3. Look for duplicate `check_id` exists across all canonical checks stored. 

## 5.2 Embedding
Embed, normalize and compare:
- embedding = embed(check_text)
- Normalize
- For each existing embedding:
	- similarity = dot(new_embedding, existing_embedding)
	- Threshold: similarity >= 0.95

## 5.3 Confirmation Workflow

This will be executed if either a duplicate `check_id` is detected, or any canonical checks meet the embedding threshold. In this case:
- Display all duplicate canonical checks (along either high similarity score or `check_id`)
- User can either choose:
	- Proceed: they are confident the canonical check they are adding is new and unique. Enforce that the entered `check_id` is unique. 
		- Append the new canonical check to `data/check_ids.yaml`
		- Append embedding row to `data/embeddings.pt`
	- Accept: they click on and choose one of the displayed duplicate canonical checks along with its `check_id`

## 5.4 Add State Workflow
Add the new state to the SOP, and the new canonical check to `data/check_ids.yaml`, along with its embedding to `data/embeddings.pt`, enforcing that its `state_id` and `check_id` are not duplicates. If there already exists a start state, enforce that this cannot be one. If the state is an end state, enforce that it does not have any next states.
# 6. SOP Creation Workflow
When the user creates a new SOP, they submit:
- `sop_id`: a unique identifier of the SOP.
- `sop_description`: a description of the SOP.
- SOP states: added one-by-one, each triggering the New State Workflow (5). 
- At the end (once user has added all states), verify the following:
	- For exactly one is_start: true
	- For at least one is_end: true
	- All next_state_ids must exist in the SOP


# 7. UI
Pages (keep all objects aligned to center of screen):
- Login (username, dummy password)
- Index: Links to the following pages:
	- View All SOPs (of all users)
	- Create SOP
- View All SOPs: Present as vertically stacked boxes, each as a link to view an SOP view.
	- A flow chart, with arrows between connecting states. Each vertex just shows the state id. User can click on state to see more information i.e. check / transition description. Highlight the start state in green, and the end state(s) in red.
- Create SOP: Trigger SOP Creation Workflow
	- Has separate submit buttons for state-level and SOP level. 

# 8. System Summary

This design:
- Separates canonical checks from the rest of the state.
- Uses high-quality embeddings for semantic deduplication.
- Maintains simple, inspectable YAML storage.
- Keeps embeddings aligned deterministically to their corresponding canonical checks.