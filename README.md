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
uv run python ax_moo.py
```

既定では 30 試行を実行し、設定 JSON、試行結果 CSV、Ax スナップショット JSON、HTML 分析レポートをプロジェクト内に保存します。同名の既存結果は上書きされます。計算には時間がかかる場合があります。

レポート先頭の Parallel Coordinates では、全パラメータと全目的を一緒に表示します。橙色は完了試行の観測値に基づくパレート最適、灰色はその他の試行です。目標閾値はパレート判定に適用しません。軸をドラッグして表示範囲を絞り込めます。目的別の図もレポート内に残しています。

## Codex で結果を解説

このフォルダーで Codex を開始し、`$ax-result-explainer` を指定して最適化結果の解説を依頼してください。必要なら `ax_summary_explanation_ja.md` への保存も依頼できます。スキルは `.agents/skills/ax-result-explainer/SKILL.md` にあります。

スキルはディレクトリごと別の Codex スキル配置先にコピーして使用できます。集計コードと uv の依存関係定義を同梱し、対象の結果ディレクトリを指定して読み込みます。スキル専用の環境は初回使用時に作成されます。最適化プログラムと次の集計コマンドはスキルを必要としません。

スキルが参照する数値は、次のコマンドで確認できます。

```powershell
uv run python analysis_evidence.py
uv run python analysis_evidence.py --settings path\to\settings.json --summary path\to\summary.csv
```

CSV の完了試行に基づき、目的別の最良値、均等重みの参考順位、目的間の相関、設定された閾値を基準とした観測ハイパーボリュームを算出します。さらに同じ試行結果の Ax Client スナップショットからモデルを再学習し、符号付き一次 Sobol 感度を求めます。スナップショットの場所は `--snapshot` で変更でき、`--no-sobol` で感度計算を省略できます。符号は生の目的値の平均勾配の方向であり、最小化目的での改善方向は逆になります。

既存の `ax_config_and_summary_explainer.py` は従来の Ollama 版として残していますが、Codex スキルでは使用しません。同スクリプトの旧 AxClient に依存するハイパーボリューム・感度分析は現行 Client のスナップショットには対応していません。
