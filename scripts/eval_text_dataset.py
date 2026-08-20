"""Eval the Claude-based text classifier against datasets/dataset.csv.

Usage:
    python scripts/eval_text_dataset.py [--n 10] [--seed 0]

Requires ANTHROPIC_API_KEY. Takes a stratified sample (--n per category,
default 10) instead of running all 2360 rows, to keep it fast/cheap.
Reports binary precision/recall (any finding vs. label) plus a
per-category breakdown of what pattern_type Claude actually picked.
"""
import argparse
import collections
import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analysis.llm_classify import classify_text

CSV_PATH = Path(__file__).resolve().parents[1] / "datasets" / "dataset.csv"


def load_stratified_sample(n_per_category: int, seed: int) -> list[dict]:
    by_category = collections.defaultdict(list)
    with CSV_PATH.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_category[row["Pattern Category"]].append(row)

    rng = random.Random(seed)
    sample = []
    for category, rows in by_category.items():
        rng.shuffle(rows)
        sample.extend(rows[:n_per_category])
    return sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=10, help="rows per category")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    sample = load_stratified_sample(args.n, args.seed)
    print(f"Evaluating {len(sample)} rows ({args.n} per category)...\n")

    tp = fp = tn = fn = 0
    category_hits = collections.Counter()

    for i, row in enumerate(sample, 1):
        text, label, category = row["text"], row["label"], row["Pattern Category"]
        findings = classify_text(text)
        found = len(findings) > 0
        expected = label == "1"

        if found and expected:
            tp += 1
        elif found and not expected:
            fp += 1
        elif not found and expected:
            fn += 1
        else:
            tn += 1

        if found and expected:
            category_hits[category] += 1

        print(f"[{i}/{len(sample)}] {category!r:20} label={label} found={found} "
              f"types={[x['pattern_type'] for x in findings]}")

    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    accuracy = (tp + tn) / len(sample)

    print(f"\n--- Results (n={len(sample)}) ---")
    print(f"TP={tp} FP={fp} TN={tn} FN={fn}")
    print(f"Precision={precision:.2f} Recall={recall:.2f} Accuracy={accuracy:.2f}")


if __name__ == "__main__":
    main()
