from __future__ import annotations

import argparse
import csv
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

try:
    import ollama
except ImportError:
    ollama = None  # type: ignore[assignment]


DEFAULT_MODEL = "qwen3.5"
DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_SETTINGS = "ax_optimization_settings.json"
DEFAULT_SUMMARY = "ax_summary.csv"
DEFAULT_OUTPUT = "ax_summary_explanation_ja.md"
DEFAULT_SNAPSHOT = "ax_client_snapshot.json"
# Pearson r threshold below which a pair is treated as a trade-off for Sobol analysis
SOBOL_TRADEOFF_THRESHOLD = -0.3
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


@dataclass
class OllamaConfig:
    host: str
    model: str
    timeout_sec: int = 600
    temperature: float = 0.2
    max_tokens: int = 4096
    use_thinking: bool = False
    repeat_penalty: float = 1.1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a Japanese explanation for completed Ax optimization results "
            "using ollama-python qwen3.5."
        )
    )
    parser.add_argument(
        "--settings",
        type=Path,
        default=Path(__file__).with_name(DEFAULT_SETTINGS),
        help="Path to optimization settings JSON",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path(__file__).with_name(DEFAULT_SUMMARY),
        help="Path to optimization summary CSV",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name(DEFAULT_OUTPUT),
        help="Path to output Markdown file",
    )
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Ollama model name")
    parser.add_argument("--host", type=str, default=DEFAULT_HOST, help="Ollama host URL")
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=600,
        help="Timeout in seconds for Ollama requests",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Sampling temperature",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4096,
        help="Maximum generated tokens",
    )
    parser.add_argument(
        "--thinking",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable qwen thinking mode",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path(__file__).with_name(DEFAULT_SNAPSHOT),
        help=(
            "Path to ax_client_snapshot.json used for signed Sobol sensitivity analysis. "
            "If the file does not exist, the Sobol section is skipped."
        ),
    )
    parser.add_argument(
        "--no-sobol",
        action="store_true",
        default=False,
        help="Skip signed Sobol sensitivity analysis even if snapshot is available.",
    )
    return parser.parse_args()


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


def build_sobol_section(
    settings: OptimizationSettings,
    rows: list[dict[str, str]],
    snapshot_path: Path,
) -> str:
    """Compute signed first-order Sobol sensitivity indices for objective pairs that are
    in trade-off relationship (Pearson r < SOBOL_TRADEOFF_THRESHOLD).

    Requires a fitted TorchAdapter loaded from *snapshot_path* (ax_client_snapshot.json).
    Returns a formatted ``[sobol_sensitivity]`` section string suitable for appending to
    the dataset summary, including a diagnostic message when analysis is unavailable.
    """
    # ---- Identify trade-off pairs from raw data --------------------------------
    objective_names = [o.name for o in settings.objectives]
    obj_idx_vals: dict[str, list[tuple[int, float]]] = {n: [] for n in objective_names}
    for row in rows:
        trial_idx = int(float(row.get("trial_index", "0") or 0))
        for name in objective_names:
            v = _safe_float(str(row.get(name, "")))
            if v is not None:
                obj_idx_vals[name].append((trial_idx, v))

    obj_ranges: dict[str, tuple[float, float]] = {}
    for obj in settings.objectives:
        vals = [v for _, v in obj_idx_vals[obj.name]]
        if vals:
            obj_ranges[obj.name] = (min(vals), max(vals))

    tradeoff_pairs: list[tuple[ObjectiveDef, ObjectiveDef]] = []
    for i, obj_a in enumerate(settings.objectives):
        for obj_b in settings.objectives[i + 1 :]:
            map_a = {idx: v for idx, v in obj_idx_vals[obj_a.name]}
            map_b = {idx: v for idx, v in obj_idx_vals[obj_b.name]}
            common = sorted(set(map_a) & set(map_b))
            if len(common) < 3:
                continue
            lo_a, hi_a = obj_ranges.get(obj_a.name, (0.0, 1.0))
            lo_b, hi_b = obj_ranges.get(obj_b.name, (0.0, 1.0))
            ga = [_objective_goodness(map_a[idx], lo_a, hi_a, obj_a.direction) for idx in common]
            gb = [_objective_goodness(map_b[idx], lo_b, hi_b, obj_b.direction) for idx in common]
            r = _pearson_correlation(ga, gb)
            if r is not None and r < SOBOL_TRADEOFF_THRESHOLD:
                tradeoff_pairs.append((obj_a, obj_b))

    if not tradeoff_pairs:
        return "[sobol_sensitivity]\nno_tradeoff_pairs_found=true"

    pair_labels = ", ".join(f"{a.name} vs {b.name}" for a, b in tradeoff_pairs)

    # ---- Load Ax dependencies (optional) ---------------------------------------
    try:
        from ax.service.ax_client import AxClient  # noqa: PLC0415
        from ax.adapter.torch import TorchAdapter  # noqa: PLC0415
        from ax.utils.sensitivity.sobol_measures import ax_parameter_sens as _ax_param_sens  # noqa: PLC0415
    except ImportError:
        return (
            "[sobol_sensitivity]\n"
            f"tradeoff_pairs={pair_labels}\n"
            "ax_not_available=true (install ax-platform to enable Sobol analysis)"
        )

    if not snapshot_path.exists():
        return (
            "[sobol_sensitivity]\n"
            f"tradeoff_pairs={pair_labels}\n"
            f"snapshot_not_found={snapshot_path}"
        )

    # ---- Load snapshot and fit model -------------------------------------------
    # Load JSON manually so we can inject legacy keys that may be absent in older
    # snapshots (e.g. '_enforce_sequential_optimization' added in a later Ax version).
    import json as _json  # noqa: PLC0415

    try:
        raw_snapshot = _json.loads(snapshot_path.read_text(encoding="utf-8"))
        raw_snapshot.setdefault("_enforce_sequential_optimization", True)
        ax_client = AxClient.from_json_snapshot(raw_snapshot)
    except Exception as exc:  # noqa: BLE001
        return (
            "[sobol_sensitivity]\n"
            f"tradeoff_pairs={pair_labels}\n"
            f"load_failed={exc}"
        )

    # Try to find an already-fitted TorchAdapter across all generation nodes first,
    # then fall back to re-fitting the current node.
    adapter = None
    try:
        for node in ax_client.generation_strategy._nodes:
            candidate = node._fitted_adapter
            if isinstance(candidate, TorchAdapter):
                adapter = candidate
                break
    except Exception:  # noqa: BLE001
        pass

    if adapter is None:
        try:
            ax_client.fit_model()
            candidate = ax_client.generation_strategy._curr._fitted_adapter
            if isinstance(candidate, TorchAdapter):
                adapter = candidate
        except Exception as exc:  # noqa: BLE001
            return (
                "[sobol_sensitivity]\n"
                f"tradeoff_pairs={pair_labels}\n"
                f"fit_failed={exc}"
            )

    if not isinstance(adapter, TorchAdapter):
        return (
            "[sobol_sensitivity]\n"
            f"tradeoff_pairs={pair_labels}\n"
            "adapter_not_torch=true (no fitted GP-based TorchAdapter found in generation nodes)"
        )

    # ---- Run signed Sobol sensitivity ------------------------------------------
    tradeoff_metrics = sorted({obj.name for pair in tradeoff_pairs for obj in pair})
    signed_ok = True
    try:
        sens: dict[str, Any] = _ax_param_sens(
            adapter, metrics=tradeoff_metrics, order="first", signed=True
        )
    except Exception:  # noqa: BLE001
        signed_ok = False
        try:
            sens = _ax_param_sens(
                adapter, metrics=tradeoff_metrics, order="first", signed=False
            )
        except Exception as exc:  # noqa: BLE001
            return (
                "[sobol_sensitivity]\n"
                f"tradeoff_pairs={pair_labels}\n"
                f"computation_failed={exc}"
            )

    # ---- Format output ---------------------------------------------------------
    lines: list[str] = ["[sobol_sensitivity]"]
    lines.append(
        f"# signed={'true' if signed_ok else 'false (unsigned fallback)'} "
        "first-order Sobol sensitivity indices."
    )
    lines.append("# Positive value: increasing this parameter tends to IMPROVE the metric.")
    lines.append("# Negative value: increasing this parameter tends to WORSEN the metric.")
    lines.append("# Magnitude: larger absolute value = stronger influence on that metric.")
    lines.append(f"# Analyzed trade-off pairs: {pair_labels}")
    lines.append("")

    for metric_name in tradeoff_metrics:
        param_sens = sens.get(metric_name)
        if param_sens is None:
            lines.append(f"{metric_name}: no_data")
            continue
        sorted_params = sorted(
            ((p, float(v)) for p, v in param_sens.items()),
            key=lambda kv: abs(kv[1]),
            reverse=True,
        )
        vals_str = ", ".join(f"{p}={v:+.4f}" for p, v in sorted_params)
        lines.append(f"{metric_name}: {vals_str}")

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


def build_hypervolume_section(rows: list[dict[str, str]], snapshot_path: Path) -> str:
    """Build [hypervolume_trend] using Ax hypervolume API by trial count."""
    completed_indices = sorted(
        {
            int(float(r.get("trial_index", "0") or 0))
            for r in rows
            if str(r.get("trial_status", "")).upper() == "COMPLETED"
        }
    )
    if not completed_indices:
        return "[hypervolume_trend]\nno_completed_trials=true"

    try:
        from ax.service.ax_client import AxClient  # noqa: PLC0415
    except ImportError:
        return "[hypervolume_trend]\nax_not_available=true"

    if not snapshot_path.exists():
        return f"[hypervolume_trend]\nsnapshot_not_found={snapshot_path}"

    import json as _json  # noqa: PLC0415

    try:
        raw_snapshot = _json.loads(snapshot_path.read_text(encoding="utf-8"))
        raw_snapshot.setdefault("_enforce_sequential_optimization", True)
        ax_client = AxClient.from_json_snapshot(raw_snapshot)
    except Exception as exc:  # noqa: BLE001
        return f"[hypervolume_trend]\nload_failed={exc}"

    hv_by_trial: list[tuple[int, float]] = []
    for t in completed_indices:
        try:
            hv = float(
                ax_client.get_hypervolume(
                    trial_indices=range(0, t + 1),
                    use_model_predictions=False,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return (
                "[hypervolume_trend]\n"
                f"computation_failed_at_trial={t}\n"
                f"error={exc}"
            )
        hv_by_trial.append((t, hv))

    convergence_trial = _estimate_hv_convergence_trial(hv_by_trial)
    final_hv = hv_by_trial[-1][1]
    best_hv = max(h for _, h in hv_by_trial)
    best_trial = max(hv_by_trial, key=lambda x: x[1])[0]

    lines = ["[hypervolume_trend]"]
    lines.append(
        "# observed hypervolume by completed-trial prefix using Ax get_hypervolume(use_model_predictions=False)"
    )
    for t, hv in hv_by_trial:
        lines.append(f"trial={t}, hypervolume={hv:.8g}")
    lines.append("")
    lines.append(f"final_hypervolume={final_hv:.8g}")
    lines.append(f"best_hypervolume={best_hv:.8g}")
    lines.append(f"best_hv_trial={best_trial}")
    lines.append(f"convergence_trial_rel1pct={convergence_trial}")
    lines.append(
        "convergence_definition=first_trial_with_hv_at_least_99pct_of_final_hv"
    )
    return "\n".join(lines)


def list_models(client: Any) -> list[str]:
    payload = client.list()
    models = payload.get("models", []) if isinstance(payload, dict) else getattr(payload, "models", [])

    names: list[str] = []
    for model in models or []:
        if isinstance(model, dict):
            name = model.get("name") or model.get("model")
        else:
            name = getattr(model, "name", None) or getattr(model, "model", None)
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _remove_repetition(text: str, window: int = 200, threshold: float = 0.85) -> str:
    if len(text) < window * 2:
        return text

    step = window // 2
    prev_chunk = text[:window]
    pos = window
    while pos + window <= len(text):
        current = text[pos : pos + window]
        same = sum(1 for a, b in zip(prev_chunk, current) if a == b)
        similarity = same / window
        if similarity >= threshold:
            cut = text.rfind("\n\n", 0, pos)
            if cut == -1:
                cut = text.rfind("\n", 0, pos)
            if cut == -1:
                cut = pos
            return text[:cut].rstrip()
        prev_chunk = current
        pos += step
    return text


def ask_ollama(client: Any, config: OllamaConfig, system: str, user: str) -> tuple[str, str]:
    response = client.chat(
        model=config.model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        think=config.use_thinking,
        options={
            "temperature": config.temperature,
            "num_predict": config.max_tokens,
            "repeat_penalty": config.repeat_penalty,
        },
    )

    message = response.get("message") if isinstance(response, dict) else getattr(response, "message", None)
    thinking = ""
    content = ""
    if isinstance(message, dict):
        thinking = str(message.get("thinking", "") or "")
        content = str(message.get("content", "") or "")
    elif message is not None:
        thinking = str(getattr(message, "thinking", "") or "")
        content = str(getattr(message, "content", "") or "")

    stop_tokens = ["<|endoftext|>", "<|im_end|>", "<|end|>", "</s>"]
    for token in stop_tokens:
        t_idx = thinking.find(token)
        if t_idx != -1:
            thinking = thinking[:t_idx]
        c_idx = content.find(token)
        if c_idx != -1:
            content = content[:c_idx]

    if not content.strip() and thinking.strip():
        match = re.search(r"(## .+)", thinking, re.DOTALL)
        content = match.group(1).strip() if match else thinking.strip()
        thinking = ""

    content = _remove_repetition(content.strip())
    if not content:
        raise RuntimeError("No valid text returned from Ollama")
    return thinking.strip(), content


def build_prompt(dataset_summary: str, settings: OptimizationSettings) -> tuple[str, str]:
    objective_names_str = ", ".join(o.name for o in settings.objectives)
    parameter_names_str = ", ".join(p.name for p in settings.parameters)
    obj_a = settings.objectives[0].name if settings.objectives else "A"
    obj_b = settings.objectives[1].name if len(settings.objectives) > 1 else "B"

    system = (
        "You are an expert in Bayesian optimization. "
        "Write in natural Japanese for engineers and use concrete numbers from the input. "
        "Do not invent unobserved values."
    )

    user = f"""
The following block describes executed Ax multi-objective optimization settings and summary statistics.

--- DATA START ---
{dataset_summary}
--- DATA END ---

Objective names: {objective_names_str}
Parameter names: {parameter_names_str}

Please generate a Japanese Markdown report with these required sections:
1. Experiment setting overview (parameters: {parameter_names_str}; objectives: {objective_names_str}, their directions, thresholds).
2. Result summary with key numbers (trial count, best values per objective, generation node trend).
3. Hypervolume trend and convergence analysis from [hypervolume_trend]:
     - Explain how hypervolume changed as trial count increased.
     - Identify which trial the optimization effectively converged based on
         convergence_trial_rel1pct and interpret whether improvement after that point
         is marginal or still meaningful.
4. Trade-off / trade-on analysis: For EVERY objective pair listed in [objective_relationships],
   state clearly whether it is a trade-off or trade-on, quantify the strength using the r value,
   and explain what this means in practice (e.g., "{obj_a} と {obj_b} は強いトレードオフ関係にある (r=-0.83)。
   {obj_a} を改善しようとすると {obj_b} が悪化する傾向が強い").
5. 正負符号付きSobol感度指標 for trade-off pairs (use [sobol_sensitivity] if present):
   - For each metric involved in a trade-off, list parameters ({parameter_names_str}) in
     descending absolute sensitivity order. Positive = increasing the parameter improves the
     metric; negative = decreasing it improves it.
   - Identify "conflict parameters" (opposite signs between the two trade-off metrics) and
     "synergy parameters" (same sign for both metrics and worth prioritizing).
   - If [sobol_sensitivity] shows no_tradeoff_pairs_found or a failure, explain concisely.
6. Balanced top trials interpretation and what the parameter ranges ({parameter_names_str}) imply.
7. Actionable recommendations for next optimization run (at least 3 concrete actions),
   incorporating the 正負符号付きSobol感度指標 findings where available.
   - For each trade-off pair, identify conflict parameters (opposite Sobol signs) and recommend
     changing the corresponding fixed experimental conditions (e.g., machining conditions, tool
     geometry) to relax the trade-off, rather than further tuning within the optimization loop.
   - Based on [sobol_sensitivity], identify parameters with negligibly small absolute sensitivity
     across ALL objectives; recommend removing them from the search space and fixing at a
     convenient value to reduce dimensionality without sacrificing result quality.
   - Identify parameters showing trade-on with ALL objective pairs (same sign for every metric)
     whose optimal value is already clear; recommend fixing them at that value and excluding
     from future runs to focus trials on the remaining uncertain dimensions.

Requirements:
- Focus on numerical interpretation using exact objective names ({objective_names_str}) and
  parameter names ({parameter_names_str}) throughout.
- Section 3: cite convergence_trial_rel1pct and final_hypervolume explicitly.
- Section 4: cover ALL pairs from [objective_relationships] with r value and relationship label.
- Section 5: label heading "正負符号付きSobol感度指標"; use exact names from [sobol_sensitivity].
- State any caveats or uncertainty clearly. Output only the Markdown body in Japanese.
""".strip()

    return system, user


def resolve_model_name(requested: str, available: list[str]) -> str | None:
    if requested in available:
        return requested
    req_base = requested.split(":")[0]
    for name in available:
        if name.split(":")[0] == req_base:
            return name
    return None


def main() -> int:
    args = parse_args()

    if ollama is None:
        print("[error] ollama-python is not installed. Run: pip install ollama")
        return 1

    try:
        settings = load_settings(args.settings)
        rows = load_summary_rows(args.summary)
    except Exception as exc:  # noqa: BLE001
        print(f"[error] failed to load input files: {exc}")
        return 1

    try:
        dataset_summary = build_dataset_summary(settings, rows)
    except Exception as exc:  # noqa: BLE001
        print(f"[error] failed to analyze summary data: {exc}")
        return 1

    try:
        hv_section = build_hypervolume_section(rows, args.snapshot)
        dataset_summary = dataset_summary + "\n\n" + hv_section
        if "computation_failed" in hv_section or "load_failed" in hv_section:
            print("[warn] hypervolume trend computation failed; diagnostic included in prompt")
        else:
            print("hypervolume trend computation complete")
    except Exception as exc:  # noqa: BLE001
        dataset_summary = dataset_summary + "\n\n" + f"[hypervolume_trend]\\nunexpected_error={exc}"
        print("[warn] hypervolume trend step raised an unexpected error; diagnostic included")

    if not args.no_sobol:
        print(f"running signed Sobol sensitivity analysis (snapshot: {args.snapshot}) ...")
        try:
            sobol_section = build_sobol_section(settings, rows, args.snapshot)
        except Exception as exc:  # noqa: BLE001
            sobol_section = f"[sobol_sensitivity]\nunexpected_error={exc}"
        dataset_summary = dataset_summary + "\n\n" + sobol_section
        # Report whether real sensitivity data was computed or a fallback message
        if "computation_failed" in sobol_section or "fit_failed" in sobol_section:
            print(f"[warn] Sobol sensitivity computation failed; diagnostic included in prompt")
        elif "no_tradeoff_pairs_found" in sobol_section:
            print("no strong trade-off pairs found; Sobol section skipped")
        elif "snapshot_not_found" in sobol_section:
            print(f"[warn] snapshot not found at {args.snapshot}; Sobol section skipped")
        else:
            print("Sobol sensitivity analysis complete")

    config = OllamaConfig(
        host=args.host,
        model=args.model,
        timeout_sec=max(30, int(args.timeout_sec)),
        temperature=float(args.temperature),
        max_tokens=max(256, int(args.max_tokens)),
        use_thinking=bool(args.thinking),
    )

    try:
        client = ollama.Client(host=config.host, timeout=config.timeout_sec)
        available_models = list_models(client)
    except Exception as exc:  # noqa: BLE001
        print("[error] failed to connect to Ollama. Check 'ollama serve' and host URL.")
        print(f"details: {exc}")
        return 1

    if not available_models:
        print("[error] no models found in Ollama instance.")
        print(f"hint: ollama pull {config.model}")
        return 1

    resolved_model = resolve_model_name(config.model, available_models)
    if resolved_model is None:
        print(f"[error] requested model not found: {config.model}")
        print("available models:")
        for name in available_models:
            print(f"- {name}")
        print(f"hint: ollama pull {config.model}")
        return 1
    config.model = resolved_model

    system, user = build_prompt(dataset_summary, settings)

    try:
        thinking, body = ask_ollama(client, config, system, user)
    except Exception as exc:  # noqa: BLE001
        print(f"[error] generation failed: {exc}")
        return 1

    heading = (
        "# Ax optimization result explanation (Japanese)\n\n"
        f"- source settings: {args.settings.name}\n"
        f"- source summary: {args.summary.name}\n"
        f"- model: {config.model}\n\n"
    )
    output_text = heading + body.strip() + "\n"

    try:
        args.output.write_text(output_text, encoding="utf-8")
    except OSError as exc:
        print(f"[error] failed to write output: {exc}")
        return 1

    print("explanation generated successfully")
    print(f"output: {args.output}")
    print(f"trials processed: {len(rows)}")
    print(f"model used: {config.model}")
    if thinking:
        print("thinking output was returned and handled")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
