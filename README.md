# bo_chat_analysis

Meta の [Ax](https://ax.dev/) ライブラリを使った**多目的ベイズ最適化**のデモと、ローカル LLM（Ollama）による**日本語結果解説生成**を組み合わせたプロジェクトです。

---

## ファイル構成

| ファイル | 説明 |
|---|---|
| `ax_moo.py` | 多目的最適化を実行するメインスクリプト |
| `ax_config_and_summary_explainer.py` | Ollama を使って最適化結果を日本語 Markdown で解説するスクリプト |
| `ax_optimization_settings.json` | 最適化設定（パラメータ・目的関数）の出力ファイル |
| `ax_summary.csv` | 全試行のサマリーCSV（実行後に生成） |
| `ax_client_snapshot.json` | Ax クライアントのスナップショット（実行後に生成） |
| `ax_moo_analysis_report.html` | Plotly を使ったインタラクティブな分析レポート（実行後に生成） |
| `ax_summary_explanation_ja.md` | LLM が生成した日本語解説（explainer 実行後に生成） |

---

## 最適化問題の設定

- **パラメータ**: `x1`, `x2`, `x3`, `x4` — それぞれ `[0.0, 1.0]` の連続値
- **目的関数**: 以下の 3 つをすべて最大化

| 目的関数 | 最適点 | 閾値 |
|---|---|---|
| `quality` | (x1, x2, x3, x4) ≈ (0.2, 0.8, 0.2, 0.8) | −1.5 |
| `speed` | (x1, x2, x3, x4) ≈ (0.8, 0.2, 0.8, 0.2) | −1.5 |
| `efficiency` | (x1, x2, x3, x4) ≈ (0.5, 0.5, 0.8, 0.2) | −1.2 |

`quality` と `speed` は最適点が相反するため、**トレードオフ関係**が生じます。

- **試行回数**: 30 回（Sobol 初期探索 + ベイズ最適化）

---

## 使い方

### 1. 依存パッケージのインストール

```bash
pip install ax-platform plotly
# LLM 解説を使う場合
pip install ollama
```

Ollama 自体のインストールと、使用するモデル（デフォルト: `qwen3.5`）のプル:

```bash
# https://ollama.com からインストール後
ollama pull qwen3.5
```

### 2. 多目的最適化の実行

```bash
python ax_moo.py
```

実行後、以下のファイルが生成されます:

- `ax_optimization_settings.json`
- `ax_summary.csv`
- `ax_client_snapshot.json`
- `ax_moo_analysis_report.html`

### 3. 日本語解説の生成

```bash
python ax_config_and_summary_explainer.py
```

`ax_summary_explanation_ja.md` に結果の解説が出力されます。

主なオプション:

```
--model MODEL         使用する Ollama モデル名 (デフォルト: qwen3.5)
--host HOST           Ollama ホスト URL (デフォルト: http://127.0.0.1:11434)
--thinking            Qwen thinking モードを有効化
--no-sobol            Sobol 感度分析をスキップ
--temperature FLOAT   サンプリング温度 (デフォルト: 0.2)
--max-tokens INT      最大生成トークン数 (デフォルト: 4096)
```

---

## 出力例

- **ハイパーボリューム収束**: 試行 25 で最終値の 99% に到達（最終値: 2.074）
- **トレードオフ**: `quality` vs `speed` の相関係数 r = −0.83（強いトレードオフ）
- **トレードオン**: `speed` vs `efficiency` の相関係数 r = +0.83（正の相関）

分析レポート (`ax_moo_analysis_report.html`) をブラウザで開くと、パレートフロントや平行座標プロットをインタラクティブに確認できます。
