# Edge Discovery Bot

このシステムは、戦略候補を生成・検証し、条件を満たすものだけを候補として扱う研究支援アプリです。Bubingaへのログイン、自動クリック、自動発注、画面スクレイピングは実装していません。

CSVの必須カラムは `symbol,timeframe,timestamp,open,high,low,close,volume` です。

M1しかないCSVでは、`/v1/research/resample` で M5 と M15 を決定論的に生成します。仕様は、open=期間先頭、high/low=期間内極値、close=期間末尾、volume=期間合計、timestamp=期間開始時刻、不完全期間は破棄です。

特徴量生成では、M1判定に対して直近で確定済みの M5/M15 特徴量だけを参照します。未確定上位足を使わないことで lookahead bias を避けます。

ラベル生成で1分足を使う場合、30秒満期は unsupported として保存します。60秒満期は次の1分足closeを使う近似です。これは実際のBubinga判定を完全再現するものではありません。

`/v1/research/monte-carlo` は、ランダムではなく決定論的ストレス検証を返します。最悪順序のドローダウン、payout率低下シナリオの期待値を計算します。

active strategy が0の状態は正常系です。その場合 `/v1/signals/latest` は `no_active_strategy` を返します。

Linux/macOS:
```bash
python -m pip install -r requirements.txt
pytest -q
uvicorn app.main:app --reload
```

Windows PowerShell:
```powershell
python -m pip install -r requirements.txt
pytest -q
uvicorn app.main:app --reload
```
