import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sentence_transformers import SentenceTransformer
from sklearn.metrics import precision_recall_curve, average_precision_score
from collections import defaultdict
from itertools import combinations

with open("sops/all_checks.json") as f:
    checks = json.load(f)

# ---------------------------------------------------------------------------
# Ground truth: mutation pairs from mutations.txt (true inconsistencies).
# Format: frozenset({id_a, id_b}) so order doesn't matter.
# ---------------------------------------------------------------------------
MUTATION_PAIRS = {
    # M1 (cross-SOP within aws)
    frozenset({"aws/patch_processing/step_0", "aws/maintenance_window/step_2"}),
    frozenset({"aws/patch_processing/step_0", "aws/schedule_automations/step_1"}),
    # M2
    frozenset({"aws/patch_processing/step_3a", "aws/patch_processing/step_3"}),
    # M3
    frozenset({"aws/maintenance_window/step_2a", "aws/maintenance_window/step_2"}),
    # M4 (step_6a is the mutation of step_6, tagged [M4] in the SOP)
    frozenset({"aws/maintenance_window/step_6a", "aws/maintenance_window/step_6"}),
    # M5
    frozenset({"nhs/sop_creation/step_9a", "nhs/sop_creation/step_9"}),
    # M6
    frozenset({"nhs/establishing_and_maintaining_tmf_isf/step_1a",
               "nhs/establishing_and_maintaining_tmf_isf/step_1"}),
    # M7
    frozenset({"nhs/establishing_and_maintaining_tmf_isf/step_10a",
               "nhs/establishing_and_maintaining_tmf_isf/step_10"}),
    # M8
    frozenset({"nhs/expediting_urgent_public_health_research/step_1a",
               "nhs/expediting_urgent_public_health_research/step_1"}),
    # M9
    frozenset({"nhs/management_of_research_samples/step_7a",
               "nhs/management_of_research_samples/step_7"}),
    # M10 (cross-SOP within nhs)
    frozenset({"nhs/transportation_of_temperature_sensitive/step_6a",
               "nhs/management_of_research_samples/step_8"}),
    # M11 (cross-SOP within nhs)
    frozenset({"nhs/transportation_of_temperature_sensitive/step_4a",
               "nhs/management_of_research_samples/step_4"}),
    # M12
    frozenset({"color_creek/accounts_payable/step_4b",
               "color_creek/accounts_payable/step_4"}),
    # M13
    frozenset({"york_u/payment_requisition/step_9a",
               "york_u/payment_requisition/step_9"}),
    # M14
    frozenset({"odyssey/transport_logistics_and_invoicing/step_10a",
               "odyssey/transport_logistics_and_invoicing/step_10"}),
    # M15
    frozenset({"tenessee_dot/utilities_invoice_sop/step_6b",
               "tenessee_dot/utilities_invoice_sop/step_6"}),
    # M16
    frozenset({"gemini/understanding_bills_of_lading/step_10a",
               "gemini/understanding_bills_of_lading/step_10"}),
}

# FP pairs (should NOT be flagged — kept here for reporting only)
FP_PAIRS = {
    frozenset({"aws/maintenance_window/step_3a", "aws/maintenance_window/step_3"}),
    frozenset({"aws/patch_processing/step_1b", "aws/patch_processing/step_1a"}),
    frozenset({"nhs/sop_creation/step_8a", "nhs/sop_creation/step_4"}),
    frozenset({"nhs/management_of_research_samples/step_4a",
               "nhs/management_of_research_samples/step_4"}),
    frozenset({"odyssey/transport_logistics_and_invoicing/step_2a",
               "odyssey/transport_logistics_and_invoicing/step_2"}),
    frozenset({"color_creek/accounts_payable/step_8a",
               "color_creek/accounts_payable/step_8"}),
}

# ---------------------------------------------------------------------------
# Group checks by org, embed, build pairs
# ---------------------------------------------------------------------------
org_groups = defaultdict(list)
for c in checks:
    org_groups[c["org"]].append(c)

print("Loading embedding model...")
model = SentenceTransformer("all-MiniLM-L6-v2")

all_texts = [c["check_text"] for c in checks]
print(f"Embedding {len(all_texts)} checks...")
embeddings = model.encode(all_texts, normalize_embeddings=True, show_progress_bar=True)

id_to_idx = {c["id"]: i for i, c in enumerate(checks)}

scores = []
labels = []
pair_ids = []

for org, org_checks in org_groups.items():
    ids = [c["id"] for c in org_checks]
    for i, j in combinations(range(len(ids)), 2):
        a, b = ids[i], ids[j]
        sim = float(np.dot(embeddings[id_to_idx[a]], embeddings[id_to_idx[b]]))
        is_mut = 1 if frozenset({a, b}) in MUTATION_PAIRS else 0
        scores.append(sim)
        labels.append(is_mut)
        pair_ids.append((a, b))

scores = np.array(scores)
labels = np.array(labels)

print(f"\nTotal within-org pairs: {len(scores)}")
print(f"Ground-truth mutation pairs found: {int(labels.sum())} / {len(MUTATION_PAIRS)}")

# ---------------------------------------------------------------------------
# PR curve
# ---------------------------------------------------------------------------
precision, recall, thresholds = precision_recall_curve(labels, scores)
ap = average_precision_score(labels, scores)

fig, ax = plt.subplots(figsize=(10, 7))
ax.plot(recall, precision, "b-", linewidth=2, label=f"PR curve (AP = {ap:.3f})")

for thr, color, marker in [(0.8, "red", "o"), (0.7, "orange", "s"), (0.9, "green", "^")]:
    idx = np.argmin(np.abs(thresholds - thr))
    ax.plot(recall[idx], precision[idx], color=color, marker=marker, markersize=10,
            label=f"t={thr} (P={precision[idx]:.2f}, R={recall[idx]:.2f})")

ax.set_xlabel("Recall", fontsize=14)
ax.set_ylabel("Precision", fontsize=14)
ax.set_title("Precision-Recall Curve — Mutation Detection\n(within-org cosine similarity, all-MiniLM-L6-v2)", fontsize=13)
ax.legend(fontsize=11)
ax.set_xlim([0, 1.05])
ax.set_ylim([0, 1.05])
ax.grid(True, alpha=0.3)

info = (f"Total within-org pairs: {len(scores)}\n"
        f"Ground-truth mutation pairs: {int(labels.sum())}\n"
        f"Orgs evaluated: {len(org_groups)}")
ax.text(0.55, 0.25, info, transform=ax.transAxes, fontsize=10,
        verticalalignment="top",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

plt.tight_layout()
plt.savefig("sops/pr_curve.png", dpi=150)
print("Saved sops/pr_curve.png")

# ---------------------------------------------------------------------------
# Detailed printout
# ---------------------------------------------------------------------------
for thr in [0.7, 0.8, 0.9]:
    tp = int(((scores >= thr) & (labels == 1)).sum())
    fp = int(((scores >= thr) & (labels == 0)).sum())
    fn = int(((scores < thr) & (labels == 1)).sum())
    p = tp / (tp + fp) if (tp + fp) else 0
    r = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * p * r / (p + r) if (p + r) else 0
    print(f"\n--- threshold = {thr} ---")
    print(f"  TP={tp}  FP={fp}  FN={fn}")
    print(f"  Precision={p:.3f}  Recall={r:.3f}  F1={f1:.3f}")

print(f"\n{'='*70}")
print("Mutation pair similarity scores")
print(f"{'='*70}")
mut_results = []
for a, b, s, l in zip(
    [p[0] for p in pair_ids], [p[1] for p in pair_ids], scores, labels
):
    if l == 1:
        mut_results.append((s, a, b))
for s, a, b in sorted(mut_results, reverse=True):
    tag = "HIT" if s >= 0.8 else "MISS"
    print(f"  [{tag}] {s:.4f}  {a}  <->  {b}")

print(f"\n{'='*70}")
print("FP-pair similarity scores (should NOT be flagged)")
print(f"{'='*70}")
for a, b, s, _ in zip(
    [p[0] for p in pair_ids], [p[1] for p in pair_ids], scores, labels
):
    if frozenset({a, b}) in FP_PAIRS:
        tag = "SAFE" if s < 0.8 else "FALSE-ALARM"
        print(f"  [{tag}] {s:.4f}  {a}  <->  {b}")

print(f"\n{'='*70}")
print("Top 15 highest-scoring NON-mutation pairs (potential false alarms)")
print(f"{'='*70}")
non_mut = [(s, a, b) for (a, b), s, l in zip(pair_ids, scores, labels) if l == 0]
non_mut.sort(reverse=True)
for s, a, b in non_mut[:15]:
    fp_tag = " [designed FP]" if frozenset({a, b}) in FP_PAIRS else ""
    print(f"  {s:.4f}  {a}  <->  {b}{fp_tag}")
