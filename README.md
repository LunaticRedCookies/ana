# Edge Discovery Bot

このシステムは、バイナリーオプション向けに戦略候補を自動生成・検証し、採用条件を満たすものだけをライブ候補として表示する研究支援アプリです。

## 注意事項
- このシステムはBubingaを自動操作しません。
- Bubingaへのログイン、自動クリック、自動発注は実装していません。
- 実取引の利益を保証しません。
- バックテスト成績は将来の結果を保証しません。
- 条件を満たす戦略がなければシグナルを出しません。
- 金融リスクがあります。

## CSV必要カラム
`symbol,timeframe,timestamp,open,high,low,close,volume`

## 研究フロー
`/v1/import/csv` の後に、`/v1/research/generate-features`、`/v1/research/generate-labels`、`/v1/research/generate-candidates`、`/v1/research/backtest`、`/v1/research/walk-forward`、`/v1/research/monte-carlo`、`/v1/research/promote-strategies` の順で実行します。

特徴量生成とラベル生成は `raw_candles` から決定論的に計算します。同じCSVを再投入した場合、同じ結果が再現される前提です。

1分足CSVの場合、30秒満期ラベルは推定せず `unsupported` として保存します。draw はバックテストで損益0として扱います。

本実装では、バックテスト、ウォークフォワード、モンテカルロ、採用判定でランダム値や仮値を使わない方針です。

## 起動方法
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## テスト
```bash
pytest -q
```
