# Edge Discovery Bot

このシステムは、バイナリーオプション向けに戦略候補を自動生成・検証し、採用条件を満たすものだけをライブ候補として表示する研究支援アプリです。

## 注意事項
- このシステムはBubingaを自動操作しません。
- Bubingaへのログイン、自動クリック、自動発注は実装していません。
- 実取引の利益を保証しません。
- バックテスト成績は将来の結果を保証しません。
- 条件を満たす戦略がなければシグナルを出しません。
- 金融リスクがあります。

## 起動方法
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## テスト実行方法
```bash
pytest
```

## サンプルCSVで再現する方法
`sample_data/candles.csv` を `/v1/import/csv` に投入し、以下を順番に実行します。
- `/v1/research/generate-candidates`
- `/v1/research/backtest`
- `/v1/research/walk-forward`
- `/v1/research/monte-carlo`
- `/v1/research/promote-strategies`
- `/v1/signals/latest`

active strategy が 0 の場合は `現在採用可能な戦略なし` が返ります。
