"""Téléchargement avec cache disque, et choix du magasin de certificats TLS."""
from __future__ import annotations

import hashlib
import re

import requests

# --- Certificats TLS ---------------------------------------------------------------------
# 1) truststore : utilise le magasin de certificats du système (Windows / macOS / OpenSSL).
#    `pip install truststore`.
# 2) sinon variable REQUESTS_CA_BUNDLE=chemin\vers\ca.pem (mécanisme standard requests)
try:
    import truststore  # type: ignore

    truststore.inject_into_ssl()
    TLS_MODE = "truststore (magasin système)"
except ImportError:
    TLS_MODE = "certifi (bundle Python)"

from prix_energie.config import CACHE_DIR
from prix_energie.journal import log

# En-tête strictement ASCII : un « é » dans le User-Agent faisait répondre 403 au
# pare-feu de data.gouv.fr (les en-têtes HTTP ne sont pas censés sortir du latin-1).
# Ne pas y remettre d'accent ni d'apostrophe typographique.
UA = {"User-Agent": "energie-prix-fr/1.0 (script d'agregation de statistiques publiques)"}


class DownloadError(RuntimeError):
    pass


def fetch(url: str, *, binary: bool = True, offline: bool = False, timeout: int = 90,
          ok_404: bool = False) -> bytes | None:
    """Télécharge `url` (ou relit le cache). Retourne None si 404 et ok_404."""
    CACHE_DIR.mkdir(exist_ok=True)
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", url.split("/")[-1].split("?")[0])[:60] or "index"
    path = CACHE_DIR / f"{key}_{stem}"
    if path.exists():
        return path.read_bytes()
    if offline:
        raise DownloadError(f"hors-ligne et absent du cache : {url}")
    log.info("GET %s", url)
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
    except requests.exceptions.SSLError as e:
        raise DownloadError(
            f"Erreur TLS sur {url} ({TLS_MODE}) : "
            "`pip install truststore`, ou REQUESTS_CA_BUNDLE=<chemin vers une CA .pem>."
        ) from e
    except requests.exceptions.RequestException as e:
        raise DownloadError(f"Réseau : {e}") from e
    if r.status_code == 404 and ok_404:
        return None
    if r.status_code >= 400:
        raise DownloadError(f"HTTP {r.status_code} pour {url}")
    path.write_bytes(r.content)
    return r.content
