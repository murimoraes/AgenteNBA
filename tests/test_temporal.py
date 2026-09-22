"""
Testes de grounding temporal.

Reproduz o caso #8 do relatorio de testes: em 21/09/2026, o agente apresentou
um jogo de 10/04/2026 como "o jogo de ontem".
"""

from __future__ import annotations

from datetime import date

from validation import temporal


# ---------------------------------------------------------------------------
# Parsing de data
# ---------------------------------------------------------------------------
def test_parse_formato_da_nba_api():
    assert temporal.parse_game_date("APR 10, 2026") == date(2026, 4, 10)
    assert temporal.parse_game_date("Apr 10, 2026") == date(2026, 4, 10)
    assert temporal.parse_game_date("DEC 25, 2025") == date(2025, 12, 25)


def test_parse_formato_iso():
    assert temporal.parse_game_date("2026-04-10") == date(2026, 4, 10)


def test_parse_entrada_invalida_nao_quebra():
    assert temporal.parse_game_date(None) is None
    assert temporal.parse_game_date("") is None
    assert temporal.parse_game_date("nao e data") is None
    assert temporal.parse_game_date("FEB 30, 2026") is None


# ---------------------------------------------------------------------------
# Bloco data_freshness
# ---------------------------------------------------------------------------
def test_jogo_recente_e_marcado_como_atual():
    bloco = temporal.describe_freshness("APR 10, 2026", today=date(2026, 4, 12))
    assert bloco["is_recent"] is True
    assert bloco["days_since_last_game"] == 2


def test_jogo_velho_traz_aviso_explicito():
    bloco = temporal.describe_freshness("APR 10, 2026", today=date(2026, 9, 21))
    assert bloco["is_recent"] is False
    assert bloco["days_since_last_game"] == 164
    assert bloco["last_game_date"] == "2026-04-10"
    assert "ontem" in bloco["note"]  # o aviso proibe explicitamente o termo


def test_fronteira_de_sete_dias():
    assert temporal.describe_freshness("APR 10, 2026", today=date(2026, 4, 17))["is_recent"]
    assert not temporal.describe_freshness("APR 10, 2026", today=date(2026, 4, 18))["is_recent"]


def test_data_indeterminada_nao_afirma_nada():
    bloco = temporal.describe_freshness(None)
    assert bloco["is_recent"] is None


# ---------------------------------------------------------------------------
# Deteccao na resposta
# ---------------------------------------------------------------------------
def test_caso_real_jogo_de_abril_narrado_como_ontem(recent_games_payload):
    answer = "No jogo de ontem, 10 de abril de 2026, Wembanyama fez 40 pontos."
    flags = temporal.check(answer, [recent_games_payload], question="Como ele jogou ontem?")

    assert any(flag.kind == "stale_as_current" for flag in flags)


def test_resposta_que_cita_a_data_real_passa(recent_games_payload):
    answer = (
        "O ultimo jogo de Wembanyama foi em 2026-04-10, ha 164 dias: 40 pontos "
        "contra Dallas. A temporada nao esta em andamento."
    )
    flags = temporal.check(answer, [recent_games_payload], question="Como ele jogou ontem?")
    assert flags == []


def test_pergunta_sobre_ontem_exige_data_na_resposta(recent_games_payload):
    answer = "Wembanyama fez 40 pontos, 13 rebotes e 5 assistencias."
    flags = temporal.check(answer, [recent_games_payload], question="Como o Wemby jogou ontem?")

    assert any(flag.kind == "missing_date_disclosure" for flag in flags)


def test_data_escrita_por_extenso_conta_como_divulgada(recent_games_payload):
    answer = "O jogo foi em 10 de abril de 2026: 40 pontos."
    flags = temporal.check(answer, [recent_games_payload], question="Como ele jogou ontem?")
    assert [f.kind for f in flags] == []


def test_dado_atual_nao_gera_flag():
    payload = {
        "player": "Nikola Jokic",
        "games": [{"date": "APR 10, 2026", "points": 30}],
        "data_freshness": temporal.describe_freshness("APR 10, 2026", today=date(2026, 4, 11)),
    }
    flags = temporal.check("Ontem ele fez 30 pontos.", [payload], question="e ontem?")
    assert flags == []


def test_sem_bloco_de_frescor_nao_ha_o_que_checar():
    assert temporal.check("Ontem ele jogou muito.", [{"player": "X"}]) == []
    assert temporal.check("Ontem ele jogou muito.", []) == []


def test_prompt_de_correcao_pede_a_data_real(recent_games_payload):
    flags = temporal.check(
        "No jogo de ontem ele fez 40 pontos.",
        [recent_games_payload],
        question="Como ele jogou ontem?",
    )
    prompt = temporal.correction_prompt(flags)
    assert "data real" in prompt
    assert "2026-04-10" in prompt
