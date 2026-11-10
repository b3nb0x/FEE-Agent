"""FEE-Agent headroom – Ressourcen-Schutz für schwere Jobs.

Vorbild: Hermes-Plugin 'headroom'. Schwere Jobs (OCR, LibreOffice) laufen
nur bei genug freiem RAM, eine nach der anderen, mit Timeout – der Agent
bleibt am Leben.
"""
import os
import queue
import threading
import time

MIN_FREE_MB = int(os.environ.get("FEE_HEADROOM_MIN_MB", "400"))
JOB_TIMEOUT_S = int(os.environ.get("FEE_HEADROOM_TIMEOUT", "300"))

_job_q: "queue.Queue" = queue.Queue()
_lock = threading.Lock()
_running = False
_events: list = []


def _meminfo() -> dict:
    try:
        with open("/proc/meminfo") as f:
            info = {}
            for line in f:
                k, v = line.split(":", 1)
                info[k.strip()] = int(v.strip().split()[0])  # kB
        return {
            "total_mb": info.get("MemTotal", 0) // 1024,
            "free_mb": (info.get("MemAvailable", info.get("MemFree", 0))) // 1024,
        }
    except Exception:  # noqa: BLE001 – nicht-Linux: keine Begrenzung
        return {"total_mb": 0, "free_mb": 99999}


def _log(event: str, detail: str = "") -> None:
    _events.append({"t": round(time.time(), 2), "event": event, "detail": detail})
    if len(_events) > 200:
        del _events[:100]


def status() -> dict:
    m = _meminfo()
    return {
        **m,
        "min_free_mb": MIN_FREE_MB,
        "queue_length": _job_q.qsize(),
        "running": _running,
        "events": _events[-10:],
    }


def _worker() -> None:
    global _running
    while True:
        fn, args, kwargs, result_holder = _job_q.get()
        # Warten auf genug freien Speicher (max. 60 s, dann trotzdem starten)
        waited = 0
        while _meminfo()["free_mb"] < MIN_FREE_MB and waited < 60:
            time.sleep(2)
            waited += 2
        if waited >= 60 and _meminfo()["free_mb"] < MIN_FREE_MB:
            _log("refused", "zu wenig RAM")
            result_holder["error"] = (
                f"Zu wenig freier Speicher ({_meminfo()['free_mb']} MB < "
                f"{MIN_FREE_MB} MB). Job abgelehnt – später erneut versuchen "
                "oder kleinere Dokumente verarbeiten.")
            _job_q.task_done()
            continue
        _running = True
        _log("start", str(getattr(fn, "__name__", fn)))
        try:
            result_holder["result"] = fn(*args, **kwargs)
            _log("done")
        except Exception as e:  # noqa: BLE001
            result_holder["error"] = str(e)
            _log("error", str(e))
        finally:
            _running = False
            _job_q.task_done()


threading.Thread(target=_worker, daemon=True).start()


def run_heavy(fn, *args, **kwargs):
    """Führt einen schweren Job über die Queue aus (blockierend, thread-sicher)."""
    holder: dict = {}
    _job_q.put((fn, args, kwargs, holder))
    while "result" not in holder and "error" not in holder:
        time.sleep(0.1)
    if "error" in holder:
        raise RuntimeError(holder["error"])
    return holder["result"]
