"""FEE-Agent auth – Anmeldung per PC-Konto (PAM), Sitzungen, Rollen.

Nutzer melden sich mit ihrem Linux-Konto an (python-pam). Der erste
angemeldete Account wird automatisch Admin und darf in der GUI weitere
PC-Konten registrieren und Rollen vergeben (admin | nutzer).
"""
import json
import secrets
import threading
from pathlib import Path

USERS_FILE = Path.home() / ".config" / "fee-agent" / "users.json"
# Alte Lage (im Repo) migrieren, falls vorhanden
_OLD_USERS = Path(__file__).resolve().parent / "users.json"
if _OLD_USERS.exists():
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _OLD_USERS.rename(USERS_FILE)
SESSIONS: dict = {}  # token -> {"user", "role"}
_lock = threading.Lock()


def load_users() -> dict:
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    return {}


def save_users(users: dict) -> None:
    USERS_FILE.write_text(json.dumps(users, indent=1), encoding="utf-8")


def pam_check(user: str, password: str) -> bool:
    """PC-Konto gegen Linux-PAM prüfen. Benötigt Leserechte auf /etc/shadow:
    als Root starten oder GUI-Nutzer in die Gruppe 'shadow' aufnehmen."""
    try:
        import pam
        return bool(user) and pam.pam().authenticate(user, password)
    except Exception:
        return False


def login(user: str, password: str) -> dict | None:
    users = load_users()
    if not pam_check(user, password):
        return None
    if user not in users:  # erster Account wird Admin (Bootstrap)
        users[user] = {"role": "admin" if not users else "nutzer"}
        save_users(users)
    role = users[user]["role"]
    with _lock:
        token = secrets.token_hex(32)
        SESSIONS[token] = {"user": user, "role": role}
    return {"token": token, "user": user, "role": role}


def session(token: str) -> dict | None:
    return SESSIONS.get(token)


def logout(token: str) -> None:
    SESSIONS.pop(token, None)


def register(user: str, role: str) -> bool:
    """PC-Konto vorab registrieren (Admin-Funktion)."""
    users = load_users()
    if not user or role not in ("admin", "nutzer"):
        return False
    users.setdefault(user, {"role": role})
    save_users(users)
    return True


def set_role(user: str, role: str) -> bool:
    users = load_users()
    if user not in users or role not in ("admin", "nutzer"):
        return False
    users[user]["role"] = role
    save_users(users)
    return True


def remove(user: str) -> bool:
    users = load_users()
    if user not in users:
        return False
    del users[user]
    save_users(users)
    return True
