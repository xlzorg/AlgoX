
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


DEFAULT_INPUT = Path("analytics/data/scoring_analysis.csv")
DEFAULT_OUTPUT = Path("analytics/data/decision_matrix.csv")


def load_data(input_path: Path) -> pd.DataFrame:
    """Load the normalized scoring CSV."""

    if not input_path.exists():
        raise FileNotFoundError(
            f"Input CSV does not exist: {input_path}"
        )

    df = pd.read_csv(input_path)

    required_columns = {
        "timestamp",
        "symbol",
        "timeframe",
        "decision",
        "source_file",
        "source_line",
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(
            f"Missing required columns: {sorted(missing)}"
        )

    return df


def prepare_decision_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Create a sequential decision index independently for each source file.

    Each source file receives:

        1, 2, 3, 4, ...

    representing the order of scoring events in that file.
    """

    # Make sure chronological ordering is correct first.
    df = df.copy()

    df["_timestamp"] = pd.to_datetime(
        df["timestamp"],
        errors="coerce",
    )

    df = df.sort_values(
        by=[
            "source_file",
            "_timestamp",
            "source_line",
        ],
        kind="stable",
    )

    # Sequential index per source file.
    df["decision_index"] = (
        df.groupby("source_file")
        .cumcount()
        + 1
    )

    return df


def create_decision_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert long-form scoring data into a decision comparison matrix.

    Example:

        decision_index | bot_a.log | bot_b.log | bot_c.log
        --------------------------------------------------
        1              | BUY       | HOLD      | BUY
        2              | HOLD      | BUY       | BUY
        3              | SELL      | SELL      | HOLD
    """

    # Pivot source files into columns.
    matrix = df.pivot_table(
        index="decision_index",
        columns="source_file",
        values="decision",
        aggfunc="first",
    )

    # Remove pandas column-index name.
    matrix.columns.name = None

    matrix = matrix.sort_index()

    # ------------------------------------------------------------------
    # Decision statistics
    # ------------------------------------------------------------------

    decision_values = matrix.fillna("")

    matrix["BUY_count"] = (
        decision_values == "BUY"
    ).sum(axis=1)

    matrix["SELL_count"] = (
        decision_values == "SELL"
    ).sum(axis=1)

    matrix["HOLD_count"] = (
        decision_values == "HOLD"
    ).sum(axis=1)

    total_files = len(
        [
            column
            for column in matrix.columns
            if column
            not in {
                "BUY_count",
                "SELL_count",
                "HOLD_count",
            }
        ]
    )

    # Determine consensus.
    def determine_consensus(row: pd.Series) -> str:
        counts = {
            "BUY": row["BUY_count"],
            "SELL": row["SELL_count"],
            "HOLD": row["HOLD_count"],
        }

        highest = max(counts.values())

        if highest == 0:
            return "NO_DATA"

        winners = [
            decision
            for decision, count in counts.items()
            if count == highest
        ]

        if len(winners) > 1:
            return "MIXED"

        return winners[0]

    matrix["consensus"] = matrix.apply(
        determine_consensus,
        axis=1,
    )

    # Ratio of files agreeing with the consensus.
    matrix["consensus_ratio"] = (
        matrix[
            [
                "BUY_count",
                "SELL_count",
                "HOLD_count",
            ]
        ]
        .max(axis=1)
        .div(total_files)
    )

    # ------------------------------------------------------------------
    # Reorder columns
    # ------------------------------------------------------------------

    source_columns = [
        column
        for column in matrix.columns
        if column
        not in {
            "BUY_count",
            "SELL_count",
            "HOLD_count",
            "consensus",
            "consensus_ratio",
        }
    ]

    matrix = matrix[
        source_columns
        + [
            "BUY_count",
            "SELL_count",
            "HOLD_count",
            "consensus",
            "consensus_ratio",
        ]
    ]

    matrix = matrix.reset_index()

    return matrix


def create_metadata_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """
    Create a secondary matrix containing useful metadata for each
    decision index.

    This helps identify what timestamp/symbol the aligned decisions
    correspond to.
    """

    metadata = (
        df.sort_values(
            [
                "decision_index",
                "source_file",
            ]
        )
        .groupby("decision_index")
        .agg(
            timestamp=("timestamp", "first"),
            symbol=("symbol", "first"),
            timeframe=("timeframe", "first"),
        )
        .reset_index()
    )

    return metadata


def export_matrix(
    matrix: pd.DataFrame,
    metadata: pd.DataFrame,
    output_path: Path,
) -> None:
    """Write the final decision matrix to CSV."""

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    result = metadata.merge(
        matrix,
        on="decision_index",
        how="right",
    )

    result.to_csv(
        output_path,
        index=False,
    )

    print(f"[WRITE] {output_path}")
    print(f"[WRITE] Rows: {len(result)}")
    print(
        f"[WRITE] Source files: "
        f"{matrix.shape[1] - 6}"
    )


def print_summary(matrix: pd.DataFrame) -> None:
    """Print a useful summary to the terminal."""

    print()
    print("=" * 70)
    print("DECISION MATRIX SUMMARY")
    print("=" * 70)

    if "consensus" in matrix.columns:
        consensus_counts = (
            matrix["consensus"]
            .value_counts()
        )

        print()
        print("Consensus:")
        for decision, count in consensus_counts.items():
            print(f"  {decision:<8}: {count}")

    if "consensus_ratio" in matrix.columns:
        print()
        print("Consensus ratio:")
        print(
            f"  100% : "
            f"{(matrix['consensus_ratio'] == 1.0).sum()}"
        )
        print(
            f"  >=75%: "
            f"{(matrix['consensus_ratio'] >= 0.75).sum()}"
        )
        print(
            f"  >=50%: "
            f"{(matrix['consensus_ratio'] >= 0.50).sum()}"
        )

    print("=" * 70)
    print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a BUY/SELL/HOLD comparison matrix "
            "from scoring_analysis.csv."
        )
    )

    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=(
            "Input scoring CSV "
            "(default: analytics/data/scoring_analysis.csv)"
        ),
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=(
            "Output decision matrix CSV "
            "(default: analytics/data/decision_matrix.csv)"
        ),
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        # --------------------------------------------------------------
        # Load
        # --------------------------------------------------------------
        print(f"[READ] {args.input}")

        df = load_data(args.input)

        print(
            f"[READ] Records: {len(df)}"
        )

        print(
            f"[READ] Source files: "
            f"{df['source_file'].nunique()}"
        )

        # --------------------------------------------------------------
        # Build sequential indexes
        # --------------------------------------------------------------
        df = prepare_decision_index(df)

        # --------------------------------------------------------------
        # Create matrix
        # --------------------------------------------------------------
        matrix = create_decision_matrix(df)

        # --------------------------------------------------------------
        # Metadata
        # --------------------------------------------------------------
        metadata = create_metadata_matrix(df)

        # --------------------------------------------------------------
        # Export
        # --------------------------------------------------------------
        export_matrix(
            matrix=matrix,
            metadata=metadata,
            output_path=args.output,
        )

        # --------------------------------------------------------------
        # Summary
        # --------------------------------------------------------------
        print_summary(matrix)

    except FileNotFoundError as exc:
        print(
            f"[ERROR] {exc}",
            file=sys.stderr,
        )
        return 1

    except ValueError as exc:
        print(
            f"[ERROR] {exc}",
            file=sys.stderr,
        )
        return 1

    except Exception as exc:
        print(
            f"[ERROR] Unexpected error: {exc}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
