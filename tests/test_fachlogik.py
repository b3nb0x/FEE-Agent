"""Fachlogik-Tests: Fristen, Zeiten/Rechnungen, RVG, Vorlagen, Portal, E-Mail."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _mandat(client, slug="tf"):
    client.post("/api/mandates", json={"slug": slug, "anzeigename": "T"})


def test_fristen_und_wiedervorlage(client):
    _mandat(client)
    assert client.post("/api/mandates/tf/fristen",
                       json={"datum": "2020-01-01", "text": "alt"}).status_code == 200
    assert client.post("/api/mandates/tf/fristen",
                       json={"datum": "2027-01-01", "text": "neu"}).status_code == 200
    # falsches Datum abgelehnt
    assert client.post("/api/mandates/tf/fristen",
                       json={"datum": "1.1.2027", "text": "x"}).status_code == 400
    alle = client.get("/api/fristen").json()
    assert len(alle) == 2
    assert alle[0]["ueberfaellig"] is True and alle[1]["ueberfaellig"] is False
    # erledigt markieren
    fid = alle[1]["id"]
    assert client.post(f"/api/mandates/tf/fristen/{fid}/erledigt").json()["ok"]


def test_zeiten_abrechnen_rechnung(client):
    _mandat(client)
    client.post("/api/mandates/tf/zeiten",
                json={"datum": "2026-11-19", "minuten": 90, "text": "Beratung"})
    # 0 Minuten abgelehnt
    assert client.post("/api/mandates/tf/zeiten",
                       json={"datum": "2026-11-19", "minuten": 0, "text": "x"}).status_code == 400
    client.post("/api/settings", json={"endpoint": "http://x/v1", "model": "",
                                       "api_key": "", "stundensatz": "120"})
    # ohne Abrechnung keine Rechnung
    assert client.post("/api/mandates/tf/rechnungen").status_code == 400
    client.post("/api/mandates/tf/zeiten/abrechnen")
    r = client.post("/api/mandates/tf/rechnungen")
    assert r.status_code == 200
    assert r.json()["summe_min"] == 90
    assert r.json()["betrag"] == 180.0  # 1,5 h × 120 €
    rid = r.json()["id"]
    assert client.get(f"/api/mandates/tf/rechnungen/{rid}").json()["betrag"] == 180.0
    assert client.get(f"/api/mandates/tf/rechnungen/{rid}/druck").status_code == 200
    # zweite Rechnung ohne offene Zeiten schlägt fehl
    assert client.post("/api/mandates/tf/rechnungen").status_code == 400


def test_rvg_gebuehren(client):
    r = client.post("/api/rvg", json={"streitwert": 10000, "satz": 1.3, "ust": True})
    assert r.status_code == 200
    j = r.json()
    assert j["stufe"] == 1947 and j["betrag"] == 2531.10
    assert j["betrag_inkl_ust"] == 3012.01
    assert client.post("/api/rvg",
                       json={"streitwert": 10_000_000, "satz": 1.3}).status_code == 400


def test_vorlagen(client):
    assert client.post("/api/vorlagen", json={"name": "Mahnung", "text": "Hallo"}).json()["ok"]
    assert client.post("/api/vorlagen", json={"name": "Mahnung", "text": "Neu"}).json()["ok"]
    vs = client.get("/api/vorlagen").json()
    assert vs[0]["text"] == "Neu"  # Überschreiben
    name = vs[0]["name"]
    assert client.delete(f"/api/vorlagen/{name}").json()["ok"]
    assert client.get("/api/vorlagen").json() == []


def test_kontakte_und_notizen(client):
    _mandat(client)
    assert client.post("/api/mandates/tf/kontakte",
                       json={"rolle": "gegner", "name": "X", "kontakt": "@"}).status_code == 200
    assert client.post("/api/mandates/tf/kontakte",
                       json={"rolle": "falsch", "name": "X"}).status_code == 400
    ks = client.get("/api/mandates/tf/kontakte").json()
    assert ks[0]["name"] == "X"
    assert client.delete(f"/api/mandates/tf/kontakte/{ks[0]['id']}").json()["ok"]
    client.post("/api/mandates/tf/notes", json={"typ": "telefonat", "inhalt": "Ruf"})
    ns = client.get("/api/mandates/tf/notes").json()
    assert len(ns) == 1
    assert client.delete(f"/api/mandates/tf/notes/{ns[0]['id']}").json()["ok"]


def test_portal_token(client):
    _mandat(client)
    url = client.post("/api/mandates/tf/portal").json()["url"]
    from fastapi.testclient import TestClient
    from feeagent import server
    c2 = TestClient(server.app, client=("10.0.0.51", 9))
    assert c2.get(url).status_code == 200          # ohne Login ok (Token = Auth)
    assert c2.get("/portal/falsch").status_code == 404


def test_email_import_mit_anhang(tmp_path):
    from email.message import EmailMessage
    import feeagent.ocr as ocr

    inner = EmailMessage()
    inner["Subject"] = "Stellungnahme"
    inner.set_content("Frist: 15.03.2027.")
    msg = EmailMessage()
    msg["Subject"] = "Wichtig"
    msg.set_content("Siehe Anhang.")
    msg.add_attachment(bytes(inner), maintype="message", subtype="rfc822",
                       filename="sn.eml")
    eml = tmp_path / "mail.eml"
    eml.write_bytes(bytes(msg))
    md = tmp_path / "mandat"
    md.mkdir()
    r = ocr.process_document(eml, md)
    assert r["ok"] and len(r["anhaenge"]) == 1
    txt = (md / "dokumente" / "sn.txt").read_text()
    assert "Stellungnahme" in txt and "15.03.2027" in txt


def test_llm_chat_content_als_liste(monkeypatch):
    """Provider liefern content teils als Blockliste statt String (Claude-kompatibel)."""
    import json as _json
    import urllib.request
    import feeagent.agent as agent

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return _json.dumps({"choices": [{"message": {"content": [
                {"type": "text", "text": "ok"}]}}]}).encode()

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResp())
    assert agent.llm_chat("http://x/v1", "m", "s", "u") == "ok"


def test_fristen_extraktion():
    from datetime import date
    from feeagent.fristen import extrahieren
    t = ("Zahlung bis 15.03.2027. Widerspruch innerhalb von 2 Wochen "
         "ab Zugang (Zugang: 01.11.2026). Klagefrist: 2026-12-31.")
    erg = {f["datum"] for f in extrahieren(t, date(2026, 11, 1))}
    assert "2027-03-15" in erg      # absolut
    assert "2026-12-31" in erg      # ISO
    assert "2026-11-15" in erg      # 01.11. + 2 Wochen


def test_upload_erstellt_fristen_automatisch(client, tmp_path):
    _mandat(client)
    # txt-Dokument mit Frist hochladen
    f = tmp_path / "brief.txt"
    f.write_text("Sehr geehrte Damen und Herren, Zahlung bis 15.03.2027 fällig.")
    r = client.post("/api/mandates/tf/documents",
                    files={"file": ("brief.txt", f.read_bytes(), "text/plain")})
    assert r.status_code == 200
    fr = client.get("/api/mandates/tf/fristen").json()
    assert any(x["datum"] == "2027-03-15" and "auto:" in x["text"] for x in fr)
    # Duplikat: derselbe Upload nochmal → keine Doppelung
    client.post("/api/mandates/tf/documents",
                files={"file": ("brief.txt", f.read_bytes(), "text/plain")})
    fr2 = client.get("/api/mandates/tf/fristen").json()
    assert len([x for x in fr2 if x["datum"] == "2027-03-15"]) == 1


def test_meta_aktenzeichen_auto(client, tmp_path):
    _mandat(client)
    f = tmp_path / "brief.txt"
    f.write_text("Aktenzeichen: 123 C 456/26, Verhandlung am 15.03.2027")
    client.post("/api/mandates/tf/documents",
                files={"file": ("b.txt", f.read_bytes(), "text/plain")})
    r = client.post("/api/mandates/tf/meta/az-auto")
    assert r.status_code == 200 and "123 C 456/26" in r.json()["aktenzeichen"]
    assert client.get("/api/mandates/tf/meta").json()["aktenzeichen"] == "123 C 456/26"
    # manuell setzen
    client.post("/api/mandates/tf/meta", json={"aktenzeichen": "999 O 1/27", "bemerkung": "x"})
    assert client.get("/api/mandates/tf/meta").json()["aktenzeichen"] == "999 O 1/27"


def test_termine(client):
    _mandat(client)
    r = client.post("/api/termine", json={"mandate": "tf", "datum": "2027-01-10",
                                           "uhrzeit": "10:00", "titel": "Gerichtstermin"})
    assert r.status_code == 200
    assert client.post("/api/termine", json={"mandate": "", "datum": "bad", "titel": "x"}).status_code == 400
    ts = client.get("/api/termine?bis=2027-12-31").json()
    assert ts[0]["titel"] == "Gerichtstermin"
    assert client.delete(f"/api/termine/{ts[0]['id']}").json()["ok"]


def test_zahlstatus(client):
    _mandat(client)
    client.post("/api/mandates/tf/zeiten", json={"datum": "2026-11-19", "minuten": 60, "text": "t"})
    client.post("/api/mandates/tf/zeiten/abrechnen")
    client.post("/api/settings", json={"endpoint": "http://x/v1", "model": "", "api_key": "", "stundensatz": "100"})
    rid = client.post("/api/mandates/tf/rechnungen").json()["id"]
    assert client.get(f"/api/mandates/tf/rechnungen/{rid}").json()["zahlstatus"] == "offen"
    r = client.post(f"/api/mandates/tf/rechnungen/{rid}/zahlung?status=bezahlt")
    assert r.json()["zahlstatus"] == "bezahlt" and r.json()["gezahlt_am"]
    r = client.post(f"/api/mandates/tf/rechnungen/{rid}/zahlung?status=mahnung")
    assert r.json()["zahlstatus"] == "mahnung"


def test_bea_outbox_und_inbox(client, tmp_path, monkeypatch):
    _mandat(client)
    # Outbox: Entwurf anlegen
    r = client.post("/api/mandates/tf/bea/outbox",
                    json={"titel": "Klage", "text": "Sehr geehrte...", "empfaenger": "vg@bea"})
    assert r.status_code == 200 and r.json()["nr"]
    liste = client.get("/api/mandates/tf/bea/outbox").json()
    assert liste[0]["titel"] == "Klage"
    # Inbox: beA-Client-Ordner simulieren
    import feeagent.bea as bea
    inbox = tmp_path / "bea-inbox"; inbox.mkdir()
    (inbox / "gericht.eml").write_text(
        "From: Gericht\nSubject: Ladung\n\nTermin 15.03.2027, Frist bis 01.04.2027")
    r = client.post("/api/mandates/tf/bea/inbox")
    # ohne Konfig zeigt er auf ~/bea-inbox – hier direkt Funktion testen:
    res = bea.posteingang_importieren(_mandat_dir(client), inbox)
    assert res["ok"] and res["neu"] == 1
    # Auto-Fristen aus der importierten beA-Nachricht (wie im API-Endpunkt):
    import feeagent.fristen as ff, feeagent.db as db
    ff.auto_eintragen(_mandat_dir(client), "tf", db)
    fr = client.get("/api/mandates/tf/fristen").json()
    assert any(f["datum"] == "2027-04-01" for f in fr)


def _mandat_dir(client):
    import feeagent.agent as agent
    return agent.MANDATE_DIR / "tf"


def test_kollision_und_vorfrist_und_suche_export(client, tmp_path):
    _mandat(client, "alt")
    client.post("/api/mandates/alt/kontakte",
                json={"rolle": "gegner", "name": "Muster GmbH", "kontakt": ""})
    _mandat(client, "neu")
    # Kollision: gleicher Gegner im anderen Mandat
    r = client.post("/api/mandates/neu/kontakte",
                    json={"rolle": "gegner", "name": "Muster GmbH"})
    assert r.json()["kollision"] == [{"mandate": "alt", "gegner": "Muster GmbH"}]
    # Vorfrist: Frist + 7 Tage vorher automatisch
    client.post("/api/mandates/neu/fristen",
                json={"datum": "2027-03-15", "text": "Klage", "vorfrist_tage": 7})
    fr = {f["datum"] for f in client.get("/api/mandates/neu/fristen").json()}
    assert "2027-03-15" in fr and "2027-03-08" in fr
    # Globale Suche über Mandatsdokumente
    f = tmp_path / "doc.txt"
    f.write_text("Besonderheit: Schadensersatz 5.000 EUR gefordert")
    client.post("/api/mandates/neu/documents",
                files={"file": ("doc.txt", f.read_bytes(), "text/plain")})
    erg = client.get("/api/suche?q=Schadensersatz").json()
    assert erg and erg[0]["mandate"] == "neu"
    # Export enthält alle Tabellen
    ex = client.get("/api/export").json()
    assert "fristen" in ex["daten"] and "rechnungen" in ex["daten"]
