"""Snake Charmer is served at /ui (or a build hint when the bundle is missing)."""

from __future__ import annotations


def test_ui_route_always_answers(make_client):
    import httpx

    client = make_client(lambda req: httpx.Response(200, json={}))
    r = client.get("/ui/", follow_redirects=True)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Snake Charmer" in r.text or "<div id=\"app\">" in r.text


def test_dashboard_links_to_ui(make_client):
    import httpx

    client = make_client(lambda req: httpx.Response(200, json={}))
    assert 'href="/ui/"' in client.get("/").text
