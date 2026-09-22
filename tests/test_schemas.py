"""
Testes do contrato de dados (entrada e saida das tools).

A auditoria pede explicitamente para nao confiar em argumento gerado por LLM:
tipo, faixa, enum, formato de temporada e parametro inventado sao todos casos
observados na pratica com modelos pequenos.
"""

from __future__ import annotations

import pytest

import tools as tool_registry
from validation import schemas

SCHEMAS = tool_registry.TOOL_SCHEMAS


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
def test_argumentos_validos_passam_intactos():
    cleaned, errors = schemas.validate_arguments(
        "get_player_season_stats",
        {"player_name": "Nikola Jokic", "season": "2024-25"},
        SCHEMAS,
    )
    assert errors == []
    assert cleaned == {"player_name": "Nikola Jokic", "season": "2024-25"}


def test_parametro_inventado_e_descartado_sem_derrubar_a_chamada():
    cleaned, errors = schemas.validate_arguments(
        "get_player_season_stats",
        {"player_name": "Jokic", "playoffs": True},
        SCHEMAS,
    )
    assert "playoffs" not in cleaned
    assert any("nao existe no schema" in e for e in errors)


def test_obrigatorio_ausente_e_erro():
    _, errors = schemas.validate_arguments("get_player_season_stats", {}, SCHEMAS)
    assert any("obrigatorio" in e for e in errors)


def test_temporada_em_formato_livre_e_rejeitada():
    cleaned, errors = schemas.validate_arguments(
        "get_player_season_stats",
        {"player_name": "Jokic", "season": "2024"},
        SCHEMAS,
    )
    assert "season" not in cleaned
    assert any("formato AAAA-AA" in e for e in errors)


@pytest.mark.parametrize("season", ["2024-25", "1996-97", "2025-26"])
def test_temporadas_validas_sao_aceitas(season):
    cleaned, errors = schemas.validate_arguments(
        "get_player_season_stats", {"player_name": "Jokic", "season": season}, SCHEMAS
    )
    assert cleaned["season"] == season
    assert errors == []


def test_inteiro_como_string_e_convertido():
    """Modelo pequeno manda num_games='7' com frequencia."""
    cleaned, _ = schemas.validate_arguments(
        "get_recent_games", {"player_name": "Giannis", "num_games": "7"}, SCHEMAS
    )
    assert cleaned["num_games"] == 7


def test_faixa_fora_do_limite_e_ajustada():
    cleaned, errors = schemas.validate_arguments(
        "get_recent_games", {"player_name": "Giannis", "num_games": 500}, SCHEMAS
    )
    assert cleaned["num_games"] == 25
    assert any("acima do maximo" in e for e in errors)


def test_enum_invalido_e_rejeitado():
    cleaned, errors = schemas.validate_arguments(
        "compare_players", {"player_a": "Jokic", "mode": "parecido"}, SCHEMAS
    )
    assert "mode" not in cleaned
    assert any("fora do enum" in e for e in errors)


def test_booleano_no_lugar_de_inteiro_nao_vira_um():
    _, errors = schemas.validate_arguments(
        "get_recent_games", {"player_name": "X", "num_games": True}, SCHEMAS
    )
    assert any("booleano" in e for e in errors)


def test_tool_desconhecida():
    _, errors = schemas.validate_arguments("get_salary", {"player_name": "X"}, SCHEMAS)
    assert any("desconhecida" in e for e in errors)


def test_erro_de_argumento_vira_dict_estruturado():
    payload = schemas.arguments_error("get_recent_games", ["faltou player_name"])
    assert payload["error"] == "invalid_arguments"
    assert "message" in payload


# ---------------------------------------------------------------------------
# Saida
# ---------------------------------------------------------------------------
def test_payload_valido_nao_gera_problema(season_stats_payload):
    assert schemas.validate_output("get_player_season_stats", season_stats_payload) == []


def test_campo_obrigatorio_ausente_e_pego(season_stats_payload):
    del season_stats_payload["games_played"]
    issues = schemas.validate_output("get_player_season_stats", season_stats_payload)
    assert any("games_played" in i for i in issues)


def test_percentual_fora_da_faixa_e_pego(season_stats_payload):
    season_stats_payload["shooting"]["fg_pct"] = 57.6  # deveria ser 0.576
    issues = schemas.validate_output("get_player_season_stats", season_stats_payload)
    assert any("fracao entre 0 e 1" in i for i in issues)


def test_contagem_negativa_e_pega(season_stats_payload):
    season_stats_payload["per_game"]["points"] = -3.0
    issues = schemas.validate_output("get_player_season_stats", season_stats_payload)
    assert any("nao pode ser negativo" in i for i in issues)


def test_temporada_malformada_no_payload_e_pega(season_stats_payload):
    season_stats_payload["season"] = "2024/25"
    issues = schemas.validate_output("get_player_season_stats", season_stats_payload)
    assert any("formato AAAA-AA" in i for i in issues)


def test_player_id_invalido(season_stats_payload):
    season_stats_payload["player_id"] = -1
    issues = schemas.validate_output("get_player_season_stats", season_stats_payload)
    assert any("player_id invalido" in i for i in issues)


def test_contagem_de_jogos_inconsistente(recent_games_payload):
    recent_games_payload["games_returned"] = 5  # ha 1 jogo na lista
    issues = schemas.validate_output("get_recent_games", recent_games_payload)
    assert any("nao bate" in i for i in issues)


def test_erro_estruturado_e_saida_valida():
    payload = {"error": "player_not_found", "message": "Nao encontrei."}
    assert schemas.validate_output("get_player_season_stats", payload) == []


def test_erro_sem_mensagem_e_violacao_de_contrato():
    issues = schemas.validate_output("get_player_season_stats", {"error": "no_data"})
    assert any("sem mensagem" in i for i in issues)


def test_resemblance_fora_da_escala():
    issues = schemas.validate_output("compare_players", {"resemblance": 180.0})
    assert any("0-100" in i for i in issues)


def test_plus_minus_negativo_e_legitimo(recent_games_payload):
    recent_games_payload["games"][0]["plus_minus"] = -12
    assert schemas.validate_output("get_recent_games", recent_games_payload) == []
