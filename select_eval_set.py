#!/usr/bin/env python
"""
select_eval_set.py — deterministic, stratified selection of frozen-eval candidates.

Proposes which plans should form the frozen held-out eval set (program.md P0).
It ONLY proposes a plan_id list. It does NOT move files, create data/eval_set/,
or --freeze anything. Run it on the real dataset, review eval_candidates.txt,
then (separately, after sign-off) populate + freeze the eval set.

Selection criteria (program.md P0):
  - deterministic + seeded (reproducible; --seed)
  - stratified by room-class so classes appear in eval ~ their corpus rate
  - ~5% held out (default --frac 0.05, i.e. ~250 of 5000), or exact --n
  - strict disjointness: eval and train pools share no plan_id
  - no cherry-picking: selection optimizes ONLY class balance, never difficulty

INPUT — provide exactly one (this script makes no assumptions about your CAD
format; you map your data to one of these simple shapes):

  --manifest FILE.csv   CSV with a header row and columns `plan_id,classes`.
                        `classes` = semicolon-separated room-class names for that
                        plan (repeat a name per instance), e.g.:
                            plan_id,classes
                            10001,kitchen;bedroom;bedroom;bathroom
                            10002,living;kitchen

  --labels-dir DIR      directory of YOLO-seg .txt label files (e.g. after P1).
                        plan_id = filename stem; each line's first token is the
                        class id. Optional --names FILE maps id->name (one name
                        per line; line index = id) for a readable report.

OUTPUT:
  eval_candidates.txt   selected plan_ids, one per line, sorted — REVIEW THIS
  train_pool.txt        the disjoint remainder, one per line, sorted
  + a per-class summary (corpus vs eval instance counts, rare-class warnings)

This script never writes to data/eval_set/ and never freezes anything.
"""
from __future__ import annotations

import argparse
import csv
import random
from collections import Counter
from pathlib import Path


def load_manifest_csv(path: str) -> dict[str, Counter]:
    """plan_id -> Counter(class_name -> instance count) from a CSV manifest."""
    plans: dict[str, Counter] = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        if "plan_id" not in cols or "classes" not in cols:
            raise SystemExit("manifest CSV must have header columns: plan_id, classes")
        for row in reader:
            pid = (row.get("plan_id") or "").strip()
            if not pid:
                continue
            classes = [c.strip() for c in (row.get("classes") or "").split(";") if c.strip()]
            plans[pid] = Counter(classes)
    return plans


def load_labels_dir(path: str, names: list[str] | None) -> dict[str, Counter]:
    """plan_id -> Counter(class -> count) from a dir of YOLO-seg .txt labels."""
    plans: dict[str, Counter] = {}
    for txt in sorted(Path(path).glob("*.txt")):
        counts: Counter = Counter()
        for line in txt.read_text().splitlines():
            parts = line.split()
            if not parts:
                continue
            try:
                cid = int(float(parts[0]))
            except ValueError:
                continue
            name = names[cid] if names and 0 <= cid < len(names) else str(cid)
            counts[name] += 1
        plans[txt.stem] = counts
    return plans


def select(plans: dict[str, Counter], eval_n: int, seed: int):
    """Greedy min-gap stratified selection — deterministic given `seed`.

    At each step it picks the not-yet-selected plan that brings the eval set's
    per-class instance distribution closest to the corpus distribution. Difficulty
    never enters the objective, so it stratifies without cherry-picking. A seeded
    shuffle sets iteration order and breaks ties, making runs reproducible.
    """
    corpus: Counter = Counter()
    for c in plans.values():
        corpus.update(c)
    total_instances = sum(corpus.values()) or 1

    rng = random.Random(seed)
    order = sorted(plans)      # stable base order
    rng.shuffle(order)         # seeded randomness — the no-cherry-pick backbone

    selected: list[str] = []
    sel: Counter = Counter()
    remaining = list(order)

    def gap_if_added(pid: str) -> float:
        after = sel + plans[pid]
        after_total = sum(after.values()) or 1
        return sum(
            abs(after.get(cls, 0) / after_total - corpus[cls] / total_instances)
            for cls in corpus
        )

    while len(selected) < eval_n and remaining:
        best_pid, best_gap = None, None
        for pid in remaining:            # shuffled order → deterministic tie-break
            g = gap_if_added(pid)
            if best_gap is None or g < best_gap:
                best_gap, best_pid = g, pid
        selected.append(best_pid)
        sel.update(plans[best_pid])
        remaining.remove(best_pid)

    return selected, remaining, corpus, sel


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Propose frozen-eval candidates (program.md P0). Does NOT freeze.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--manifest", help="CSV with columns plan_id,classes (;-separated classes)")
    src.add_argument("--labels-dir", help="dir of YOLO-seg .txt labels (plan_id=stem, class=first token)")
    ap.add_argument("--names", help="optional class-names file for --labels-dir (one per line; index=id)")
    ap.add_argument("--frac", type=float, default=0.05, help="fraction held out for eval (default 0.05)")
    ap.add_argument("--n", type=int, default=None, help="exact eval size (overrides --frac)")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for deterministic selection")
    ap.add_argument("--min-per-class", type=int, default=30,
                    help="warn if an eval class has fewer than this many instances")
    ap.add_argument("--out", default="eval_candidates.txt")
    ap.add_argument("--train-out", default="train_pool.txt")
    args = ap.parse_args(argv)

    names = None
    if args.names:
        names = [ln.strip() for ln in Path(args.names).read_text().splitlines()]

    plans = load_manifest_csv(args.manifest) if args.manifest \
        else load_labels_dir(args.labels_dir, names)

    # eval images must carry ground truth → a plan needs >=1 class instance
    eligible = {pid: c for pid, c in plans.items() if sum(c.values()) > 0}
    n_excluded = len(plans) - len(eligible)
    total = len(eligible)
    if total == 0:
        raise SystemExit("no eligible plans (each needs >=1 room-class instance)")

    eval_n = args.n if args.n is not None else max(1, round(args.frac * total))
    eval_n = min(eval_n, total)

    selected, remaining, corpus, sel = select(eligible, eval_n, args.seed)

    Path(args.out).write_text("\n".join(sorted(selected)) + "\n")
    Path(args.train_out).write_text("\n".join(sorted(remaining)) + "\n")

    disjoint = not (set(selected) & set(remaining))
    print(f"[select] source={'manifest' if args.manifest else 'labels-dir'} seed={args.seed}")
    print(f"[select] plans total={len(plans)} eligible={total} excluded_no_gt={n_excluded}")
    print(f"[select] eval={len(selected)} ({len(selected)/total*100:.1f}%)  train_pool={len(remaining)}")
    print(f"[select] disjoint eval/train: {'OK' if disjoint else 'FAIL'}")
    print()
    print(f"{'class':<16}{'corpus':>10}{'eval':>8}{'eval%':>8}")
    warnings = []
    for cls in sorted(corpus, key=lambda c: -corpus[c]):
        corp_ct, ev = corpus[cls], sel.get(cls, 0)
        pct = (ev / corp_ct * 100) if corp_ct else 0.0
        print(f"{cls:<16}{corp_ct:>10}{ev:>8}{pct:>7.1f}%")
        if ev < args.min_per_class:
            warnings.append((cls, ev))
    print()
    for cls, ev in warnings:
        print(f"[warn] class '{cls}' has only {ev} eval instances (< {args.min_per_class}) — under-represented")
    print(f"\n[select] wrote {args.out} ({len(selected)} plan_ids) and {args.train_out} ({len(remaining)}).")
    print("[select] REVIEW eval_candidates.txt. This script did NOT create or --freeze the eval set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
