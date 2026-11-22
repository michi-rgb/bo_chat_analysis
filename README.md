# bo_chat_analysis

Ax による 4 変数・3 目的のベイズ最適化のデモと、Codex による結果解説です。

## 環境

Windows で uv と Python 3.14 を使います。依存関係は `pyproject.toml` に定義し、Ax 1.3.1 を指定しています。プロジェクトフォルダーで次を実行します。

```powershell
uv sync
```

Python 3.14 が未導入の場合は、uv がダウンロードすることがあります。Ax とその依存パッケージもインストールされます。

## 最適化

```powershell
uv run python scripts/ax_moo.py
```

既定では 30 試行を実行し、設定 JSON、試行結果 CSV、Ax スナップショット JSON、英語と日本語の HTML 分析レポートを保存します。実行ごとにプロジェクト直下の `results/` に連番フォルダー（`result_1/`、`result_2/` など）を作成します。計算には時間がかかる場合があります。

全目的の平行座標プロットは、目的別の平行座標プロットの直前にあります。全パラメータと全目的を一緒に表示し、完了試行の観測値に基づくパレート最適を橙色、その他の試行を灰色で示します。目標閾値はパレート判定に適用しません。軸をドラッグして表示範囲を絞り込めます。

英語版は `ax_moo_analysis_report.html`、日本語版は `ax_moo_analysis_report_ja.html` です。既存の Ax HTML レポートから両版を作成する場合は、対象フォルダーを指定します。

```powershell
$skillDir = '.agents\skills\ax-result-explainer'
uv run --locked --project $skillDir python "$skillDir\scripts\report_languages.py" results
```

## Codex で結果を解説

プロジェクトフォルダーで Codex を開始し、`$ax-result-explainer` を指定して最適化結果の解説を依頼してください。解説は対象の結果フォルダーの `ax_summary_explanation_ja.md` に保存できます。スキルは `.agents/skills/ax-result-explainer/SKILL.md` にあります。

スキルはディレクトリごと別の Codex スキル配置先にコピーして使用できます。集計コードと uv の依存関係定義を同梱し、対象の結果ディレクトリを指定して読み込みます。スキル専用の環境は初回使用時に作成されます。

プロジェクトフォルダーで次のコマンドを実行すると、`results/` の連番フォルダーのうち、設定 JSON と試行結果 CSV がそろっている最大番号の結果を集計します。該当する連番フォルダーがなければ、`results/` 直下の結果を集計します。

```powershell
$skillDir = '.agents\skills\ax-result-explainer'
uv run --locked --project $skillDir python "$skillDir\scripts\analysis_evidence.py"
```

特定の結果を集計する場合は、対象フォルダーの設定 JSON と試行結果 CSV を渡します。以下は同梱の結果を指定する例です。

```powershell
$dataDir = 'results'
uv run --locked --project $skillDir python "$skillDir\scripts\analysis_evidence.py" --settings "$dataDir\ax_optimization_settings.json" --summary "$dataDir\ax_summary.csv"
```

CSV の完了試行に基づき、目的別の最良値、均等重みの参考順位、目的間の相関、設定された閾値を基準とした観測ハイパーボリュームを算出します。さらに同じ試行結果の Ax Client スナップショットからモデルを再学習し、符号付き一次 Sobol 感度を求めます。スナップショットの場所は `--snapshot` で変更でき、`--no-sobol` で感度計算を省略できます。符号は生の目的値の平均勾配の方向であり、最小化目的での改善方向は逆になります。
