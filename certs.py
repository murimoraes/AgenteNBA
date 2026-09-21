"""
Compatibilidade TLS.

Antivirus com inspecao HTTPS (Norton, Kaspersky, ESET) e proxies corporativos
substituem o certificado dos sites por um emitido por uma CA propria, instalada
no store do Windows. O `requests` nao le esse store -- ele usa o bundle do
`certifi` -- e por isso falha com CERTIFICATE_VERIFY_FAILED mesmo com a rede OK.

A correcao aqui NAO desliga a verificacao: ela monta um bundle = certifi + raizes
confiaveis do Windows e aponta o requests para ele. Em Linux/macOS (Streamlit
Cloud, Railway) a funcao detecta que o padrao ja funciona e nao faz nada.
"""

from __future__ import annotations

import os
import socket
import ssl
import tempfile
from pathlib import Path

import certifi

_CA_ENV_VARS = ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE")
_PROBE_HOST = "cdn.nba.com"
_applied = False


def _default_verification_works(host: str = _PROBE_HOST, timeout: int = 8) -> bool:
    """Testa se o bundle do certifi ja valida a cadeia apresentada pela rede."""
    try:
        ctx = ssl.create_default_context(cafile=certifi.where())
        with socket.create_connection((host, 443), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host):
                return True
    except Exception:
        return False


def _build_bundle(dest: Path) -> Path | None:
    """certifi + raizes do store do Windows num unico arquivo PEM."""
    if not hasattr(ssl, "enum_certificates"):  # nao-Windows
        return None

    blocks = [Path(certifi.where()).read_text(encoding="utf-8")]
    added = 0
    for store in ("ROOT", "CA"):
        try:
            for der, _enc, trust in ssl.enum_certificates(store):
                if trust is False:  # explicitamente nao-confiavel
                    continue
                try:
                    blocks.append(ssl.DER_cert_to_PEM_cert(der))
                    added += 1
                except Exception:
                    continue
        except Exception:
            continue

    if not added:
        return None

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(blocks), encoding="utf-8")
    return dest


def ensure_tls() -> str | None:
    """
    Garante que requests/nba_api consigam validar HTTPS nesta maquina.

    Retorna o caminho do bundle usado, ou None se o padrao ja bastava.
    Idempotente: so executa o trabalho na primeira chamada do processo.
    """
    global _applied
    if _applied:
        return os.environ.get("REQUESTS_CA_BUNDLE")

    _applied = True

    # 1) Bundle explicito do usuario tem prioridade.
    override = os.environ.get("NBA_CA_BUNDLE")
    if override and Path(override).is_file():
        for var in _CA_ENV_VARS:
            os.environ[var] = override
        return override

    # 2) Se o certifi ja valida a cadeia, nao mexe em nada.
    if _default_verification_works():
        return None

    # 3) Monta (ou reaproveita) o bundle combinado.
    cached = Path(tempfile.gettempdir()) / "nba_scout" / "ca-bundle.pem"
    bundle = cached if cached.is_file() else _build_bundle(cached)
    if bundle is None:
        return None

    for var in _CA_ENV_VARS:
        os.environ[var] = str(bundle)
    return str(bundle)
