from __future__ import annotations

import csv
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

HV_CONVERGENCE_REL_EPS = 0.01


@dataclass
class ParameterDef:
    name: str
    ptype: str
    min_value: float
    max_value: float


@dataclass
class ObjectiveDef:
    name: str
    direction: str
    threshold: float | None


@dataclass
class OptimizationSettings:
    parameters: list[ParameterDef]
    objectives: list[ObjectiveDef]


def _safe_float(value: str) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return number


def load_settings(path: Path) -> OptimizationSettings:
    import json

    if not path.exists():
        raise FileNotFoundError(f"Settings file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Settings JSON root must be an object")

    params_raw = data.get("parameters")
    objs_raw = data.get("objectives")

    if not isinstance(params_raw, list) or not params_raw:
        raise ValueError("'parameters' must be a non-empty list")
    if not isinstance(objs_raw, list) or not objs_raw:
        raise ValueError("'objectives' must be a non-empty list")

    parameters: list[ParameterDef] = []
    for item in params_raw:
        if not isinstance(item, dict):
            raise ValueError("Each parameter entry must be an object")
        name = item.get("name")
        ptype = item.get("parameter_type", "unknown")
        search_range = item.get("search_range")
        if not isinstance(name, str) or not name:
            raise ValueError("Parameter 'name' must be a non-empty string")
        if not isinstance(search_range, dict):
            raise ValueError(f"Parameter '{name}' must have 'search_range' object")
        min_value = _safe_float(str(search_range.get("min", "")))
        max_value = _safe_float(str(search_range.get("max", "")))
        if min_value is None or max_value is None:
            raise ValueError(f"Parameter '{name}' has invalid min/max")
        parameters.append(
            ParameterDef(name=name, ptype=str(ptype), min_value=min_value, max_value=max_value)
        )

    objectives: list[ObjectiveDef] = []
    for item in objs_raw:
        if not isinstance(item, dict):
            raise ValueError("Each objective entry must be an object")
        name = item.get("name")
        direction = str(item.get("direction", "maximize")).strip().lower()
        if direction not in {"maximize", "minimize"}:
            raise ValueError(
                f"Objective '{name}' has invalid direction '{direction}' "
                "(expected maximize/minimize)"
            )
        if not isinstance(name, str) or not name:
            raise ValueError("Objective 'name' must be a non-empty string")
        threshold = None
        if "threshold" in item and item.get("threshold") is not None:
            threshold = _safe_float(str(item.get("threshold")))
            if threshold is None:
                raise ValueError(f"Objective '{name}' has invalid threshold")
        objectives.append(ObjectiveDef(name=name, direction=direction, threshold=threshold))

    return OptimizationSettings(parameters=parameters, objectives=objectives)


def load_summary_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Summary CSV file not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        raise ValueError("Summary CSV is empty")
    return rows


def _is_better(value: float, best: float, direction: str) -> bool:
    return value > best if direction == "maximize" else value < best


def _pearson_correlation(xs: list[float], ys: list[float]) -> float | None:
    """Compute Pearson correlation coefficient. Returns None if insufficient data."""
    n = len(xs)
    if n < 3:
        return None
    mean_x = mean(xs)
    mean_y = mean(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = sum((x - mean_x) ** 2 for x in xs) ** 0.5
    den_y = sum((y - mean_y) ** 2 for y in ys) ** 0.5
    if den_x < 1e-12 or den_y < 1e-12:
        return None
    return max(-1.0, min(1.0, num / (den_x * den_y)))


def _objective_goodness(value: float, lo: float, hi: float, direction: str) -> float:
    """Normalize objective value to [0, 1] where 1 is best."""
    span = hi - lo
    if span <= 1e-12:
        return 0.5
    if direction == "maximize":
        return (value - lo) / span
    return (hi - value) / span


def _tradeoff_label(r: float) -> str:
    """Return a human-readable relationship label for a Pearson r value."""
    if r >= 0.7:
        return "strong_trade_on"
    if r >= 0.3:
        return "moderate_trade_on"
    if r > -0.3:
        return "neutral"
    if r > -0.7:
        return "moderate_trade_off"
    return "strong_trade_off"


def build_dataset_summary(settings: OptimizationSettings, rows: list[dict[str, str]]) -> str:
    objective_names = [o.name for o in settings.objectives]
    parameter_names = [p.name for p in settings.parameters]

    total_trials = len(rows)
    completed_trials = sum(1 for r in rows if str(r.get("trial_status", "")).upper() == "COMPLETED")
    node_counter = Counter(str(r.get("generation_node", "unknown")) for r in rows)

    lines: list[str] = []
    lines.append("[experiment]")
    lines.append(f"total_trials={total_trials}")
    lines.append(f"completed_trials={completed_trials}")
    lines.append("generation_nodes=" + ", ".join(f"{k}:{v}" for k, v in node_counter.items()))
    lines.append("")

    lines.append("[search_space]")
    for p in settings.parameters:
        lines.append(
            f"{p.name}: type={p.ptype}, min={p.min_value:.6g}, max={p.max_value:.6g}"
        )
    lines.append("")

    lines.append("[objectives]")
    objective_values: dict[str, list[tuple[int, float, dict[str, str]]]] = {name: [] for name in objective_names}
    for row in rows:
        idx = int(float(row.get("trial_index", "0") or 0))
        for name in objective_names:
            value = _safe_float(str(row.get(name, "")))
            if value is not None:
                objective_values[name].append((idx, value, row))

    for obj in settings.objectives:
        vals = objective_values[obj.name]
        threshold_text = "none" if obj.threshold is None else f"{obj.threshold:.6g}"
        if not vals:
            lines.append(
                f"{obj.name}: direction={obj.direction}, threshold={threshold_text}, no_data=true"
            )
            continue
        numbers = [v for _, v, _ in vals]
        best_idx, best_val, best_row = vals[0]
        for idx, val, row in vals[1:]:
            if _is_better(val, best_val, obj.direction):
                best_idx, best_val, best_row = idx, val, row

        lines.append(
            f"{obj.name}: direction={obj.direction}, threshold={threshold_text}, "
            f"best_trial={best_idx}, best_value={best_val:.6g}"
        )

        param_snapshot = ", ".join(
            f"{pn}={_safe_float(str(best_row.get(pn, ""))) if _safe_float(str(best_row.get(pn, ""))) is not None else best_row.get(pn, '')}"
            for pn in parameter_names
        )
        lines.append(f"{obj.name}_best_trial_params: {param_snapshot}")
    lines.append("")

    # Balanced ranking across all objectives using normalized score.
    objective_ranges: dict[str, tuple[float, float]] = {}
    for obj in settings.objectives:
        vals = [v for _, v, _ in objective_values[obj.name]]
        if vals:
            objective_ranges[obj.name] = (min(vals), max(vals))

    scored_rows: list[tuple[float, dict[str, str]]] = []
    for row in rows:
        score_parts: list[float] = []
        for obj in settings.objectives:
            value = _safe_float(str(row.get(obj.name, "")))
            if value is None:
                continue
            lo, hi = objective_ranges.get(obj.name, (value, value))
            span = hi - lo
            if span <= 1e-12:
                norm = 0.5
            elif obj.direction == "maximize":
                norm = (value - lo) / span
            else:
                norm = (hi - value) / span
            score_parts.append(max(0.0, min(1.0, norm)))
        if score_parts:
            scored_rows.append((mean(score_parts), row))

    scored_rows.sort(key=lambda item: item[0], reverse=True)
    top_k = scored_rows[: min(5, len(scored_rows))]
    lines.append("[top_balanced_trials]")
    for rank, (score, row) in enumerate(top_k, start=1):
        idx = row.get("trial_index", "?")
        obj_values = ", ".join(f"{n}={row.get(n, 'NA')}" for n in objective_names)
        params = ", ".join(f"{n}={row.get(n, 'NA')}" for n in parameter_names)
        lines.append(
            f"rank={rank}, trial_index={idx}, score={score:.4f}, objectives=[{obj_values}], params=[{params}]"
        )

    if top_k:
        lines.append("")
        lines.append("[top_trial_parameter_center]")
        for pn in parameter_names:
            values: list[float] = []
            for _, row in top_k:
                v = _safe_float(str(row.get(pn, "")))
                if v is not None:
                    values.append(v)
            if values:
                lines.append(f"{pn}: mean={mean(values):.6g}, min={min(values):.6g}, max={max(values):.6g}")

    # Pairwise trade-off / trade-on analysis across all objective combinations.
    if len(settings.objectives) >= 2:
        lines.append("")
        lines.append("[objective_relationships]")
        lines.append(
            "# Pearson correlation of 'goodness' scores (1=best, 0=worst) for each objective pair."
        )
        lines.append(
            "# Positive r → trade-on (synergy): improving one tends to improve the other."
        )
        lines.append(
            "# Negative r → trade-off: improving one tends to worsen the other."
        )
        for i, obj_a in enumerate(settings.objectives):
            for obj_b in settings.objectives[i + 1 :]:
                vals_a = objective_values[obj_a.name]
                vals_b = objective_values[obj_b.name]
                # Align by trial index.
                idx_to_val_a = {idx: v for idx, v, _ in vals_a}
                idx_to_val_b = {idx: v for idx, v, _ in vals_b}
                common_indices = sorted(set(idx_to_val_a) & set(idx_to_val_b))
                if len(common_indices) < 3:
                    lines.append(
                        f"{obj_a.name} vs {obj_b.name}: insufficient_data (n={len(common_indices)})"
                    )
                    continue
                lo_a, hi_a = objective_ranges.get(obj_a.name, (0.0, 1.0))
                lo_b, hi_b = objective_ranges.get(obj_b.name, (0.0, 1.0))
                goodness_a = [
                    _objective_goodness(idx_to_val_a[idx], lo_a, hi_a, obj_a.direction)
                    for idx in common_indices
                ]
                goodness_b = [
                    _objective_goodness(idx_to_val_b[idx], lo_b, hi_b, obj_b.direction)
                    for idx in common_indices
                ]
                r = _pearson_correlation(goodness_a, goodness_b)
                if r is None:
                    lines.append(
                        f"{obj_a.name} vs {obj_b.name}: correlation_undefined (n={len(common_indices)})"
                    )
                    continue
                label = _tradeoff_label(r)
                lines.append(
                    f"{obj_a.name} vs {obj_b.name}: r={r:.4f}, relationship={label}, n={len(common_indices)}"
                )

    return "\n".join(lines)


def _estimate_hv_convergence_trial(
    hv_by_trial: list[tuple[int, float]],
    rel_eps: float = HV_CONVERGENCE_REL_EPS,
) -> int | None:
    """Return earliest trial where HV reaches near-final value within rel_eps.

    Convergence is defined as first trial t where hv(t) >= final_hv * (1 - rel_eps).
    """
    if not hv_by_trial:
        return None
    final_hv = hv_by_trial[-1][1]
    if final_hv <= 0:
        return hv_by_trial[-1][0]
    threshold = final_hv * (1.0 - rel_eps)
    for trial_idx, hv in hv_by_trial:
        if hv >= threshold:
            return trial_idx
    return hv_by_trial[-1][0]
