import copy
import pytest
from fastapi.testclient import TestClient
from backend.app.main import app

PUBLISHER = {"X-Admin-Token": "test-publisher"}
EDITOR = {"X-Admin-Token": "test-editor"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as client:
        yield client


def test_seeded_products(client):
    assert client.get("/health").json()["status"] == "ok"
    assert len(client.get("/products").json()) == 4


def test_calculate_idempotency_and_replay(client):
    body = {"product_id": "car_rental_standard", "context": {}}
    headers = {"Idempotency-Key": "test-calculation"}
    first = client.post("/pricing/calculate", json=body, headers=headers)
    assert first.status_code == 200, first.text
    assert float(first.json()["final_price"]) == 14900
    assert client.post("/pricing/calculate", json=body, headers=headers).json() == first.json()
    changed = {**body, "context": {"rental_days": 3}}
    assert client.post("/pricing/calculate", json=changed, headers=headers).status_code == 409
    replay = client.post(f"/pricing/history/{first.json()['decision_id']}/replay")
    assert replay.json()["matches"]


def test_new_domain_lifecycle(client):
    cfg = copy.deepcopy(client.get("/strategies/car_rental/versions").json()[0]["config"])
    cfg["id"] = "new_domain_api_test"
    cfg["name"] = "New domain"
    assert client.post("/strategies", json=cfg).status_code == 403
    assert client.post("/strategies", json=cfg, headers=EDITOR).status_code == 201
    path = "/strategies/new_domain_api_test"
    assert client.post(path + "/publish", json={"version": 1}, headers=PUBLISHER).status_code == 409
    assert client.post(path + "/approve", json={"version": 1}, headers=EDITOR).status_code == 403
    assert client.post(path + "/approve", json={"version": 1}, headers=PUBLISHER).status_code == 200
    assert client.post(path + "/publish", json={"version": 1}, headers=PUBLISHER).status_code == 200
    p = {"id": "new_product_api_test", "name": "New product", "strategy_id": cfg["id"], "base_rate": "2000", "defaults": {}}
    assert client.post("/products", json=p, headers=EDITOR).status_code == 201
    assert client.post("/pricing/calculate", json={"product_id": p["id"], "context": {}}).status_code == 200


def test_failed_tests_block_approval(client):
    cfg = client.get("/strategies/hospitality/versions").json()[0]["config"]
    cfg["scenarios"][0]["expected_price"] = "1"
    created = client.post("/strategies/hospitality/versions", json=cfg, headers=EDITOR)
    assert created.status_code == 201
    assert client.post("/strategies/hospitality/approve", json={"version": created.json()["version"]}, headers=PUBLISHER).status_code == 422


def test_simulations_do_not_add_transactions(client):
    total = client.get("/pricing/history").json()["total"]
    cfg = client.get("/strategies/car_rental/versions").json()[0]["config"]
    body = {"strategy_id": "car_rental", "version": 1, "scenarios": cfg["scenarios"]}
    r = client.post("/pricing/simulate", json=body)
    assert r.status_code == 200, r.text
    assert all(x["passed"] for x in r.json()["results"])
    assert client.get("/pricing/history").json()["total"] == total
    comparison = client.post("/pricing/compare", json={**body, "baseline_version": 1, "disabled_rule_ids": ["weekly_suv"]})
    assert comparison.status_code == 200
    assert comparison.json()["changed_count"] > 0


def test_replay_uses_product_snapshot(client):
    body = {"product_id": "car_rental_standard", "context": {}}
    r = client.post("/pricing/calculate", json=body).json()
    p = next(p for p in client.get("/products").json() if p["id"] == body["product_id"])
    update = {k: p[k] for k in ["id", "name", "strategy_id", "base_rate", "defaults"]}
    update["base_rate"] = "2500"
    assert client.put("/products/" + p["id"], json=update, headers=EDITOR).status_code == 200
    assert client.post(f"/pricing/history/{r['decision_id']}/replay").json()["matches"]


def test_bad_context_rejected(client):
    r = client.post("/pricing/calculate", json={"product_id": "car_rental_standard", "context": {"rental_days": "eight"}})
    assert r.status_code == 422


def test_ai_without_key_is_explicitly_unavailable(client):
    cfg = client.get("/strategies/car_rental/versions").json()[0]["config"]
    r = client.post("/assistant/draft", json={"instruction": "Change the discount to 12 percent", "config": cfg}, headers=EDITOR)
    assert r.status_code == 503
