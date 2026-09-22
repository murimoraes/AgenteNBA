"""
Testes de configuracao.

O ponto sensivel aqui e nao vazar credencial e nao escolher provider errado --
os dois falham silenciosamente em producao se ninguem testar.
"""

from __future__ import annotations

from datetime import date

import pytest

import config


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    for var in ("LLM_PROVIDER", "LLM_BASE_URL", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
                "OPENAI_MODEL", "OPENROUTER_MODEL"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------
def test_openai_tem_precedencia_quando_as_duas_chaves_existem(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-teste")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-teste")
    assert config.get_provider().name == "openai"


def test_openrouter_quando_so_ele_tem_chave(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-teste")
    assert config.get_provider().name == "openrouter"


def test_sem_chave_nenhuma_cai_no_openrouter_para_a_mensagem_fazer_sentido():
    assert config.get_provider().name == "openrouter"
    assert not config.has_api_key()


def test_llm_provider_forca_a_escolha(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-teste")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    assert config.get_provider().name == "openrouter"


def test_llm_provider_invalido_falha_alto(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    with pytest.raises(config.ConfigError) as exc:
        config.get_provider()
    assert "anthropic" in str(exc.value)


def test_base_url_pode_ser_sobreposta(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.interno/v1")
    assert config.get_base_url() == "https://gateway.interno/v1"


def test_chave_ausente_da_erro_acionavel():
    with pytest.raises(config.ConfigError) as exc:
        config.get_api_key()
    assert "OPENROUTER_API_KEY" in str(exc.value)
    assert ".env" in str(exc.value)


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------
def test_modelo_padrao_por_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-teste")
    assert config.get_model() == "gpt-4o-mini"


def test_modelo_do_env_tem_precedencia(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-teste")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    assert config.get_model() == "gpt-4o"


def test_cada_provider_tem_sua_variavel_de_modelo(monkeypatch):
    """Trocar de provider nao pode exigir tambem trocar o nome do modelo."""
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4o")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-teste")
    assert config.get_model() == "openai/gpt-4o"


# ---------------------------------------------------------------------------
# Seguranca
# ---------------------------------------------------------------------------
def test_describe_nunca_inclui_a_chave(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-SEGREDO-NAO-VAZAR")
    resumo = config.describe()

    assert "SEGREDO" not in str(resumo)
    assert resumo["key_status"] == "configurada"
    assert resumo["provider"] == "OpenAI"


def test_describe_sinaliza_chave_ausente():
    assert config.describe()["key_status"] == "ausente"


# ---------------------------------------------------------------------------
# Temporada
# ---------------------------------------------------------------------------
def test_temporada_vira_em_outubro():
    assert config.current_season(date(2025, 9, 30)) == "2024-25"
    assert config.current_season(date(2025, 10, 1)) == "2025-26"


def test_temporada_no_fim_do_ano():
    assert config.current_season(date(2025, 12, 31)) == "2025-26"
    assert config.current_season(date(2026, 1, 1)) == "2025-26"


def test_virada_de_decada():
    assert config.current_season(date(2029, 10, 15)) == "2029-30"
    assert config.current_season(date(2030, 3, 1)) == "2029-30"


def test_temporada_anterior():
    assert config.previous_season("2025-26") == "2024-25"
    assert config.previous_season("2000-01") == "1999-00"


# ---------------------------------------------------------------------------
# Custo
# ---------------------------------------------------------------------------
def test_custo_de_modelo_tabelado():
    # 1M de entrada + 1M de saida em gpt-4o-mini = 0.15 + 0.60
    assert config.estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000) == pytest.approx(0.75)


def test_custo_de_turno_tipico_e_pequeno():
    custo = config.estimate_cost("gpt-4o-mini", 2500, 600)
    assert 0 < custo < 0.01


def test_modelo_gratuito_custa_zero():
    assert config.estimate_cost("nex-agi/nex-n2.5-mini:free", 5000, 1000) == 0.0


def test_modelo_desconhecido_admite_que_nao_sabe():
    """Mesma regra que o agente segue: nao estimar o que nao se sabe."""
    assert config.estimate_cost("modelo-novo-qualquer", 1000, 500) is None


def test_custo_sem_tokens():
    assert config.estimate_cost("gpt-4o-mini", 0, 0) == 0.0
