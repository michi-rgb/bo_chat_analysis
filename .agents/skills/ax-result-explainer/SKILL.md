---
name: ax-result-explainer
description: Ax の最適化設定と試行結果を分析し、日本語で多目的最適化の結果やトレードオフを解説する。Ax の設定 JSON とサマリー CSV に基づく結果解説に使用する。
---

# Ax 最適化結果の解説

ユーザーが指定した対象ディレクトリの `ax_optimization_settings.json` と `ax_summary.csv` を確認する。指定がなければ現在の作業ディレクトリを対象とする。結果は実験ごとに変化するため、既存の解説文の数値を流用しない。

スキル自身のディレクトリにある `scripts/analysis_evidence.py` と `pyproject.toml` を使う。Windows では、実際のスキルディレクトリの絶対パスを `$skillDir`、対象データのディレクトリを `$dataDir` に設定し、次を実行する。

```powershell
uv run --locked --project $skillDir python "$skillDir\scripts\analysis_evidence.py" --settings "$dataDir\ax_optimization_settings.json" --summary "$dataDir\ax_summary.csv"
```

初回は uv がスキル専用の仮想環境と依存パッケージを準備する。Python 3.14 と uv が必要。設定、完了試行、各目的の最良試行、均等重みの参考順位、目的間の相関、観測ハイパーボリュームの推移と符号付き一次 Sobol 感度を取得する。スナップショットを `--snapshot` で指定しなければ CSV と同じディレクトリの `ax_client_snapshot.json` を使う。感度計算を省く場合は `--no-sobol` を使う。実行できない場合は原因を伝え、利用できたデータの範囲で分析する。

得られた根拠を用い、日本語の Markdown で探索範囲と目的・閾値、試行状況、目的別の最良条件、バランスの取れた候補、全目的ペアの関係、ハイパーボリュームの変化と次の判断を説明する。試行番号と値を示し、欠損・計算不能を推測で補わない。均等重みの順位は観測範囲による仮の指標で、ユーザーの選好やパレート最適性そのものではない。相関は観測された試行上の関係であり、因果関係や探索領域全体の性質の証明ではない。最終値の 99% に達した試行は事後的な目安で、最適化の真の収束を意味しない。

Sobol 感度は再学習した代理モデルに基づく一次効果であり、符号は目的値そのものの平均勾配の符号である。最小化目的では、負の符号が改善方向となる。局所的な増減や因果効果を保証しない。算出できなかった場合はその旨を記し、数値を作らない。結果を `ax_summary_explanation_ja.md` に保存する場合は入力元と分析上の制約を記す。
