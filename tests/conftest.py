"""FEE-Agent Test-Fixtures: isolierte DB + Mandatsverzeichnis + PAM-Mock."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def test_env(tmp_path, monkeypatch):
    import feeagent.db as db
    import feeagent.agent as agent
    import feeagent.auth as auth

    db.DB_PATH = tmp_path / "feeagent.db"
    db.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    agent.MANDATE_DIR = tmp_path / "mandate"
    agent.MANDATE_DIR.mkdir()
    monkeypatch.setattr(auth, "pam_check", lambda u, p: u == "b3n" and p == "test")

    from fastapi.testclient import TestClient
    from feeagent import server
    client = TestClient(server.app, client=("10.0.0.51", 5))
    return client


@pytest.fixture()
def client(test_env):
    """Eingeloggter Test-Client (b3n/test)."""
    test_env.post("/api/login", json={"username": "b3n", "password": "test"})
    return test_env
