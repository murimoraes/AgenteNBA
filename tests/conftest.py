"""
Configuracao da suite.

Regra da suite: NENHUM teste chama a API do LLM nem a API da NBA. Tudo que sai
para a rede e substituido por dado fixo. Assim a suite roda offline, em
segundos, e sem custo -- que e o que permite roda-la a cada alteracao.

A suite de avaliacao (eval/), essa sim, chama o modelo de verdade -- e por isso
tem controle explicito de orcamento.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def season_stats_payload() -> dict:
    """Retorno tipico de get_player_season_stats, usado como evidencia."""
    return {
        "player": "Nikola Jokic",
        "player_id": 203999,
        "season": "2024-25",
        "team": "DEN",
        "games_played": 70,
        "games_started": 70,
        "per_game": {
            "minutes": 36.7,
            "points": 29.6,
            "rebounds": 12.7,
            "assists": 10.2,
            "steals": 1.8,
            "blocks": 0.6,
            "turnovers": 3.2,
            "fouls": 2.2,
        },
        "shooting": {
            "fg_made_per_game": 10.5,
            "fg_attempted_per_game": 18.2,
            "fg_pct": 0.576,
            "fg3_made_per_game": 1.9,
            "fg3_attempted_per_game": 4.6,
            "fg3_pct": 0.417,
            "ft_made_per_game": 6.7,
            "ft_attempted_per_game": 8.4,
            "ft_pct": 0.8,
            "true_shooting_pct": 0.663,
        },
        "season_totals": {
            "points": 2071,
            "rebounds": 889,
            "assists": 715,
            "minutes": 2566,
        },
        "note": "Medias calculadas em Python a partir dos totais oficiais da NBA.",
    }


@pytest.fixture
def recent_games_payload() -> dict:
    """Retorno de get_recent_games com dado VELHO (off-season)."""
    return {
        "player": "Victor Wembanyama",
        "player_id": 1641705,
        "season": "2025-26",
        "games_returned": 1,
        "games": [
            {
                "date": "APR 10, 2026",
                "matchup": "SAS vs. DAL",
                "result": "W",
                "minutes": 26,
                "points": 40,
                "rebounds": 13,
                "assists": 5,
                "steals": 1,
                "blocks": 2,
                "turnovers": 2,
                "fg": "14/23",
                "fg3": "2/7",
                "ft": "10/11",
                "plus_minus": 10,
            }
        ],
        "averages_over_span": {
            "points": 40.0,
            "rebounds": 13.0,
            "assists": 5.0,
            "minutes": 26.0,
            "fg_pct": 0.609,
        },
        "record_over_span": {"wins": 1, "losses": 0},
        "data_freshness": {
            "today": "2026-09-21",
            "last_game_date": "2026-04-10",
            "days_since_last_game": 164,
            "is_recent": False,
            "note": "ATENCAO: o ultimo jogo deste jogador foi em 2026-04-10, ha 164 dias.",
        },
        "note": "Medias do recorte calculadas em Python sobre os box scores oficiais.",
    }
