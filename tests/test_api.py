"""Smoke-Tests: Auth, Netzwerkschutz, Kern-Endpunkte."""


def test_gui_ohne_login_erreichbar(test_env):
    assert test_env.get("/").status_code == 200


def test_api_ohne_login_gesperrt(test_env):
    for p in ("/api/mandates", "/api/settings", "/api/fristen",
              "/api/vorlagen", "/api/rvg"):
        r = test_env.get(p) if p != "/api/rvg" else test_env.post(
            p, json={"streitwert": 1000, "satz": 1.3})
        assert r.status_code == 401, p


def test_login_falsch_schlaegt_fehl(test_env):
    r = test_env.post("/api/login", json={"username": "x", "password": "y"})
    assert r.status_code == 401


def test_login_und_rollen(client):
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["role"] == "admin"  # erster Account wird Admin
    # Nutzer registrieren + Rolle
    assert client.post("/api/users", json={"username": "anna", "role": "nutzer"}).json()["ok"]
    assert client.post("/api/users/role", json={"username": "anna", "role": "admin"}).json()["ok"]
    users = client.get("/api/users").json()
    assert users["anna"]["role"] == "admin"


def test_fremdes_netz_gesperrt(test_env):
    from fastapi.testclient import TestClient
    from feeagent import server
    fremd = TestClient(server.app, client=("10.9.9.9", 1))
    assert fremd.get("/").status_code == 403
    assert fremd.get("/api/mandates").status_code == 403


def test_mandat_anlegen_archivieren_liste(client):
    assert client.post("/api/mandates", json={"slug": "tf", "anzeigename": "T"}).json()["ok"]
    assert [m["slug"] for m in client.get("/api/mandates").json()] == ["tf"]
    r = client.delete("/api/mandates/tf")
    assert r.json()["ok"] and "archiv" in r.json()["archiv"]
    assert client.get("/api/mandates").json() == []


def test_slug_traversal_geblockt(client):
    # Mandat mit ../ anlegen darf nicht außerhalb landen
    r = client.post("/api/mandates", json={"slug": "../../tmp/evil", "anzeigename": "x"})
    assert r.json()["ok"]
    assert "/tmp/evil" not in r.json()["pfad"]
