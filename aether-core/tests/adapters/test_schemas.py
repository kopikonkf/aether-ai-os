from aether.adapters.schemas import (
    WhoAmIResponse,
    BelieveRequest,
    EvaluateRequest,
    EvaluateResponse,
    RunTaskRequest,
)

def test_who_am_i_response_defaults():
    r = WhoAmIResponse(name="Aether", narrative="test", stage="baby")
    assert r.name == "Aether"
    assert r.stage == "baby"

def test_evaluate_request_requires_action():
    req = EvaluateRequest(action="open_trade", reason="signal", amount_usd=5.0)
    assert req.action == "open_trade"
    assert req.amount_usd == 5.0

def test_believe_request():
    req = BelieveRequest(claim="XAUUSD volatile", evidence="session-1", strength=0.4)
    assert 0.0 <= req.strength <= 1.0
