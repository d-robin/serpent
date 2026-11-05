"""The live API contract that apps and AI assistants read."""

from __future__ import annotations

import httpx

from tests.conftest import ADMIN, CLIENT, READ


def _provider(client, slug, base, **extra):
    r = client.post("/admin/providers", headers=ADMIN, json={"slug": slug, "base_url": base, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _client(make_client):
    return make_client(lambda req: httpx.Response(200, json={}))


def test_contract_needs_a_client_key(make_client):
    client = _client(make_client)
    assert client.get("/v1/contract").status_code == 401
    assert client.get("/v1/contract", headers=READ).status_code == 403
    assert client.get("/v1/contract", headers=CLIENT).status_code == 200


def test_contract_describes_serpapi_google_and_amazon(make_client):
    client = _client(make_client)
    _provider(client, "serpapi", "", preset="serpapi")
    text = client.get("/v1/contract", headers=CLIENT).text
    assert "/p/serpapi/search" in text
    assert "engine=amazon&k=" in text and "`k` for the search words" in text
    assert "engine=google&q=" in text
    assert "Retry-After" in text and "429" in text


def test_contract_json_lists_routes_and_default(make_client):
    client = _client(make_client)
    _provider(client, "serper", "", preset="serper")
    _provider(client, "other", "https://other.test")
    doc = client.get("/v1/contract?format=json", headers=CLIENT).json()
    slugs = {r["slug"]: r for r in doc["routes"]}
    assert {"serper", "other"} <= set(slugs)
    assert slugs["serper"]["operations"][0]["method"] == "POST"
    assert slugs["other"]["operations"] == [] and "provider's" in slugs["other"]["notes"]
    assert doc["default_route"]["target"] in slugs


def test_contract_warns_about_mixed_chains(make_client):
    client = _client(make_client)
    _provider(client, "serpapi", "", preset="serpapi")
    _provider(client, "serper", "", preset="serper")
    r = client.post("/admin/chains", headers=ADMIN, json={"slug": "mix", "steps": ["serpapi", "serper"]})
    assert r.status_code == 201, r.text
    doc = client.get("/v1/contract?format=json", headers=CLIENT).json()
    chain = next(x for x in doc["routes"] if x["slug"] == "mix")
    assert "WARNING" in chain["notes"] and chain["operations"] == []


def test_contract_never_contains_secrets(make_client):
    client = _client(make_client)
    p = _provider(client, "serpapi", "", preset="serpapi")
    client.post("/admin/accounts", headers=ADMIN,
                json={"api_key": "SECRETKEY123", "label": "a", "quota_limit": 5, "provider_id": p["id"]})
    for fmt in ("markdown", "json"):
        body = client.get(f"/v1/contract?format={fmt}", headers=CLIENT).text
        assert "SECRETKEY123" not in body and "test-admin" not in body


def test_empty_router_says_so(make_client):
    from serpent import contract
    from serpent.config import Settings

    doc = contract.build(Settings(), [], [], "default", "http://x.test")
    assert "No provider is configured yet" in contract.render_markdown(doc)


def test_llms_txt_points_at_the_contract(make_client):
    txt = _client(make_client).get("/llms.txt")
    assert txt.status_code == 200 and "/v1/contract" in txt.text
