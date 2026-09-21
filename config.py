"""
Configuracao central: provider, credenciais, modelo e temporada.

O projeto fala o formato OpenAI de ponta a ponta, entao o provider e apenas um
`base_url` diferente. Trocar entre OpenRouter e OpenAI da OpenAI e questao de
preencher uma chave no .env -- nenhuma linha de codigo muda, e o loop do agente,
os schemas de tool e a interface continuam identicos.

Nada de chave ou modelo hardcoded: tudo vem de variavel de ambiente ou .env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI

import certs

load_dotenv()

APP_TITLE = "NBA Scouting Report"
APP_URL = os.getenv("OPENROUTER_APP_URL", "https://github.com/local/nba-scouting-report")


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    base_url: str
    key_env: str
    model_env: str
    default_model: str
    key_prefix: str


# Ordem importa: e a precedencia usada quando LLM_PROVIDER nao esta definido.
# A OpenAI vem primeiro porque preencher a chave dela e um ato deliberado --
# basta comentar a linha para voltar ao OpenRouter.
PROVIDERS: tuple[Provider, ...] = (
    Provider(
        name="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        key_env="OPENAI_API_KEY",
        model_env="OPENAI_MODEL",
        default_model="gpt-4o-mini",
        key_prefix="sk-",
    ),
    Provider(
        name="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        key_env="OPENROUTER_API_KEY",
        model_env="OPENROUTER_MODEL",
        default_model="nex-agi/nex-n2.5-mini:free",
        key_prefix="sk-or-",
    ),
)

_BY_NAME = {p.name: p for p in PROVIDERS}


class ConfigError(RuntimeError):
    """Configuracao ausente ou invalida."""


def _key_of(provider: Provider) -> str:
    return (os.getenv(provider.key_env) or "").strip()


def get_provider() -> Provider:
    """
    Provider ativo.

    LLM_PROVIDER manda, se definido. Sem ele, vale o primeiro da lista que tiver
    chave preenchida. Se nenhum tiver, devolve o OpenRouter para as mensagens de
    erro e a interface continuarem fazendo sentido.
    """
    forced = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if forced:
        if forced not in _BY_NAME:
            raise ConfigError(
                f"LLM_PROVIDER='{forced}' e invalido. "
                f"Use um de: {', '.join(_BY_NAME)}."
            )
        return _BY_NAME[forced]

    for provider in PROVIDERS:
        if _key_of(provider):
            return provider
    return _BY_NAME["openrouter"]


def get_base_url() -> str:
    """LLM_BASE_URL sobrepoe o padrao do provider (proxies, Azure, gateways)."""
    return (os.getenv("LLM_BASE_URL") or "").strip() or get_provider().base_url


def get_model() -> str:
    """
    Modelo do provider ativo.

    Cada provider tem sua propria variavel porque o formato do id difere: no
    OpenRouter e namespaced ('openai/gpt-4o'), na OpenAI e direto ('gpt-4o-mini').
    Assim trocar de provider nao exige mexer tambem no nome do modelo.
    """
    provider = get_provider()
    configured = (os.getenv(provider.model_env) or "").strip()
    return configured or provider.default_model


def get_api_key() -> str:
    provider = get_provider()
    key = _key_of(provider)
    if not key:
        raise ConfigError(
            f"{provider.key_env} nao encontrada para o provider '{provider.label}'. "
            f"Preencha {provider.key_env} no arquivo .env da raiz do projeto "
            "(veja .env.example)."
        )
    return key


def has_api_key() -> bool:
    return bool(_key_of(get_provider()))


def describe() -> dict[str, str]:
    """Resumo para a interface -- nunca inclui a chave."""
    provider = get_provider()
    return {
        "provider": provider.label,
        "model": get_model(),
        "base_url": get_base_url(),
        "key_env": provider.key_env,
        "key_status": "configurada" if has_api_key() else "ausente",
    }


@lru_cache(maxsize=1)
def _client_for(base_url: str, api_key: str, provider_name: str) -> OpenAI:
    # HTTP-Referer / X-Title so fazem sentido no OpenRouter (ranking publico de
    # apps). A OpenAI ignora headers desconhecidos, mas nao ha motivo para enviar.
    headers = (
        {"HTTP-Referer": APP_URL, "X-Title": APP_TITLE}
        if provider_name == "openrouter"
        else None
    )
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        default_headers=headers,
        timeout=120.0,
        max_retries=2,
    )


def get_client() -> OpenAI:
    """Client no formato OpenAI. Unico ponto de saida para LLM do projeto."""
    certs.ensure_tls()
    provider = get_provider()
    return _client_for(get_base_url(), get_api_key(), provider.name)


def current_season(today: date | None = None) -> str:
    """
    Temporada NBA no formato usado pela API ("2025-26").

    A temporada abre em outubro, entao antes de outubro o rotulo corrente ainda
    e o da temporada que comecou no ano anterior.
    """
    today = today or date.today()
    start_year = today.year if today.month >= 10 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def previous_season(season: str) -> str:
    start_year = int(season.split("-")[0]) - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"
