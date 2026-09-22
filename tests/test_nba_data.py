"""
Testes da camada de dados.

A resolucao de nomes e o unico ponto do sistema que adivinha alguma coisa, e
por isso o mais testado aqui. O acesso a rede e substituido por frames fixos.
"""

from __future__ import annotations

import pandas as pd
import pytest

import nba_data


# ---------------------------------------------------------------------------
# Normalizacao e resolucao de nome
# ---------------------------------------------------------------------------
def test_normalizacao_remove_acento_e_caixa():
    assert nba_data._normalize("Nikola Jokic") == "nikola jokic"
    assert nba_data._normalize("Nikola Jokic") == nba_data._normalize("Nikola Jokić")
    assert nba_data._normalize("  Luka   Doncic  ") == "luka doncic"
    assert nba_data._normalize("Dončić") == "doncic"


def test_nome_exato():
    player = nba_data.resolve_player("LeBron James")
    assert player and player["full_name"] == "LeBron James"
    assert player["id"] == 2544


def test_acento_e_indiferente_na_busca():
    """A base guarda o nome acentuado; a busca funciona dos dois jeitos."""
    assert nba_data.resolve_player("Nikola Jokić")["id"] == 203999
    assert nba_data.resolve_player("Nikola Jokic")["id"] == 203999

    com_acento = nba_data.resolve_player("Luka Dončić")
    sem_acento = nba_data.resolve_player("Luka Doncic")
    assert com_acento["id"] == sem_acento["id"]


def test_apenas_o_sobrenome():
    assert nba_data.resolve_player("Wembanyama")["full_name"] == "Victor Wembanyama"


def test_erro_de_digitacao_e_corrigido():
    """Caso #5 do relatorio de testes: 'Lebron Jams'."""
    assert nba_data.resolve_player("Lebron Jams")["full_name"] == "LeBron James"


def test_nome_inexistente_devolve_none():
    """Caso #7 do relatorio: 'Zzyxor Quantum'."""
    assert nba_data.resolve_player("Zzyxor Quantum") is None
    assert nba_data.resolve_player("") is None
    assert nba_data.resolve_player("   ") is None


def test_sugestoes_para_nome_proximo():
    sugestoes = nba_data.suggest_players("Lebron Jaymes")
    assert any("LeBron" in s for s in sugestoes)


def test_sugestoes_nunca_quebram():
    assert isinstance(nba_data.suggest_players("xxxxxxxxxxxx"), list)


def test_jogador_ativo_tem_precedencia_em_homonimo(monkeypatch):
    monkeypatch.setattr(
        nba_data, "_player_index",
        lambda: [
            {"id": 1, "full_name": "Gary Payton", "is_active": False},
            {"id": 2, "full_name": "Gary Payton", "is_active": True},
        ],
    )
    assert nba_data.resolve_player("Gary Payton")["id"] == 2


# ---------------------------------------------------------------------------
# Camadas de era
# ---------------------------------------------------------------------------
def test_era_antiga_so_tem_core():
    assert nba_data.era_tiers("1996-97") == {"core"}
    assert nba_data.era_tiers("2012-13") == {"core"}


def test_tracking_a_partir_de_2013_14():
    assert "tracking" in nba_data.era_tiers("2013-14")
    assert "tracking" not in nba_data.era_tiers("2012-13")


def test_hustle_a_partir_de_2015_16():
    assert "hustle" not in nba_data.era_tiers("2014-15")
    assert nba_data.era_tiers("2015-16") == {"core", "tracking", "hustle"}


def test_temporada_atual_tem_todas_as_camadas():
    assert nba_data.era_tiers("2025-26") == {"core", "tracking", "hustle"}


# ---------------------------------------------------------------------------
# Temporadas
# ---------------------------------------------------------------------------
@pytest.fixture
def career(monkeypatch):
    frame = pd.DataFrame(
        [
            {"SEASON_ID": "2023-24", "TEAM_ABBREVIATION": "SAS", "PTS": 1500, "GP": 71},
            {"SEASON_ID": "2024-25", "TEAM_ABBREVIATION": "SAS", "PTS": 1600, "GP": 70},
        ]
    )
    monkeypatch.setattr(nba_data, "career_frame", lambda pid: frame)
    return frame


def test_temporadas_disponiveis_saem_ordenadas(career):
    assert nba_data.available_seasons(1) == ["2023-24", "2024-25"]


def test_sem_temporada_pedida_usa_a_mais_recente(career):
    assert nba_data.resolve_season_for_player(1, None) == "2024-25"


def test_temporada_pedida_e_respeitada(career):
    assert nba_data.resolve_season_for_player(1, "2023-24") == "2023-24"


def test_temporada_inexistente_devolve_none(career):
    """Caso #6 do relatorio: 2030-31 nao pode virar fallback silencioso."""
    assert nba_data.resolve_season_for_player(1, "2030-31") is None


def test_troca_de_time_consolida_na_linha_tot(monkeypatch):
    frame = pd.DataFrame(
        [
            {"SEASON_ID": "2024-25", "TEAM_ABBREVIATION": "DAL", "PTS": 700, "GP": 22},
            {"SEASON_ID": "2024-25", "TEAM_ABBREVIATION": "LAL", "PTS": 900, "GP": 28},
            {"SEASON_ID": "2024-25", "TEAM_ABBREVIATION": "TOT", "PTS": 1600, "GP": 50},
        ]
    )
    monkeypatch.setattr(nba_data, "career_frame", lambda pid: frame)
    row = nba_data.season_totals_row(1, "2024-25")
    assert row["TEAM_ABBREVIATION"] == "TOT"
    assert row["PTS"] == 1600


def test_temporada_sem_linha_devolve_none(career):
    assert nba_data.season_totals_row(1, "1999-00") is None


# ---------------------------------------------------------------------------
# Imagem
# ---------------------------------------------------------------------------
def test_url_de_headshot_tem_o_id_do_jogador():
    assert nba_data.HEADSHOT_URL.format(player_id=2544).endswith("/2544.png")
    assert "1040x760" in nba_data.HEADSHOT_URL


def test_tamanho_do_headshot_e_padronizado():
    assert nba_data.HEADSHOT_SIZE == (1040, 760)
