"""
Camada de acesso a dados (nba_api + CDN de imagens).

Esta e a UNICA fonte de numeros do sistema. O LLM nunca calcula nem estima:
ele recebe o que estas funcoes retornam. Tudo aqui e deterministico e cacheado.
"""

from __future__ import annotations

import hashlib
import tempfile
import time
import unicodedata
from difflib import get_close_matches
from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests

import certs

certs.ensure_tls()

from nba_api.stats.endpoints import (  # noqa: E402  (import apos ensure_tls)
    commonplayerinfo,
    leaguedashplayerbiostats,
    leaguedashplayershotlocations,
    leaguedashplayerstats,
    leaguedashptstats,
    leaguehustlestatsplayer,
    playercareerstats,
    playergamelog,
)
from nba_api.stats.static import players as static_players  # noqa: E402

TIMEOUT = 30
_CACHE_DIR = Path(tempfile.gettempdir()) / "nba_scout" / "data"
_CACHE_TTL = 60 * 60 * 12  # 12h

# ---------------------------------------------------------------------------
# Imagem oficial
# ---------------------------------------------------------------------------
# VERIFICADO POR TESTE REAL (2026-09-21), nao assumido:
#   GET https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png
#   - LeBron(2544), Wembanyama(1641705), Jokic(203999), Curry(201939):
#     200 image/png, todos 1040x760 (mesma resolucao e proporcao para todos).
#   - id inexistente (9999999): 200 image/png -- NAO 404 -- com corpo byte-a-byte
#     identico a .../1040x760/fallback.png (sha256 e366885f..., 12430 bytes).
# Consequencia de projeto: o status HTTP nao detecta jogador sem foto; a deteccao
# e feita por hash do conteudo contra o proprio fallback do CDN.
HEADSHOT_URL = "https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png"
HEADSHOT_FALLBACK_URL = "https://cdn.nba.com/headshots/nba/latest/1040x760/fallback.png"
HEADSHOT_SIZE = (1040, 760)
_KNOWN_FALLBACK_SHA256 = "e366885fc4212e3a4100f49ed48ad866fd05b32e2d25898c2c24205e789e2632"


# ---------------------------------------------------------------------------
# Cache em disco (sobrevive a restart do Streamlit)
# ---------------------------------------------------------------------------
def _cached_frame(key: str, builder) -> pd.DataFrame:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _CACHE_DIR / f"{key}.pkl"
    if path.is_file() and (time.time() - path.stat().st_mtime) < _CACHE_TTL:
        try:
            return pd.read_pickle(path)
        except Exception:
            pass
    frame = builder()
    try:
        frame.to_pickle(path)
    except Exception:
        pass
    return frame


# ---------------------------------------------------------------------------
# Resolucao de nome -> jogador
# ---------------------------------------------------------------------------
def _normalize(name: str) -> str:
    """Minusculas e sem diacriticos, para casar nomes como Jokic ou Doncic."""
    stripped = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    return " ".join(stripped.lower().split())


@lru_cache(maxsize=1)
def _player_index() -> list[dict]:
    return static_players.get_players()


def resolve_player(name: str) -> dict | None:
    """
    Nome livre -> registro do jogador. Tolerante a acento e a erro de digitacao.

    Retorna {"id", "full_name", "is_active"} ou None. Prioriza jogadores ativos
    quando ha homonimos.
    """
    query = _normalize(name)
    if not query:
        return None

    by_norm: dict[str, list[dict]] = {}
    for p in _player_index():
        by_norm.setdefault(_normalize(p["full_name"]), []).append(p)

    def pick(cands: list[dict]) -> dict:
        active = [c for c in cands if c.get("is_active")]
        chosen = (active or cands)[0]
        return {
            "id": int(chosen["id"]),
            "full_name": chosen["full_name"],
            "is_active": bool(chosen.get("is_active")),
        }

    # 1) match exato, ignorando acentos
    if query in by_norm:
        return pick(by_norm[query])

    # 2) substring: "wembanyama" casa com "Victor Wembanyama"
    subs = [p for norm, group in by_norm.items() if query in norm for p in group]
    if subs:
        return pick(subs)

    # 3) erro de digitacao
    close = get_close_matches(query, list(by_norm.keys()), n=1, cutoff=0.82)
    if close:
        return pick(by_norm[close[0]])

    return None


def suggest_players(name: str, n: int = 5) -> list[str]:
    """Sugestoes quando resolve_player falha, para o agente pedir confirmacao."""
    norms = {_normalize(p["full_name"]): p["full_name"] for p in _player_index()}
    close = get_close_matches(_normalize(name), list(norms.keys()), n=n, cutoff=0.6)
    return [norms[c] for c in close]


# ---------------------------------------------------------------------------
# Estatisticas
# ---------------------------------------------------------------------------
@lru_cache(maxsize=256)
def career_frame(player_id: int) -> pd.DataFrame:
    """Totais por temporada. Atencao: a API devolve TOTAIS, nao medias."""
    return playercareerstats.PlayerCareerStats(
        player_id=player_id, timeout=TIMEOUT
    ).get_data_frames()[0]


@lru_cache(maxsize=256)
def game_log_frame(player_id: int, season: str) -> pd.DataFrame:
    return playergamelog.PlayerGameLog(
        player_id=player_id, season=season, timeout=TIMEOUT
    ).get_data_frames()[0]


@lru_cache(maxsize=256)
def player_info_frame(player_id: int) -> pd.DataFrame:
    return commonplayerinfo.CommonPlayerInfo(
        player_id=player_id, timeout=TIMEOUT
    ).get_data_frames()[0]


# ---------------------------------------------------------------------------
# Camadas de dados por era
# ---------------------------------------------------------------------------
# Verificado por teste real (2026-09-21) sobre 1996-97 ... 2025-26:
#   Base / Advanced / Bio / ShotLocations -> existem desde 1996-97 (1990-91 e
#     anteriores voltam vazio; 1996-97 e o limite historico da API).
#   Tracking (Drives, Defense, PullUp, CatchShoot) -> a partir de 2013-14.
#   Hustle -> a partir de 2015-16 (parcial: 147 jogadores; completo de 2020-21).
# Comparar temporadas de eras diferentes so pode usar a INTERSECAO das camadas.
FIRST_SEASON = "1996-97"
TRACKING_FROM = "2013-14"
HUSTLE_FROM = "2015-16"


def _season_start(season: str) -> int:
    return int(season.split("-")[0])


def era_tiers(season: str) -> set[str]:
    """Camadas de features disponiveis para a temporada."""
    tiers = {"core"}
    if _season_start(season) >= _season_start(TRACKING_FROM):
        tiers.add("tracking")
    if _season_start(season) >= _season_start(HUSTLE_FROM):
        tiers.add("hustle")
    return tiers


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    """ShotLocations vem com MultiIndex (zona, metrica)."""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [
            "_".join(str(x) for x in c if str(x)).strip("_") for c in df.columns
        ]
    return df


def _pt(season: str, measure: str) -> pd.DataFrame:
    return leaguedashptstats.LeagueDashPtStats(
        season=season, player_or_team="Player", pt_measure_type=measure, timeout=60
    ).get_data_frames()[0]


def league_frame(season: str) -> pd.DataFrame:
    """
    Uma linha por jogador da temporada, juntando todas as fontes league-wide
    disponiveis para a era. Cada fonte e uma chamada; o conjunto e cacheado.

      core     Base PerGame + Advanced + Bio + ShotLocations   (1996-97+)
      tracking Drives, Defense, PullUpShot, CatchShoot          (2013-14+)
      hustle   deflexoes, contestados, box-outs, charges        (2015-16+)

    E a populacao usada para normalizar o vetor de estilo em similarity.py.
    """

    def build() -> pd.DataFrame:
        tiers = era_tiers(season)

        base = leaguedashplayerstats.LeagueDashPlayerStats(
            season=season, per_mode_detailed="PerGame", timeout=60
        ).get_data_frames()[0]
        keep_base = [
            "PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "AGE", "GP", "MIN",
            "FGM", "FGA", "FG_PCT", "FG3M", "FG3A", "FG3_PCT", "FTM", "FTA", "FT_PCT",
            "OREB", "DREB", "REB", "AST", "TOV", "STL", "BLK", "PF", "PTS", "PLUS_MINUS",
        ]
        merged = base[[c for c in keep_base if c in base.columns]].copy()

        adv = leaguedashplayerstats.LeagueDashPlayerStats(
            season=season, per_mode_detailed="PerGame",
            measure_type_detailed_defense="Advanced", timeout=60
        ).get_data_frames()[0]
        keep_adv = ["PLAYER_ID", "USG_PCT", "TS_PCT", "EFG_PCT", "AST_PCT",
                    "AST_TO", "OREB_PCT", "DREB_PCT", "REB_PCT", "PACE", "NET_RATING"]
        merged = merged.merge(adv[[c for c in keep_adv if c in adv.columns]],
                              on="PLAYER_ID", how="left")

        bio = leaguedashplayerbiostats.LeagueDashPlayerBioStats(
            season=season, timeout=60
        ).get_data_frames()[0]
        keep_bio = ["PLAYER_ID", "PLAYER_HEIGHT_INCHES", "PLAYER_WEIGHT"]
        merged = merged.merge(bio[[c for c in keep_bio if c in bio.columns]],
                              on="PLAYER_ID", how="left")

        # Zonas de arremesso: a fonte do perfil de estilo independente de volume.
        shots = _flatten(leaguedashplayershotlocations.LeagueDashPlayerShotLocations(
            season=season, timeout=60).get_data_frames()[0])
        # "Corner 3" e a SOMA de Left + Right Corner 3 -- incluir as tres contaria
        # o canto duas vezes no denominador.
        zonas = ["Restricted Area", "In The Paint (Non-RA)", "Mid-Range",
                 "Left Corner 3", "Right Corner 3", "Above the Break 3"]
        zcols = [f"{z}_FGA" for z in zonas if f"{z}_FGA" in shots.columns]
        if zcols:
            keep = ["PLAYER_ID"] + zcols
            merged = merged.merge(shots[keep], on="PLAYER_ID", how="left")

        if "tracking" in tiers:
            for measure, cols in [
                ("Drives", ["DRIVES", "DRIVE_PTS", "DRIVE_FG_PCT", "DRIVE_PASSES", "DRIVE_AST"]),
                ("Defense", ["DEF_RIM_FGA", "DEF_RIM_FG_PCT"]),
                ("PullUpShot", ["PULL_UP_PTS", "PULL_UP_FGA"]),
                ("CatchShoot", ["CATCH_SHOOT_PTS", "CATCH_SHOOT_FGA"]),
                ("Passing", ["PASSES_MADE", "POTENTIAL_AST", "SECONDARY_AST"]),
                ("PostTouch", ["POST_TOUCHES", "POST_TOUCH_PTS"]),
            ]:
                try:
                    df = _pt(season, measure)
                    have = [c for c in cols if c in df.columns]
                    if have:
                        merged = merged.merge(df[["PLAYER_ID"] + have],
                                              on="PLAYER_ID", how="left")
                except Exception:
                    continue  # era sem o dado: as features caem sozinhas

        if "hustle" in tiers:
            try:
                h = leaguehustlestatsplayer.LeagueHustleStatsPlayer(
                    season=season, timeout=60).get_data_frames()[0]
                # ATENCAO: o hustle traz TOTAIS e a coluna de jogos chama-se "G",
                # nao "GP". Normalizar aqui evita o erro de ler total como media.
                gcol = "G" if "G" in h.columns else ("GP" if "GP" in h.columns else None)
                cols = ["DEFLECTIONS", "CONTESTED_SHOTS", "BOX_OUTS",
                        "CHARGES_DRAWN", "SCREEN_ASSISTS", "LOOSE_BALLS_RECOVERED"]
                have = [c for c in cols if c in h.columns]
                if have and gcol:
                    hh = h[["PLAYER_ID", gcol] + have].copy()
                    for c in have:
                        hh[c] = pd.to_numeric(hh[c], errors="coerce") / pd.to_numeric(
                            hh[gcol], errors="coerce").replace(0, pd.NA)
                    merged = merged.merge(hh[["PLAYER_ID"] + have],
                                          on="PLAYER_ID", how="left")
            except Exception:
                pass

        merged["PLAYER_WEIGHT"] = pd.to_numeric(merged["PLAYER_WEIGHT"], errors="coerce")
        merged["SEASON"] = season
        return merged

    return _cached_frame(f"league_v2_{season}", build)


def season_totals_row(player_id: int, season: str):
    """Linha de totais da temporada; consolida quando houve troca de time."""
    df = career_frame(player_id)
    rows = df[df["SEASON_ID"] == season]
    if rows.empty:
        return None
    if len(rows) > 1:  # temporada com troca: a API inclui TOT + cada time
        tot = rows[rows["TEAM_ABBREVIATION"] == "TOT"]
        return (tot if not tot.empty else rows.head(1)).iloc[0]
    return rows.iloc[0]


def available_seasons(player_id: int) -> list[str]:
    df = career_frame(player_id)
    return sorted(df["SEASON_ID"].unique().tolist())


def resolve_season_for_player(player_id: int, season: str | None) -> str | None:
    """Usa a temporada pedida; sem ela, a mais recente que o jogador tem."""
    seasons = available_seasons(player_id)
    if not seasons:
        return None
    if season:
        return season if season in seasons else None
    return seasons[-1]


# ---------------------------------------------------------------------------
# Headshot
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _fallback_digest() -> str:
    """Hash do placeholder oficial; cai no valor verificado se a rede falhar."""
    try:
        resp = requests.get(HEADSHOT_FALLBACK_URL, timeout=15)
        if resp.ok:
            return hashlib.sha256(resp.content).hexdigest()
    except Exception:
        pass
    return _KNOWN_FALLBACK_SHA256


@lru_cache(maxsize=256)
def headshot_status(player_id: int) -> tuple[str, bool]:
    """
    Devolve (url, tem_foto_real).

    tem_foto_real=False quando o CDN entrega a silhueta generica. Detectado por
    hash, ja que o endpoint responde 200 tambem para jogador sem foto.
    """
    url = HEADSHOT_URL.format(player_id=player_id)
    try:
        resp = requests.get(url, timeout=15)
        if not resp.ok or not resp.headers.get("Content-Type", "").startswith("image/"):
            return url, False
        return url, hashlib.sha256(resp.content).hexdigest() != _fallback_digest()
    except Exception:
        return url, False
