"""
Testes das tools.

O foco e o contrato que o modelo enxerga: erro sempre estruturado (nunca
excecao), limites respeitados, schemas coerentes com as funcoes e os novos
metadados de rastreabilidade (name_match, data_freshness).
"""

from __future__ import annotations

import pandas as pd
import pytest

import nba_data
import tools


# ---------------------------------------------------------------------------
# Registro e schemas
# ---------------------------------------------------------------------------
def test_toda_funcao_registrada_tem_schema():
    nomes_schema = {s["function"]["name"] for s in tools.TOOL_SCHEMAS}
    assert nomes_schema == set(tools.TOOL_FUNCTIONS)


def test_schemas_estao_no_formato_da_openai():
    for schema in tools.TOOL_SCHEMAS:
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] and fn["description"]
        assert fn["parameters"]["type"] == "object"
        assert isinstance(fn["parameters"]["properties"], dict)


def test_parametros_obrigatorios_existem_nas_propriedades():
    for schema in tools.TOOL_SCHEMAS:
        params = schema["function"]["parameters"]
        for obrigatorio in params.get("required", []):
            assert obrigatorio in params["properties"]


def test_toda_tool_aceita_player_name():
    for schema in tools.TOOL_SCHEMAS:
        assert "player_name" in schema["function"]["parameters"]["properties"] or (
            "player_a" in schema["function"]["parameters"]["properties"]
        )


# ---------------------------------------------------------------------------
# Erros estruturados
# ---------------------------------------------------------------------------
def test_jogador_inexistente_em_todas_as_tools():
    """Nenhuma tool pode levantar excecao por nome desconhecido."""
    for nome, fn in tools.TOOL_FUNCTIONS.items():
        arg = "player_a" if nome == "compare_players" else "player_name"
        result = fn(**{arg: "Zzyxor Quantum"})
        assert result["error"] == "player_not_found", nome
        assert "message" in result


def test_erro_de_jogador_traz_sugestoes():
    result = tools.get_player_bio("Lebron Jaymes Jr")
    if result.get("error"):
        assert isinstance(result["suggestions"], list)


def test_temporada_inexistente_lista_as_disponiveis(monkeypatch):
    """Caso #6 do relatorio: 2030-31 devolve erro util, nao fallback mudo."""
    monkeypatch.setattr(nba_data, "resolve_season_for_player", lambda pid, s: None)
    monkeypatch.setattr(
        nba_data, "available_seasons", lambda pid: ["2023-24", "2024-25", "2025-26"]
    )
    result = tools.get_player_season_stats("Victor Wembanyama", "2030-31")

    assert result["error"] == "season_not_available"
    assert result["requested_season"] == "2030-31"
    assert "2025-26" in result["message"]


# ---------------------------------------------------------------------------
# Helpers numericos
# ---------------------------------------------------------------------------
def test_divisao_por_zero_nao_quebra():
    assert tools._rate(10, 0) is None
    assert tools._rate(10, None) is None
    assert tools._rate(None, 5) is None


def test_media_arredonda_na_casa_pedida():
    assert tools._rate(100, 3) == 33.3
    assert tools._rate(100, 3, 2) == 33.33


def test_conversao_numerica_tolera_lixo():
    assert tools._num("abc") is None
    assert tools._num(None) is None
    assert tools._num(0.57612, 3) == 0.576


# ---------------------------------------------------------------------------
# Rastreabilidade adicionada na Fase 1
# ---------------------------------------------------------------------------
def test_nome_exato_nao_gera_aviso():
    player = {"id": 2544, "full_name": "LeBron James", "is_active": True}
    assert tools._name_match("LeBron James", player) is None
    assert tools._name_match("lebron james", player) is None


def test_nome_corrigido_gera_aviso_para_o_usuario():
    """Caso #5 do relatorio: a troca silenciosa de nome agora e declarada."""
    player = {"id": 2544, "full_name": "LeBron James", "is_active": True}
    aviso = tools._name_match("Lebron Jams", player)

    assert aviso is not None
    assert aviso["resolved_to"] == "LeBron James"
    assert aviso["exact"] is False
    assert "Lebron Jams" in aviso["message"]


def test_metadados_opcionais_nao_poluem_o_payload():
    payload = tools._with_meta({"a": 1}, name_match=None, extra=None)
    assert payload == {"a": 1}

    payload = tools._with_meta({"a": 1}, name_match={"x": 1}, extra="v")
    assert payload["name_match"] == {"x": 1}
    assert payload["extra"] == "v"


def test_jogos_recentes_carregam_frescor_do_dado(monkeypatch):
    """Caso #8 do relatorio: sem este bloco o modelo chama abril de 'ontem'."""
    log = pd.DataFrame([{
        "GAME_DATE": "APR 10, 2026", "MATCHUP": "SAS vs. DAL", "WL": "W", "MIN": 26,
        "PTS": 40, "REB": 13, "AST": 5, "STL": 1, "BLK": 2, "TOV": 2,
        "FGM": 14, "FGA": 23, "FG3M": 2, "FG3A": 7, "FTM": 10, "FTA": 11,
        "PLUS_MINUS": 10,
    }])
    monkeypatch.setattr(nba_data, "resolve_player", lambda n: {
        "id": 1641705, "full_name": "Victor Wembanyama", "is_active": True})
    monkeypatch.setattr(nba_data, "resolve_season_for_player", lambda pid, s: "2025-26")
    monkeypatch.setattr(nba_data, "game_log_frame", lambda pid, s: log)

    result = tools.get_recent_games("Wembanyama", num_games=1)

    assert "data_freshness" in result
    assert result["data_freshness"]["last_game_date"] == "2026-04-10"
    assert result["data_freshness"]["days_since_last_game"] is not None
    assert result["games_returned"] == 1


def test_num_games_e_limitado(monkeypatch):
    capturado = {}

    def fake_log(pid, season):
        capturado["chamou"] = True
        return pd.DataFrame()

    monkeypatch.setattr(nba_data, "resolve_player", lambda n: {
        "id": 1, "full_name": "X Y", "is_active": True})
    monkeypatch.setattr(nba_data, "resolve_season_for_player", lambda pid, s: "2025-26")
    monkeypatch.setattr(nba_data, "game_log_frame", fake_log)

    result = tools.get_recent_games("X Y", num_games=999)
    assert result["error"] == "no_games"  # log vazio, mas sem excecao
    assert capturado["chamou"]


def test_bio_declara_o_que_nao_fornece(monkeypatch):
    """O modelo precisa ver, no proprio payload, que salario nao existe aqui."""
    info = pd.DataFrame([{
        "POSITION": "Center", "HEIGHT": "7-3", "WEIGHT": "235",
        "BIRTHDATE": "2004-01-04T00:00:00", "COUNTRY": "France", "SCHOOL": "",
        "TEAM_CITY": "San Antonio", "TEAM_NAME": "Spurs", "TEAM_ABBREVIATION": "SAS",
        "JERSEY": "1", "DRAFT_YEAR": "2023", "DRAFT_ROUND": "1", "DRAFT_NUMBER": "1",
        "SEASON_EXP": "2", "FROM_YEAR": "2023", "TO_YEAR": "2025",
        "GREATEST_75_FLAG": "N",
    }])
    monkeypatch.setattr(nba_data, "resolve_player", lambda n: {
        "id": 1641705, "full_name": "Victor Wembanyama", "is_active": True})
    monkeypatch.setattr(nba_data, "player_info_frame", lambda pid: info)
    monkeypatch.setattr(nba_data, "available_seasons", lambda pid: ["2023-24", "2024-25"])

    result = tools.get_player_bio("Wembanyama")
    assert "salario" in result["not_provided"]
    assert result["position"] == "Center"
