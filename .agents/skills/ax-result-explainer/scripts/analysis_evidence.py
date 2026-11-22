"""Produce deterministic evidence for the ax-result-explainer skill."""
from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

from summary import (
    _estimate_hv_convergence_trial,
    _safe_float,
    build_dataset_summary,
    load_settings,
    load_summary_rows,
)


def hypervolume(points: list[tuple[float, ...]], dimensions: int) -> float:
    """Union volume of boxes from the origin to positive maximization points."""
    if not points:
        return 0.0
    if dimensions == 1:
        return max(point[0] for point in points)
    levels = sorted({point[0] for point in points})
    result, previous = 0.0, 0.0
    for level in levels:
        cross_section = [point[1:] for point in points if point[0] >= level]
        result += (level - previous) * hypervolume(cross_section, dimensions - 1)
        previous = level
    return result


def print_sobol(settings, rows, snapshot: Path) -> None:
    print("\n[sobol_sensitivity]")
    if not snapshot.is_file():
        print(f"unavailable=snapshot not found: {snapshot}")
        return
    try:
        import torch
        from ax.adapter.torch import TorchAdapter
        from ax.api.client import Client
        from ax.utils.sensitivity.sobol_measures import ax_parameter_sens

        client = Client.load_from_json_file(filepath=str(snapshot))
        snapshot_rows = client.summarize().to_dict("records")
        by_trial = {int(row["trial_index"]): row for row in snapshot_rows
                    if str(row["trial_status"]).upper() == "COMPLETED"}
        if len(by_trial) != len(rows):
            raise ValueError("snapshot and CSV have different completed trial counts")
        names = [p.name for p in settings.parameters] + [o.name for o in settings.objectives]
        for row in rows:
            other = by_trial.get(int(row["trial_index"]))
            if other is None or any(
                _safe_float(str(row.get(name, ""))) is None
                or _safe_float(str(other.get(name, ""))) is None
                or not math.isclose(float(row[name]), float(other[name]), rel_tol=1e-7, abs_tol=1e-9)
                for name in names
            ):
                raise ValueError("snapshot and CSV trial values do not match")
        adapter = client._generation_strategy.fit(experiment=client._experiment)
        if not isinstance(adapter, TorchAdapter):
            raise ValueError("the current generation node has no fitted GP model")
        torch.manual_seed(123)
        result = ax_parameter_sens(adapter, metrics=[o.name for o in settings.objectives],
                                   order="first", signed=True)
        print(f"snapshot={snapshot}")
        print("signed first-order Sobol indices; sign = average model gradient of the raw metric")
        for metric, values in result.items():
            print(metric + ": " + ", ".join(
                f"{name}={float(value):+.4f}" for name, value in values.items()
            ))
    except Exception as exc:
        print(f"unavailable={type(exc).__name__}: {exc}")


def find_data_directory(current_dir: Path, settings_name: str, summary_name: str) -> Path:
    def has_inputs(directory: Path) -> bool:
        return (directory / settings_name).is_file() and (directory / summary_name).is_file()

    if has_inputs(current_dir):
        return current_dir

    results_dir = current_dir if current_dir.name == "results" else current_dir / "results"
    if not results_dir.is_dir():
        return current_dir

    completed_runs = (
        (int(match[1]), entry)
        for entry in results_dir.iterdir()
        if (match := re.fullmatch(r"result_([1-9][0-9]*)", entry.name)) and has_inputs(entry)
    )
    fallback_dir = results_dir if has_inputs(results_dir) else current_dir
    return max(completed_runs, default=(0, fallback_dir))[1]


def main() -> None:
    settings_name = "ax_optimization_settings.json"
    summary_name = "ax_summary.csv"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--snapshot", type=Path, help="Ax Client snapshot; defaults to the summary directory")
    parser.add_argument("--no-sobol", action="store_true", help="skip model fitting and Sobol analysis")
    args = parser.parse_args()
    data_dir = Path.cwd()
    if args.settings is None and args.summary is None:
        data_dir = find_data_directory(data_dir, settings_name, summary_name)
    settings_path = args.settings or data_dir / settings_name
    summary_path = args.summary or data_dir / summary_name
    settings = load_settings(settings_path)
    rows = load_summary_rows(summary_path)
    completed = [row for row in rows if row.get("trial_status", "").upper() == "COMPLETED"]
    complete_values = [row for row in completed if all(
        _safe_float(str(row.get(obj.name, ""))) is not None for obj in settings.objectives
    )]
    print(f"[input] settings={settings_path} summary={summary_path}")
    print(f"total_rows={len(rows)} completed_rows={len(completed)} complete_objective_rows={len(complete_values)}")
    print(build_dataset_summary(settings, complete_values))

    objectives = settings.objectives
    print("\n[hypervolume_trend]")
    if not objectives or any(obj.threshold is None or not math.isfinite(obj.threshold) for obj in objectives):
        print("unavailable=all objective thresholds must be finite")
        return
    points: list[tuple[float, ...]] = []
    values: list[tuple[int, float]] = []
    for row in sorted(complete_values, key=lambda r: int(r["trial_index"])):
        point = tuple(
            (float(row[obj.name]) - obj.threshold) * (1 if obj.direction == "maximize" else -1)
            for obj in objectives
        )
        if all(value > 0 for value in point):
            points.append(point)
        idx = int(row["trial_index"])
        hv = hypervolume(points, len(objectives))
        values.append((idx, hv))
        print(f"trial={idx}, hypervolume={hv:.8g}")
    if values:
        print(f"final_hypervolume={values[-1][1]:.8g}")
        if values[-1][1] > 0:
            print(f"first_trial_at_99pct_of_final={_estimate_hv_convergence_trial(values)}")
        else:
            print("first_trial_at_99pct_of_final=undefined (final hypervolume is zero)")
    else:
        print("unavailable=no completed rows with all objectives")
    if not args.no_sobol:
        print_sobol(settings, complete_values, args.snapshot or summary_path.with_name("ax_client_snapshot.json"))


if __name__ == "__main__":
    main()
