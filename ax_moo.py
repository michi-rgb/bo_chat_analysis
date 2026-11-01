from __future__ import annotations

import ast
import json
import math
import re
from pathlib import Path

from ax.api.client import Client
from ax.api.configs import RangeParameterConfig
from ax.analysis.overview import OverviewAnalysis
from ax.analysis.plotly.parallel_coordinates import ParallelCoordinatesPlot
from ax.core.objective import Objective
from ax.core.optimization_config import MultiObjectiveOptimizationConfig
from ax.core.outcome_constraint import OutcomeConstraint
from plotly.offline import get_plotlyjs
import plotly.graph_objects as go

# Objective thresholds: lower bounds for hypervolume calculation.
# Parameters: x1, x2, x3, x4 in [0, 1]
# quality    = -sum((xi - opt_q_i)^2)  optimal near (0.2, 0.8, 0.2, 0.8)  range: [-2.56, 0]
# speed      = -sum((xi - opt_s_i)^2)  optimal near (0.8, 0.2, 0.8, 0.2)  range: [-2.56, 0]
# efficiency = -sum((xi - opt_e_i)^2)  optimal near (0.5, 0.5, 0.8, 0.2)  range: [-1.78, 0]
_QUALITY_THRESHOLD = -1.5
_SPEED_THRESHOLD = -1.5
_EFFICIENCY_THRESHOLD = -1.2

n_trials = 30


def evaluate(parameters: dict[str, float]) -> dict[str, float]:
    """Synthetic three-objective function over four parameters with trade-off structure."""
    x1 = parameters["x1"]
    x2 = parameters["x2"]
    x3 = parameters["x3"]
    x4 = parameters["x4"]

    # Objective 1: best near (0.2, 0.8, 0.2, 0.8)
    quality = -(
        (x1 - 0.2) ** 2 + (x2 - 0.8) ** 2 + (x3 - 0.2) ** 2 + (x4 - 0.8) ** 2
    )
    # Objective 2: best near (0.8, 0.2, 0.8, 0.2) — conflicts with quality
    speed = -(
        (x1 - 0.8) ** 2 + (x2 - 0.2) ** 2 + (x3 - 0.8) ** 2 + (x4 - 0.2) ** 2
    )
    # Objective 3: best near (0.5, 0.5, 0.8, 0.2) — conflicts with both quality and speed
    efficiency = -(
        (x1 - 0.5) ** 2 + (x2 - 0.5) ** 2 + (x3 - 0.8) ** 2 + (x4 - 0.2) ** 2
    )

    return {"quality": quality, "speed": speed, "efficiency": efficiency}


def fix_graphviz_svg(html: str) -> str:
    """Decode Graphviz SVG byte literals produced by Ax's HTML renderer."""
    # Ax's Graphviz card currently embeds the repr of SVG bytes in its HTML.
    # Decode only those byte literals so the browser renders the inline SVG.
    def decode_graphviz_svg(match: re.Match[str]) -> str:
        svg = ast.literal_eval(match.group(1)).decode("utf-8")
        start, end = svg.find("<svg"), svg.rfind("</svg>")
        if start < 0 or end < 0:
            return match.group(0)
        return "<div>" + svg[start : end + len("</svg>")] + "</div>"

    return re.sub(
        r"<div>(b(['\"])<\?xml.*?\2)</div>", decode_graphviz_svg, html
    )


def all_objectives_plot(summary, parameter_names: list[str], objective_configs: list[dict]) -> str:
    """Render completed observed trials, highlighting the observed Pareto frontier."""
    names = parameter_names + [objective["name"] for objective in objective_configs]
    rows = []
    for _, row in summary.iterrows():
        if str(row["trial_status"]).upper() != "COMPLETED":
            continue
        try:
            values = [float(row[name]) for name in names]
            trial_index = int(row["trial_index"])
        except (KeyError, TypeError, ValueError):
            continue
        if all(math.isfinite(value) for value in values):
            rows.append((trial_index, values))
    if not rows:
        return '<section id="all-objectives"><h2>Parallel Coordinates — 全目的</h2><p>表示可能な完了試行がありません。</p></section>'

    n_params = len(parameter_names)
    scores = [
        [(-value if objective["minimize"] else value)
         for value, objective in zip(values[n_params:], objective_configs)]
        for _, values in rows
    ]
    pareto = [
        not any(all(b >= a for a, b in zip(point, other))
                and any(b > a for a, b in zip(point, other))
                for other in scores)
        for point in scores
    ]
    dimensions = [dict(label="試行番号", values=[trial for trial, _ in rows])]
    dimensions.extend(dict(label=name, values=[values[i] for _, values in rows])
                      for i, name in enumerate(names))
    fig = go.Figure(go.Parcoords(
        dimensions=dimensions,
        line=dict(color=[int(is_pareto) for is_pareto in pareto], cmin=0, cmax=1,
                  colorscale=[[0, "#aeb8c4"], [0.499, "#aeb8c4"],
                              [0.5, "#d05a23"], [1, "#d05a23"]], showscale=False),
    ))
    fig.update_layout(margin=dict(l=60, r=60, t=40, b=35), height=520)
    plot = fig.to_html(full_html=False, include_plotlyjs=False)
    return (f'<section id="all-objectives"><h2>Parallel Coordinates — 全目的</h2>'
            f'<p>完了試行 {len(rows)} 件。橙色: 観測値に基づくパレート最適 {sum(pareto)} 件、'
            '灰色: ほかの試行。各軸の範囲をドラッグして絞り込めます。'
            '判定に目標閾値は適用していません。</p>'
            f'{plot}</section>')


def save_cards_as_html(cards: list, output_path: Path, summary, parameter_names: list[str],
                       objective_configs: list[dict]) -> None:
    """Render AnalysisCards returned by client.compute_analyses() to an HTML report."""
    card_html = fix_graphviz_svg("\n".join(card._to_html(depth=0) for card in cards))
    html = f"""<!doctype html>
<html lang=\"ja\">
<head>
  <meta charset=\"utf-8\" />
  <title>Ax Multi-Objective Analysis Report</title>
  <script>define = null;{get_plotlyjs()}</script>
</head>
<body>
  <h1>Ax Multi-Objective Analysis Report</h1>
  {all_objectives_plot(summary, parameter_names, objective_configs)}
  {card_html}
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


def main() -> None:
    client = Client(random_seed=123)

    parameter_configs = [
        {"name": "x1", "bounds": [0.0, 1.0], "parameter_type": "float"},
        {"name": "x2", "bounds": [0.0, 1.0], "parameter_type": "float"},
        {"name": "x3", "bounds": [0.0, 1.0], "parameter_type": "float"},
        {"name": "x4", "bounds": [0.0, 1.0], "parameter_type": "float"},
    ]

    objective_configs = [
        {"name": "quality", "minimize": False, "threshold": _QUALITY_THRESHOLD},
        {"name": "speed", "minimize": False, "threshold": _SPEED_THRESHOLD},
        {"name": "efficiency", "minimize": False, "threshold": _EFFICIENCY_THRESHOLD},
    ]

    client.configure_experiment(
        name="moo_4param_3obj_demo",
        parameters=[
            RangeParameterConfig(
                name=p["name"],
                bounds=(p["bounds"][0], p["bounds"][1]),
                parameter_type=p["parameter_type"],
            )
            for p in parameter_configs
        ],
    )

    # Multi-objective optimization: maximize quality, speed, and efficiency.
    client.configure_optimization(objective="quality, speed, efficiency")

    # Explicitly set objective thresholds so that
    # winsorize and hypervolume calculations use a shared reference point.
    client.set_optimization_config(
        MultiObjectiveOptimizationConfig(
            objective=Objective(
                expression=", ".join(o["name"] for o in objective_configs),
                metric_name_to_signature={o["name"]: o["name"] for o in objective_configs},
            ),
            objective_thresholds=[
                OutcomeConstraint(
                    expression=f"{o['name']} >= {o['threshold']}",
                    metric_name_to_signature={o["name"]: o["name"]},
                    relative=False,
                )
                for o in objective_configs
            ],
        )
    )

    optimization_settings_path = Path(__file__).with_name("ax_optimization_settings.json")
    optimization_settings = {
        "parameters": [
            {
                "name": p["name"],
                "search_range": {"min": p["bounds"][0], "max": p["bounds"][1]},
                "parameter_type": p["parameter_type"],
            }
            for p in parameter_configs
        ],
        "objectives": [
            {
                "name": o["name"],
                "direction": "minimize" if o["minimize"] else "maximize",
                "threshold": o["threshold"],
            }
            for o in objective_configs
        ],
    }
    optimization_settings_path.write_text(
        json.dumps(optimization_settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved optimization settings: {optimization_settings_path}")

    
    for _ in range(n_trials):
        trials = client.get_next_trials(max_trials=1)
        trial_index, params = next(iter(trials.items()))
        raw_data = evaluate(params)
        client.complete_trial(trial_index=trial_index, raw_data=raw_data)

    analyses = [
        OverviewAnalysis(),
        ParallelCoordinatesPlot(metric_name="quality"),
        ParallelCoordinatesPlot(metric_name="speed"),
        ParallelCoordinatesPlot(metric_name="efficiency"),
    ]
    cards = client.compute_analyses(analyses=analyses, display=False)

    output_path = Path(__file__).with_name("ax_moo_analysis_report.html")
    summary = client.summarize()
    save_cards_as_html(cards=cards, output_path=output_path, summary=summary,
                       parameter_names=[p["name"] for p in parameter_configs],
                       objective_configs=objective_configs)

    print(f"Trials completed: {n_trials}")
    print(f"Analysis cards computed: {len(cards)}")
    print(f"Saved analysis report: {output_path}")

    client.save_to_json_file(filepath=str(Path(__file__).with_name("ax_client_snapshot.json")))
    print("Experiment summary:")
    print(summary)

    summary_csv_path = Path(__file__).with_name("ax_summary.csv")
    if hasattr(summary, "to_csv"):
        summary.to_csv(summary_csv_path, index=False)
        print(f"Saved summary csv: {summary_csv_path}")

    return summary

if __name__ == "__main__":
    main()
    # new_client = Client.load_from_json_file(filepath="ax_client_snapshot.json")
