from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Regex patterns

# TO RUN:
# python analytics/log_analyzer.py --input C:\AlgoX\logs
# ---------------------------------------------------------------------------

# Example:
# 2026-08-24 15:44:22 | INFO | [SCORING] BTCUSDT 1m |
# ema_trend=+0.00 | ema_fast=+0.00 | macd=+0.00 ...
SCORING_LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} "
    r"\d{2}:\d{2}:\d{2})"
    r"\s+\|\s+"
    r"(?P<level>[A-Z]+)"
    r"\s+\|\s+"
    r"\[SCORING\]\s+"
    r"(?P<symbol>[A-Za-z0-9._/-]+)"
    r"\s+"
    r"(?P<timeframe>[A-Za-z0-9]+)"
    r"\s+\|\s+"
    r"(?P<components>.+?)\s*$"
)

# Example:
# 2026-08-24 15:44:22 | INFO | [SCORING] Weighted Score=+0.000 |
# BUY≥+0.25 | SELL≤-0.55 → HOLD
WEIGHTED_LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} "
    r"\d{2}:\d{2}:\d{2})"
    r"\s+\|\s+"
    r"(?P<level>[A-Z]+)"
    r"\s+\|\s+"
    r"\[SCORING\]\s+"
    r"Weighted Score=(?P<weighted>[+-]?\d+(?:\.\d+)?)"
    r"\s*\|\s*"
    r"BUY[≥>=]+\s*(?P<buy>[+-]?\d+(?:\.\d+)?)"
    r"\s*\|\s*"
    r"SELL[≤<=]+\s*(?P<sell>[+-]?\d+(?:\.\d+)?)"
    r"\s*(?:→|->)\s*"
    r"(?P<decision>BUY|SELL|HOLD|EXIT)"
    r"\s*$",
    re.UNICODE,
)

# component=value
COMPONENT_RE = re.compile(
    r"(?P<name>[A-Za-z0-9_]+)"
    r"\s*=\s*"
    r"(?P<value>[+-]?\d+(?:\.\d+)?)"
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PendingScoring:
    timestamp: str
    level: str
    symbol: str
    timeframe: str
    components: dict[str, float]
    source_file: str
    line_number: int


@dataclass
class ScoringRecord:
    timestamp: str
    symbol: str
    timeframe: str
    weighted_score: float
    buy_threshold: float
    sell_threshold: float
    decision: str
    source_file: str
    source_line: int
    components: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class LogAnalyzer:
    """
    Parse multiple trading .log files into a normalized CSV dataset.

    Each scoring event consists of:

        [SCORING] SYMBOL TIMEFRAME | component=value | ...
        [SCORING] Weighted Score=... | BUY>=... | SELL<=... -> DECISION

    The component line must appear before the weighted-score line.
    """

    def __init__(self, input_dir: Path) -> None:
        self.input_dir = input_dir

    @staticmethod
    def parse_components(component_text: str) -> dict[str, float]:
        components: dict[str, float] = {}

        for match in COMPONENT_RE.finditer(component_text):
            name = match.group("name")
            value = float(match.group("value"))
            components[name] = value

        return components

    def parse_file(self, path: Path) -> list[ScoringRecord]:
        records: list[ScoringRecord] = []
        pending: Optional[PendingScoring] = None

        try:
            with path.open("r", encoding="utf-8", errors="replace") as file:
                for line_number, raw_line in enumerate(file, start=1):
                    line = raw_line.strip()

                    if not line:
                        continue

                    # ------------------------------------------------------
                    # Component/scoring line
                    # ------------------------------------------------------
                    scoring_match = SCORING_LINE_RE.match(line)

                    if scoring_match:
                        components = self.parse_components(
                            scoring_match.group("components")
                        )

                        # Only treat it as a pending component event if
                        # actual component=value entries were found.
                        if components:
                            pending = PendingScoring(
                                timestamp=scoring_match.group("timestamp"),
                                level=scoring_match.group("level"),
                                symbol=scoring_match.group("symbol"),
                                timeframe=scoring_match.group("timeframe"),
                                components=components,
                                source_file=path.name,
                                line_number=line_number,
                            )

                        continue

                    # ------------------------------------------------------
                    # Weighted score line
                    # ------------------------------------------------------
                    weighted_match = WEIGHTED_LINE_RE.match(line)

                    if weighted_match:
                        # A weighted score without a preceding component line
                        # cannot be reliably associated with an indicator set.
                        if pending is None:
                            continue

                        record = ScoringRecord(
                            timestamp=pending.timestamp,
                            symbol=pending.symbol,
                            timeframe=pending.timeframe,
                            weighted_score=float(weighted_match.group("weighted")),
                            buy_threshold=float(weighted_match.group("buy")),
                            sell_threshold=float(weighted_match.group("sell")),
                            decision=weighted_match.group("decision"),
                            source_file=pending.source_file,
                            source_line=line_number,
                            components=pending.components.copy(),
                        )

                        records.append(record)

                        # Important:
                        # Prevent an old component line from accidentally
                        # being associated with a later weighted-score line.
                        pending = None

        except OSError as exc:
            print(
                f"[ERROR] Failed to read {path}: {exc}",
                file=sys.stderr,
            )

        return records

    def analyze(self) -> list[ScoringRecord]:
        if not self.input_dir.exists():
            raise FileNotFoundError(
                f"Input directory does not exist: {self.input_dir}"
            )

        if not self.input_dir.is_dir():
            raise NotADirectoryError(
                f"Input path is not a directory: {self.input_dir}"
            )

        log_files = sorted(self.input_dir.glob("*.log"))

        if not log_files:
            print(
                f"[WARNING] No .log files found in {self.input_dir}",
                file=sys.stderr,
            )
            return []

        all_records: list[ScoringRecord] = []

        for log_file in log_files:
            print(f"[READ] {log_file}")

            file_records = self.parse_file(log_file)

            print(
                f"[READ] {log_file.name}: "
                f"{len(file_records)} scoring records"
            )

            all_records.extend(file_records)

        all_records.sort(
            key=lambda record: datetime.strptime(
                record.timestamp,
                "%Y-%m-%d %H:%M:%S",
            )
        )

        return all_records


# ---------------------------------------------------------------------------
# CSV exporter
# ---------------------------------------------------------------------------

class CsvExporter:
    """
    Export heterogeneous scoring records into one wide CSV.

    Since different strategies use different component names, the exporter
    discovers every component used across all records and creates a column
    for each one.
    """

    BASE_COLUMNS = [
        "timestamp",
        "symbol",
        "timeframe",
        "weighted_score",
        "buy_threshold",
        "sell_threshold",
        "decision",
        "source_file",
        "source_line",
    ]

    def export(
        self,
        records: list[ScoringRecord],
        output_path: Path,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Discover all component names used in all files.
        component_names: set[str] = set()

        for record in records:
            component_names.update(record.components.keys())

        component_columns = sorted(component_names)

        fieldnames = self.BASE_COLUMNS + component_columns

        with output_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as csv_file:

            writer = csv.DictWriter(
                csv_file,
                fieldnames=fieldnames,
                extrasaction="ignore",
            )

            writer.writeheader()

            for record in records:
                row: dict[str, object] = {
                    "timestamp": record.timestamp,
                    "symbol": record.symbol,
                    "timeframe": record.timeframe,
                    "weighted_score": record.weighted_score,
                    "buy_threshold": record.buy_threshold,
                    "sell_threshold": record.sell_threshold,
                    "decision": record.decision,
                    "source_file": record.source_file,
                    "source_line": record.source_line,
                }

                for component_name in component_columns:
                    row[component_name] = record.components.get(
                        component_name,
                        "",
                    )

                writer.writerow(row)

        print(f"[WRITE] {output_path}")
        print(f"[WRITE] Records: {len(records)}")
        print(f"[WRITE] Components: {len(component_columns)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze trading scoring .log files and combine them into "
            "one CSV dataset."
        )
    )

    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=Path("analytics"),
        help=(
            "Directory containing .log files "
            "(default: analytics)"
        ),
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("analytics/data/scoring_analysis.csv"),
        help=(
            "Output CSV path "
            "(default: analytics/data/scoring_analysis.csv)"
        ),
    )

    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()

    analyzer = LogAnalyzer(args.input)

    try:
        records = analyzer.analyze()
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if not records:
        print("[INFO] No scoring records found.")
        return 0

    exporter = CsvExporter()

    try:
        exporter.export(records, args.output)
    except OSError as exc:
        print(
            f"[ERROR] Failed to write CSV: {exc}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())