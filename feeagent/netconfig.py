"""FEE-Agent netconfig – erkanntes Netzwerk freigeben, andere sperren.

Beim Start wird das lokale Interface ermittelt (IP + Subnetz). Der Server
bindet an alle Interfaces (damit das LAN die GUI erreicht), die Middleware
lässt aber nur Clients aus dem erkannten Subnetz und localhost zu.
"""
import socket

# shortcut: Subnetz hart als /24 angenommen; bei fremder Netzmaskierung erweitern
_PREFIX_LEN = 24


def lan_info() -> dict:
    """Ermittelt IP + Subnetz des Interface mit Default-Route."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # kein Verkehr, nur Routing ermitteln
        ip = s.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        s.close()
    return {"ip": ip, "subnetz": ip.rsplit(".", 1)[0] + ".0/" + str(_PREFIX_LEN)}


def client_allowed(client_ip: str, subnetz_ip: str) -> bool:
    if client_ip.startswith("127."):
        return True
    return client_ip.startswith(subnetz_ip.rsplit(".", 1)[0] + ".")
