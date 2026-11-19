"""FEE-Agent netconfig – erkanntes Netzwerk freigeben, andere sperren.

Beim Start wird das lokale Interface ermittelt (IP + Subnetz). Der Server
bindet an alle Interfaces, die Middleware lässt nur Clients aus den
vertrauten Netzen zu. Default: erkanntes /24 + Docker-Bridge-Bereiche
(172.16.0.0/12, 192.168.0.0/16 – Container-NAT-Adressen).
Zusätzlich per Env: FEE_TRUSTED_NETS="10.0.0.0/24,192.168.1.0/24".
"""
import os
import socket

_PREFIX_LEN = 24
_DOCKER_NETS = ("172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
                "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
                "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.",
                "192.168.")


def _trusted_prefixes(subnetz_ip: str) -> list:
    """Präfixe, die erlaubt sind: erkanntes Netz + Docker + Env-Liste."""
    base = subnetz_ip.rsplit(".", 1)[0] + "."
    prefixes = [base] + [p for p in _DOCKER_NETS]
    extra = os.environ.get("FEE_TRUSTED_NETS", "")
    for eintrag in extra.split(","):
        eintrag = eintrag.strip()
        if eintrag:
            # "10.1.2.0/24" → Präfix "10.1.2." ; "10.1.2.3" → "10.1.2."
            net = eintrag.split("/")[0]
            prefixes.append(net.rsplit(".", 1)[0] + ".")
    return prefixes


def lan_info() -> dict:
    # Im Docker-Container wäre die eigene IP die Docker-Bridge (172.18.x) –
    # deshalb Host-IP per Env vorgeben: FEE_HOST_IP=<NAS/LAN-IP>
    env_ip = os.environ.get("FEE_HOST_IP", "").strip()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = env_ip or s.getsockname()[0]
    except OSError:
        ip = env_ip or "127.0.0.1"
    finally:
        s.close()
    return {"ip": ip, "subnetz": ip.rsplit(".", 1)[0] + ".0/" + str(_PREFIX_LEN)}


def client_allowed(client_ip: str, subnetz_ip: str) -> bool:
    if client_ip.startswith("127."):
        return True
    return any(client_ip.startswith(p) for p in _trusted_prefixes(subnetz_ip))
