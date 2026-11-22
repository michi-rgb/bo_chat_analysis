---
name: ax-result-explainer
description: Ax の最適化設定と試行結果を分析し、日本語で多目的最適化の結果やトレードオフを解説する。Ax の設定 JSON とサマリー CSV に基づく結果解説に使用する。
---

# Ax 最適化結果の解説

ユーザーが指定した対象ディレクトリの `ax_optimization_settings.json` と `ax_summary.csv` を確認する。対象ディレクトリの指定がなければ、まず現在の作業ディレクトリを確認する。両ファイルがそろっていなければ、`results/` 内で両ファイルがそろっている `result_数字/` のうち、番号が最も大きいフォルダーを選ぶ。連番フォルダーに該当する結果がなければ `results/` 直下も確認する。結果は実験ごとに変化するため、既存の解説文の数値を流用しない。

スキル自身のディレクトリにある `scripts/analysis_evidence.py` と `pyproject.toml` を使う。Windows では、実際のスキルディレクトリの絶対パスを `$skillDir`、対象データのディレクトリを `$dataDir` に設定し、次を実行する。

```powershell
uv run --locked --project $skillDir python "$skillDir\scripts\analysis_evidence.py" --settings "$dataDir\ax_optimization_settings.json" --summary "$dataDir\ax_summary.csv"
```

初回は uv がスキル専用の仮想環境と依存パッケージを準備する。Python 3.14 と uv が必要。設定、完了試行、各目的の最良試行、均等重みの参考順位、目的間の相関、観測ハイパーボリュームの推移と符号付き一次 Sobol 感度を取得する。スナップショットを `--snapshot` で指定しなければ CSV と同じディレクトリの `ax_client_snapshot.json` を使う。感度計算を省く場合は `--no-sobol` を使う。実行できない場合は原因を伝え、利用できたデータの範囲で分析する。

得られた根拠を用い、日本語の Markdown で探索範囲と目的・閾値、試行状況、目的別の最良条件、バランスの取れた候補、全目的ペアの関係、ハイパーボリュームの変化と次の判断を説明する。試行番号と値を示し、欠損・計算不能を推測で補わない。均等重みの順位は観測範囲による仮の指標で、ユーザーの選好やパレート最適性そのものではない。相関は観測された試行上の関係であり、因果関係や探索領域全体の性質の証明ではない。最終値の 99% に達した試行は事後的な目安で、最適化の真の収束を意味しない。

Sobol 感度は再学習した代理モデルに基づく一次効果であり、符号は目的値そのものの平均勾配の符号である。最小化目的では、負の符号が改善方向となる。局所的な増減や因果効果を保証しない。算出できなかった場合はその旨を記し、数値を作らない。結果を保存する場合は、対象ディレクトリの `ax_summary_explanation_ja.md` に入力元と分析上の制約を記す。

Markdown の表を出力する場合は、各表の見出し行と区切り行の列数が一致することを確認する。データ行も同じ列数にそろえ、区切り行は `| --- | ---: |` のようにパイプの前後へ空白を入れる。保存後に全表を点検し、列数の不一致を修正する。

HTML レポートの出力を依頼された場合は、対象フォルダーにある Ax の `ax_moo_analysis_report.html` から英語版と日本語版を生成する。Windows では次のコマンドを使う。

```powershell
uv run --locked --project $skillDir python "$skillDir\scripts\report_languages.py" "$dataDir"
```

英語版は `ax_moo_analysis_report.html`、日本語版は `ax_moo_analysis_report_ja.html` に保存する。両版とも、全目的の平行座標プロットを最初の目的別プロットの直前に置く。対象フォルダーに元の HTML がなければ、それを伝える。試行を実行し直す必要はない。
