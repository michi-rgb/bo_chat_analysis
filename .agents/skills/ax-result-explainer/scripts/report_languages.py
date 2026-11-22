"""Write English and Japanese editions of the Ax 1.3.1 analysis report."""

from __future__ import annotations

import argparse
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re


REPORT_NAME = "ax_moo_analysis_report.html"
JAPANESE_REPORT_NAME = "ax_moo_analysis_report_ja.html"

LABELS = {
    "Ax Multi-Objective Analysis Report": "Ax 多目的最適化レポート",
    "Parallel Coordinates — All Objectives": "平行座標プロット（全目的）",
    "No completed trials with plottable values.": "表示できる完了試行がありません。",
    "Overview of the Entire Optimization Process": "最適化プロセスの全体像",
    "Results Analysis": "最適化結果",
    "Metric Effects: Predicted and observed effects for all arms in the experiment": "指標の効果（全アームの予測と観測）",
    "Scatter Plot (Objectives)": "散布図（目的指標）",
    "Utility Progression": "ハイパーボリュームの推移",
    "Pareto Frontier Trials for Experiment": "観測値に基づくパレート最適試行",
    "Insights Analysis": "パラメータと指標の関係",
    "Top Surfaces Analysis: Parameter sensitivity, slice, and contour plots": "主要パラメータの感度・断面図・等高線図",
    "Slice Plots: Metric effects by parameter value": "断面図（パラメータ値と指標の関係）",
    "Contour Plots: Metric effects by parameter values": "等高線図（パラメータ値と指標の関係）",
    "Diagnostic Analysis": "モデル診断",
    "Cross Validation: Assessing model fit": "モデルの適合度を調べる交差検証",
    "Summary of model fits": "モデル適合度の概要",
    "Generation Strategy Graph": "候補生成戦略のグラフ",
    "GenerationStrategy": "候補生成戦略",
    "Health Checks": "実験の健全性チェック",
    "Baseline Improvement Healthcheck": "基準値からの改善状況",
    "See more": "詳細を表示",
    "trial_index": "試行番号",
    "Trial Index": "試行番号",
    "arm_name": "アーム名",
    "Arm Name": "アーム名",
    "trial_status": "試行状態",
    "generation_node": "候補生成ノード",
    "COMPLETED": "完了",
    "FAILED": "失敗",
    "ABANDONED": "中止",
    "EARLY_STOPPED": "早期終了",
    "RUNNING": "実行中",
    "CANDIDATE": "候補",
    "CenterOfSearchSpace": "探索空間の中心",
    "AutoTransitionAfterGen": "候補生成後に自動遷移",
    "Metric": "指標",
    "Status": "状態",
    "Details": "詳細",
    "Improved": "改善",
    "Not Improved": "改善なし",
    "quality": "品質",
    "speed": "速度",
    "efficiency": "効率",
    "Hypervolume": "ハイパーボリューム",
    "importance": "重要度",
    "display_parameter_name": "パラメータ",
    "parameter_name": "パラメータ名",
    "direction": "変化の方向",
    "utility": "ハイパーボリューム",
    "Actual Outcome": "観測値",
    "Predicted Outcome": "予測値",
    "Pareto Frontier": "パレートフロンティア",
    "Mean": "平均",
    "Standard Error": "標準誤差",
    "Sampled": "試行済み",
}

# Match prefixes of Ax captions so long descriptions and metric-specific variants share a translation.
CAPTIONS = {
    "This analysis provides an overview": "最適化結果、Ax モデルが学習したパラメータと指標の関係、モデルの適合度、実験の健全性を確認できます。",
    "Result Analyses provide": "実験で定義した指標ごとに、これまでの最適化結果を示します。",
    "These pair of plots visualize": "左は Ax モデルの予測、右は生の観測値です。予測ではノイズの影響を縮小し、データの非定常性を補正して、長期の検証実験で再現が期待される効果を示します。",
    "Modeled effects on ": "各アームを再実行した場合に期待される指標の変化を Ax モデルが予測します。アーム間で予測値がほぼ同じ場合、モデルは変化が小さく、図の信頼区間内に収まると予測しています。",
    "Observed effects on ": "実行済みの各アームで観測された指標値です。設定ごとの実績を比較し、有望な条件を確認できます。",
    "These plots display the effects": "横軸と縦軸に目的指標を取り、各アームの効果を示します。指標間のトレードオフとパレートフロンティアを確認できます。",
    "This plot displays the effects": "選んだ二つの指標について各アームの効果を示します。トレードオフとパレートフロンティアを確認できます。",
    "Shows the hypervolume": "横軸は試行番号、縦軸はパレートフロンティアが支配する目的空間の体積の累積最良値です。目的値がそろった完了試行と早期終了試行が対象です。横ばいは改善がなかったことを示します。結果制約を満たさない試行は改善に寄与しません。",
    "Displays trials on the Pareto frontier": "完了試行の観測値でパレートフロンティアに達した条件を示します。すべての目的で同等以上、かつ一つ以上の目的で上回る別の試行が存在しない条件です。目的間のトレードオフを比較できます。",
    "High-level summary of the": "この実験の試行一覧です。",
    "Insight Analyses display": "Ax モデルが学習したパラメータと指標の関係を確認し、探索空間の特徴を把握できます。",
    "The top surfaces analysis displays": "まず指標に対する主要パラメータの感度を示します。続く断面図と等高線図では、重要度の高いパラメータと指標値の関係を示します。",
    "Understand how each parameter affects": "二次感度分析で、各パラメータが指標に及ぼす影響を調べます。",
    "These plots show the relationship between a metric and two parameters": "横軸と縦軸の二つのパラメータを変えたときの指標の予測値を色で示します。他のパラメータは、既存条件、最良試行、または探索空間の中心の値に固定します。",
    "These plots show the relationship": "横軸のパラメータを変えたときの指標の予測値を縦軸に示します。他のパラメータは、既存条件、最良試行、または探索空間の中心の値に固定します。",
    "The slice plot provides": "他のパラメータを探索空間の中心に固定し、一つのパラメータの変化に対する指標の予測値を示します。",
    "The contour plot visualizes": "他のパラメータを固定し、二つのパラメータを変えたときの指標の予測値を示します。予測値が等しい点を等高線で結び、指標が改善する方向や最適値の候補を確認できます。",
    "Diagnostic Analyses provide": "最適化プロセスとモデルの適合度を確認します。最適化の質を上げるために実験設計を見直す際の参考になります。",
    "Cross-validation plots display": "データの一部で学習し、残りの観測値を予測します。横軸が観測値、縦軸が予測値です。点が対角の点線に近いほど予測精度が高く、信頼区間は観測ノイズと予測の不確かさを示します。",
    "NOTE: A horizontal": "予測値が横一列に並ぶ場合、モデルがデータの傾向を十分に捉えず、平均値に近い予測をしている可能性があります。",
    "The cross-validation plot displays": "一つの観測値を検証用に取り除き、残りで学習する交差検証です。横軸が観測値、縦軸が予測値です。点が対角の点線に近いほど予測精度が高くなります。95% 信頼区間は観測ノイズと予測の不確かさを示し、予測値が横一列ならモデルが平均値に近い予測をしている可能性があります。",
    "R² (coefficient of determination)": "R²（決定係数）は各指標に対する予測の適合度です。値が大きいほど適合が良く、0.1 以上の指標は緑色で表示します。",
    "Comprehensive health checks": "指標の取得、探索空間の設定、候補の生成を調べ、対応が必要な問題を見つけます。",
    "The parallel coordinates plot displays": "各パラメータを平行な軸に取り、試行を線で結びます。探索範囲の網羅性や、指標値の高い条件と低い条件のまとまりを比較し、パラメータ間の関係を確認できます。",
}

PLOTLY_JA = {
    "Download plot as a PNG": "グラフを PNG で保存",
    "Zoom": "拡大・縮小",
    "Pan": "移動",
    "Box Select": "範囲選択",
    "Lasso Select": "投げ縄選択",
    "Zoom in": "拡大",
    "Zoom out": "縮小",
    "Autoscale": "軸範囲を自動調整",
    "Reset axes": "軸をリセット",
    "Toggle Spike Lines": "補助線の表示切替",
    "Show closest data on hover": "カーソルに最も近い値を表示",
    "Compare data on hover": "カーソル位置の値を比較",
    "Click to enter Colorscale title": "クリックして色軸のタイトルを入力",
    "Double-click to zoom back out": "ダブルクリックで拡大前に戻ります",
    "Double-click on legend to isolate one trace": "凡例をダブルクリックすると、その系列だけを表示します",
}

ENGLISH_COUNT = "Completed trials: {}. Orange: {} observed Pareto-optimal trials. Gray: other trials. Drag along an axis to filter by value. Objective thresholds are excluded from Pareto classification."
JAPANESE_COUNT = "完了試行は {} 件です。橙色は観測値に基づくパレート最適試行 {} 件、灰色はその他の試行です。軸をドラッグして値の範囲を絞り込めます。パレート最適の判定には目的の閾値を使いません。"


def english_text(value: str) -> str:
    legacy_labels = {
        "Parallel Coordinates — 全目的": "Parallel Coordinates — All Objectives",
        "試行番号": "Trial Index",
        "表示可能な完了試行がありません。": "No completed trials with plottable values.",
    }
    counts = re.match(r"完了試行 (\d+) 件。橙色: 観測値に基づくパレート最適 (\d+) 件、", value)
    if counts:
        return ENGLISH_COUNT.format(*counts.groups())
    return legacy_labels.get(value, value)


def japanese_label(value: str) -> str:
    return LABELS.get(value, value)


TITLES = (
    (r"Completed trials: (\d+)\. Orange: (\d+) observed Pareto-optimal trials\..*", JAPANESE_COUNT),
    (r"Metric Effects Pair for (.+)", "{} の予測効果と観測効果"),
    (r"Modeled Arm Effects on (.+)", "{} のアーム別予測効果"),
    (r"Observed Arm Effects on (.+)", "{} のアーム別観測効果"),
    (r"Modeled Effects: (.+) vs\. (.+)", "予測効果（{} と {}）"),
    (r"Summary for (.+)", "試行の概要（{}）"),
    (r"Sensitivity Analysis for (.+)", "{} の感度分析"),
    (r"(.+) \((Mean|Standard Error)\) vs\. (.+), (.+)", "{} の予測（{}）と {}・{} の関係"),
    (r"(.+) vs\. (x\d+)", "{} と {} の関係"),
    (r"Cross Validation for (.+) \(R² = (.+)\)", "{} の交差検証（R² = {}）"),
    (r"Parallel Coordinates for (.+)", "{} の平行座標プロット"),
    (r"Trial (\d+)", "試行 {}"),
    (r"Increases (.+)", "{}を増加させる"),
    (r"Decreases (.+)", "{}を減少させる"),
    (r"Sampled (.+)", "試行済みの {}"),
    (r"MinTrials\((\d+)\)", "最低試行数（{}）"),
    (r"(.+)->(.+)", "{} から {} へ"),
)
JAPANESE_BASELINE_LINE = "{}がアーム「{}」の {} からアーム「{}」の {} に改善（Ax の変化率 {}）"
BASELINE_LINE = re.compile(r"\*\*Metric \x60(.+?)\x60 improved (.+?)\*\* from \x60(.+?)\x60 in arm \x60'(.+?)'\x60 to \x60(.+?)\x60 in arm \x60'(.+?)'\x60\.")


def japanese_text(value: str) -> str:
    if value in LABELS:
        return LABELS[value]
    for pattern, translation in TITLES:
        if match := re.fullmatch(pattern, value):
            return translation.format(*(japanese_label(field) for field in match.groups()))
    for prefix, translation in CAPTIONS.items():
        if value.startswith(prefix):
            return translation
    if value.startswith("GenerationStrategy: "):
        strategy = value.splitlines()[0].removeprefix("GenerationStrategy: ")
        return f"候補生成戦略「{strategy}」\n\n各ノードは候補の生成段階、矢印は段階間の遷移を示します。矢印のラベルは遷移条件です。"
    if value.startswith("All ") and "objective(s) improved over baseline." in value:
        value = re.sub(r"All (\d+) objective\(s\) improved over baseline\.", r"全 \1 目的が基準値から改善しました。", value)
        value = value.replace("**Objective-by-objective breakdown:**", "目的ごとの内訳")
        value = re.sub(
            r"\*\*Note:\*\* Using the first trial's first arm \('(.+?)'\) as the baseline since no explicit baseline was provided\.",
            r"基準の指定がなかったため、最初の試行の最初のアーム「\1」を基準にしました。",
            value,
        )
    return BASELINE_LINE.sub(
        lambda m: JAPANESE_BASELINE_LINE.format(japanese_label(m[1]), m[4], m[3], m[6], m[5], m[2]),
        value,
    )


def japanese_plot_text(value: str) -> str:
    if value.startswith("Trial: "):
        replacements = {
            "Trial": "試行番号", "Arm": "アーム", "Status": "状態",
            "Generation Node": "候補生成ノード", **LABELS,
        }
        return re.sub(
            r"(?:^|(?<=>))([A-Za-z_ ]+): ([^<]*)",
            lambda m: f"{replacements.get(m[1], m[1])}：{japanese_label(m[2])}",
            value,
        )
    if value.startswith("<b>Arm Name:"):
        return "<b>アーム名：%{text}</b><br>予測値：%{y}<br>観測値：%{x}<br><extra></extra>"
    if value == "(%{x}, %{y})<extra>Sampled</extra>":
        return "(%{x}, %{y})<extra>試行済み</extra>"
    if value.startswith(("direction=", "trial_index=")):
        return "<br>".join(
            f"{japanese_label(key)}：{japanese_text(text)}" if separator else field
            for field in value.split("<br>")
            for key, separator, text in [field.partition("=")]
        )
    return japanese_text(english_text(value))


PLOT_TEXT_KEYS = {"text", "name", "label", "hovertext", "hovertemplate", "ticktext", "title", "legendgroup"}
PLOT_CALL = re.compile(r'Plotly\.newPlot\(\s*"(?:[^"\\]|\\.)*"\s*,\s*')


def localize_plot(script: str, language: str) -> str:
    match = PLOT_CALL.search(script)
    if match is None:
        return script
    translate = japanese_plot_text if language == "ja" else english_text

    def visit(value, key=""):
        if isinstance(value, dict):
            return {name: visit(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [visit(item, key) for item in value]
        if isinstance(value, str) and key in PLOT_TEXT_KEYS:
            return translate(value)
        return value

    decoder = json.JSONDecoder()
    data, end = decoder.raw_decode(script, match.end())
    layout_start = re.match(r"\s*,\s*", script[end:]).end() + end
    layout, end = decoder.raw_decode(script, layout_start)
    config_start = re.match(r"\s*,\s*", script[end:]).end() + end
    config, end = decoder.raw_decode(script, config_start)
    config["locale"] = language
    # Escape HTML delimiters, including a possible closing script tag in a label.
    arguments = json.dumps([visit(data), visit(layout), config], ensure_ascii=True, separators=(",", ":"))
    arguments = arguments[1:-1].replace("<", r"\u003c").replace(">", r"\u003e")
    return script[:match.end()] + arguments + script[end:]


class LocalizedReport(HTMLParser):
    def __init__(self, language: str):
        super().__init__(convert_charrefs=True)
        self.language = language
        self.parts: list[str] = []
        self.raw_tag = None
        self.in_head = False

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()
        if tag == "html":
            raw = re.sub(r'\blang="[^"]*"', f'lang="{self.language}"', raw)
        if tag == "head":
            self.in_head = True
        if tag in {"script", "style"}:
            self.raw_tag = tag
        self.parts.append(raw)

    def handle_startendtag(self, tag, attrs):
        self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if tag == self.raw_tag:
            self.raw_tag = None
        if tag == "head":
            self.in_head = False
            if self.language == "ja":
                dictionary = json.dumps(PLOTLY_JA, ensure_ascii=False)
                self.parts.append(
                    f'<script>Plotly.register({{moduleType:"locale",name:"ja",dictionary:{dictionary},format:{{}}}});</script>'
                )
        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if self.raw_tag:
            if self.raw_tag == "script" and not self.in_head:
                data = localize_plot(data, self.language)
            self.parts.append(data)
            return
        content = data.strip()
        if content:
            translated = english_text(content)
            if self.language == "ja":
                translated = japanese_text(translated)
            data = data.replace(content, translated, 1)
        self.parts.append(escape(data, quote=False))

    def handle_comment(self, data):
        self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl):
        self.parts.append(f"<!{decl}>")


def group_parallel_coordinates(source: str) -> str:
    """Place the all-objectives section immediately before the first objective card."""
    overview = re.search(r'<section id="all-objectives">.*?</section>', source, re.DOTALL)
    first_objective = re.search(
        r'<div class="card">\s*<div class="card-header">\s*<b>\s*Parallel Coordinates for [^<]+</b>',
        source,
    )
    if overview is None or first_objective is None:
        return source

    start = first_objective.start()
    if overview.end() <= start and not source[overview.end():start].strip():
        return source

    section = overview[0] + "\n"
    without_overview = source[:overview.start()] + source[overview.end():]
    if overview.end() <= start:
        start -= overview.end() - overview.start()
    return without_overview[:start] + section + without_overview[start:]


def write_report_pair(source: str, directory: Path) -> tuple[Path, Path]:
    source = group_parallel_coordinates(source)
    paths = directory / REPORT_NAME, directory / JAPANESE_REPORT_NAME
    for language, path in zip(("en", "ja"), paths):
        report = LocalizedReport(language)
        report.feed(source)
        report.close()
        path.write_text("".join(report.parts), encoding="utf-8")
    return paths


def main() -> None:
    from analysis_evidence import find_data_directory

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, help="folder containing the Ax HTML report")
    args = parser.parse_args()
    directory = args.directory or find_data_directory(
        Path.cwd(), "ax_optimization_settings.json", "ax_summary.csv"
    )
    source = (directory / REPORT_NAME).read_text(encoding="utf-8")
    for path in write_report_pair(source, directory):
        print(path)


if __name__ == "__main__":
    main()
