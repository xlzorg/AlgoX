from __future__ import annotations

from collections import defaultdict


def signal_quality(records: list[dict]) -> dict[str, dict[str, float | int]]:
        groups: dict[str, list[dict]] = defaultdict(list)
        for record in records:
            groups[str(record.get("strategy_id", "unknown"))].append(record)
        result = {}
        for strategy, items in groups.items():
            predicted = len(items)
            profitable = sum(float(item.get("pnl_pct", 0.0)) > 0 for item in items)
            opportunities = sum(bool(item.get("profitable_opportunity", float(item.get("pnl_pct", 0.0)) > 0)) for item in items)
            precision = profitable / predicted if predicted else 0.0
            recall = profitable / opportunities if opportunities else 0.0
            result[strategy] = {"total_signals": predicted, "profitable": profitable, "precision": precision, "recall": recall, "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}
        return result
