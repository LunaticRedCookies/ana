# Edge Discovery Bot

timestamp は bar_start_time（足の開始時刻）として扱います。bar_end_time は足の確定時刻です。M5 は start+5分、M15 は start+15分です。

M1判定で上位足を参照するときは、`upper_feature.bar_end_time <= m1.bar_start_time` を満たす確定足だけを使います。これにより、未確定M5/M15の close/high/low を参照しない方針です。

M1からM5/M15のリサンプリングは `/v1/research/resample` で実行できます。open は先頭、high/low は期間内極値、close は末尾、volume は合計です。不完全バケットは破棄し、作成数と破棄数を結果で返します。

ラベル生成では1分足CSVの30秒満期を unsupported にします。60秒満期は次の1分足closeを使う近似で、実際のBubinga満期判定を完全再現するものではありません。

戦略条件DSLは eval を使わず比較関数で評価します。対応演算子は `==`, `!=`, `>`, `>=`, `<`, `<=`, `in`, `not in` です。例: `trend_m15 == "up" && atr_percentile >= 0.3`。

候補生成は方向・満期・トレンド条件の組み合わせで生成します。backtest trade log には、参照した M5/M15 の bar_start_time/bar_end_time を保存し、後から未来参照の有無を検証できます。

lookahead bias テストでは、10:00-10:05のM5足が 10:02 では参照不可、10:05以降で参照可になることを確認します。

active strategy が0は正常です。`/v1/signals/latest` は `no_active_strategy` を返します。

```bash
python -m pip install -r requirements.txt
pytest -q
uvicorn app.main:app --reload
```
