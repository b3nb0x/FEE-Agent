"""FEE-Agent auth – Anmeldung per PC-Konto (PAM), Sitzungen, Rollen.

Nutzer/Rollen liegen in der SQLite-DB (feeagent/db.py). Der erste
angemeldete Account wird automatisch Admin und darf in der GUI weitere
PC-Konten registrieren und Rollen vergeben (admin | nutzer).
"""
import secrets
import threading

from . import db

SESSIONS: dict = {}  # token -> {"user", "role"}
_lock = threading.Lock()


def pam_check(user: str, password: str) -> bool:
    """PC-Konto gegen Linux-PAM prüfen. Benötigt Leserechte auf /etc/shadow:
    als Root starten oder GUI-Nutzer in die Gruppe 'shadow' aufnehmen."""
    try:
        import pam
        return bool(user) and pam.pam().authenticate(user, password)
    except Exception:
        return False


def login(user: str, password: str) -> dict | None:
    users = db.load_users()
    if not pam_check(user, password):
        return None
    if user not in users:  # erster Account wird Admin (Bootstrap)
        role = "admin" if not users else "nutzer"
        users[user] = {"role": role}
        db.save_users(users)
    role = users[user]["role"]
    with _lock:
        token = secrets.token_hex(32)
        SESSIONS[token] = {"user": user, "role": role}
    return {"token": token, "user": user, "role": role}


def session(token: str) -> dict | None:
    return SESSIONS.get(token)


def logout(token: str) -> None:
    SESSIONS.pop(token, None)


load_users = db.load_users  # kompatibilität für server.py


def register(user: str, role: str) -> bool:
    """PC-Konto vorab registrieren (Admin-Funktion)."""
    users = db.load_users()
    if not user or role not in ("admin", "nutzer"):
        return False
    users.setdefault(user, {"role": role})
    db.save_users(users)
    return True


def set_role(user: str, role: str) -> bool:
    users = db.load_users()
    if user not in users or role not in ("admin", "nutzer"):
        return False
    users[user]["role"] = role
    db.save_users(users)
    return True


def remove(user: str) -> bool:
    users = db.load_users()
    if user not in users:
        return False
    del users[user]
    db.save_users(users)
    return True
