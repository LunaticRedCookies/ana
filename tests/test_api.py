from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_pipeline_and_zero_active_path():
    csv_content = "symbol,timeframe,timestamp,open,high,low,close,volume\nEURUSD,M1,2026-01-01T00:00:00,1.10,1.11,1.09,1.105,100\n"
    assert client.post('/v1/import/csv', json={"content": csv_content}).status_code == 200
    client.post('/v1/research/generate-candidates')
    client.post('/v1/research/backtest')
    client.post('/v1/research/walk-forward')
    client.post('/v1/research/promote-strategies')
    s = client.get('/v1/strategies/status').json()
    assert 'active' in s
    sig = client.get('/v1/signals/latest').json()
    if sig.get('entry_allowed') is False:
        assert 'blocked_reasons' in sig
