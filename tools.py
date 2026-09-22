"""
Tools do agente, no formato exigido pelo OpenRouter/OpenAI:
    {"type": "function", "function": {"name", "description", "parameters"}}

Contrato do projeto: TODO numero que o modelo escreve tem de ter saido daqui.
Estas funcoes calculam em Python e devolvem JSON; o modelo apenas narra.
Erro nunca vira excecao para o modelo -- vira um dict com "error" e, quando da,
"suggestions", para ele conseguir pedir confirmacao ao usuario.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

import config
import nba_data
import similarity
from validation import temporal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _player_or_error(name: str) -> tuple[dict | None, dict | None]:
    player = nba_data.resolve_player(name)
    if player:
        return player, None
    return None, {
        "error": "player_not_found",
        "query": name,
        "suggestions": nba_data.suggest_players(name),
        "message": (
            f"Nao encontrei um jogador chamado '{name}'. "
            "Confirme o nome com o usuario antes de responder."
        ),
    }


def _name_match(query: str, player: dict) -> dict | None:
    """
    Sinaliza quando o nome pedido nao era exatamente o nome resolvido.

    A resolucao e tolerante a erro de digitacao ("Lebron Jams" -> LeBron James),
    o que e bom para responder e ruim para a confianca: sem este aviso o usuario
    nao tem como saber que o sistema trocou o nome por conta propria.
    """
    pedido = nba_data._normalize(query)
    achado = nba_data._normalize(player["full_name"])
    if pedido == achado:
        return None
    return {
        "query": query,
        "resolved_to": player["full_name"],
        "exact": False,
        "message": (
            f"O nome pedido foi '{query}'; o jogador resolvido foi "
            f"{player['full_name']}. Avise o usuario dessa interpretacao na resposta."
        ),
    }


def _rate(num, den, digits: int = 1):
    try:
        if not den:
            return None
        return round(float(num) / float(den), digits)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _num(v, digits: int = 3):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, digits)


def _with_meta(payload: dict, *, name_match: dict | None = None, **extra) -> dict:
    """Anexa metadados de contrato ao payload, omitindo o que nao se aplica."""
    if name_match:
        payload["name_match"] = name_match
    for key, value in extra.items():
        if value is not None:
            payload[key] = value
    return payload


# ---------------------------------------------------------------------------
# 1. Estatisticas de temporada
# ---------------------------------------------------------------------------
def get_player_season_stats(player_name: str, season: str | None = None) -> dict[str, Any]:
    player, err = _player_or_error(player_name)
    if err:
        return err

    resolved = nba_data.resolve_season_for_player(player["id"], season)
    if resolved is None:
        seasons = nba_data.available_seasons(player["id"])
        return {
            "error": "season_not_available",
            "player": player["full_name"],
            "requested_season": season,
            "available_seasons": seasons[-12:],
            "message": (
                f"{player['full_name']} nao tem dados para {season}. "
                f"Temporadas disponiveis (ultimas): {', '.join(seasons[-6:])}."
            ),
        }

    row = nba_data.season_totals_row(player["id"], resolved)
    if row is None:
        return {"error": "no_data", "player": player["full_name"], "season": resolved}

    gp = int(row["GP"]) or 0
    return _with_meta({
        "player": player["full_name"],
        "player_id": player["id"],
        "season": resolved,
        "team": str(row.get("TEAM_ABBREVIATION", "")),
        "games_played": gp,
        "games_started": int(row["GS"]) if row.get("GS") is not None else None,
        "per_game": {
            "minutes": _rate(row["MIN"], gp),
            "points": _rate(row["PTS"], gp),
            "rebounds": _rate(row["REB"], gp),
            "offensive_rebounds": _rate(row["OREB"], gp),
            "defensive_rebounds": _rate(row["DREB"], gp),
            "assists": _rate(row["AST"], gp),
            "steals": _rate(row["STL"], gp),
            "blocks": _rate(row["BLK"], gp),
            "turnovers": _rate(row["TOV"], gp),
            "fouls": _rate(row["PF"], gp),
        },
        "shooting": {
            "fg_made_per_game": _rate(row["FGM"], gp),
            "fg_attempted_per_game": _rate(row["FGA"], gp),
            "fg_pct": _num(row["FG_PCT"]),
            "fg3_made_per_game": _rate(row["FG3M"], gp),
            "fg3_attempted_per_game": _rate(row["FG3A"], gp),
            "fg3_pct": _num(row["FG3_PCT"]),
            "ft_made_per_game": _rate(row["FTM"], gp),
            "ft_attempted_per_game": _rate(row["FTA"], gp),
            "ft_pct": _num(row["FT_PCT"]),
            "true_shooting_pct": _num(
                _rate(row["PTS"], 2 * (float(row["FGA"]) + 0.44 * float(row["FTA"])), 6)
            ),
        },
        "season_totals": {
            "points": int(row["PTS"]),
            "rebounds": int(row["REB"]),
            "assists": int(row["AST"]),
            "minutes": int(row["MIN"]),
        },
        "note": "Medias calculadas em Python a partir dos totais oficiais da NBA.",
    },
        name_match=_name_match(player_name, player),
        as_of=date.today().isoformat(),
        is_current_season=(resolved == config.current_season()),
    )


# ---------------------------------------------------------------------------
# 2. Jogos recentes
# ---------------------------------------------------------------------------
def get_recent_games(
    player_name: str, num_games: int = 5, season: str | None = None
) -> dict[str, Any]:
    player, err = _player_or_error(player_name)
    if err:
        return err

    num_games = max(1, min(int(num_games or 5), 25))
    season = season or nba_data.resolve_season_for_player(player["id"], None)
    if season is None:
        return {"error": "no_data", "player": player["full_name"]}

    log = nba_data.game_log_frame(player["id"], season)
    if log.empty:
        return {
            "error": "no_games",
            "player": player["full_name"],
            "season": season,
            "message": f"Sem jogos registrados para {player['full_name']} em {season}.",
        }

    recent = log.head(num_games)  # a API ja devolve do mais recente para o mais antigo
    games = [
        {
            "date": str(g["GAME_DATE"]),
            "matchup": str(g["MATCHUP"]),
            "result": str(g["WL"]),
            "minutes": _num(g["MIN"], 0),
            "points": int(g["PTS"]),
            "rebounds": int(g["REB"]),
            "assists": int(g["AST"]),
            "steals": int(g["STL"]),
            "blocks": int(g["BLK"]),
            "turnovers": int(g["TOV"]),
            "fg": f"{int(g['FGM'])}/{int(g['FGA'])}",
            "fg3": f"{int(g['FG3M'])}/{int(g['FG3A'])}",
            "ft": f"{int(g['FTM'])}/{int(g['FTA'])}",
            "plus_minus": _num(g["PLUS_MINUS"], 0),
        }
        for _, g in recent.iterrows()
    ]

    n = len(recent)
    return _with_meta({
        "player": player["full_name"],
        "player_id": player["id"],
        "season": season,
        "games_returned": n,
        "games": games,
        "averages_over_span": {
            "points": _rate(recent["PTS"].sum(), n),
            "rebounds": _rate(recent["REB"].sum(), n),
            "assists": _rate(recent["AST"].sum(), n),
            "minutes": _rate(recent["MIN"].sum(), n),
            "fg_pct": _num(
                _rate(recent["FGM"].sum(), recent["FGA"].sum(), 6)
            ),
        },
        "record_over_span": {
            "wins": int((recent["WL"] == "W").sum()),
            "losses": int((recent["WL"] == "L").sum()),
        },
        "note": "Medias do recorte calculadas em Python sobre os box scores oficiais.",
    },
        name_match=_name_match(player_name, player),
        # O modelo nao tem relogio: sem este bloco ele le "ultimo jogo do log"
        # como "jogo recente" e narra um jogo de meses atras como "ontem".
        data_freshness=temporal.describe_freshness(games[0]["date"] if games else None),
    )


# ---------------------------------------------------------------------------
# 3. Comparacao de estilo
# ---------------------------------------------------------------------------
def compare_players(
    player_a: str,
    player_b: str | None = None,
    season: str | None = None,
    season_a: str | None = None,
    season_b: str | None = None,
    mode: str = "pair",
    top_n: int = 5,
    cross_era: bool = False,
) -> dict[str, Any]:
    """
    mode="pair"    -> quanto A e B se parecem em estilo.
    mode="similar" -> os jogadores de estilo mais proximo de A.

    season_a / season_b permitem comparar temporadas DIFERENTES (ex.: o MVP de um
    contra o MVP do outro). Cada jogador e normalizado contra a liga do proprio
    ano, entao o resultado ja sai ajustado por era.

    Se o jogador nao jogou na temporada pedida, cai automaticamente para a mais
    recente dele e avisa. Calculo 100% numpy -- nenhuma chamada ao modelo.
    """
    a, err = _player_or_error(player_a)
    if err:
        return err

    avisos: list[str] = []
    match_a = _name_match(player_a, a)
    if match_a:
        avisos.append(match_a["message"])
    alvo_a, aviso_a = similarity.season_for_player(a["id"], season_a or season)
    if alvo_a is None:
        return {
            "error": "no_season_data",
            "player": a["full_name"],
            "message": f"{a['full_name']}: {aviso_a}",
        }
    if aviso_a:
        avisos.append(f"{a['full_name']}: {aviso_a}")

    if mode == "similar" or not player_b:
        extras = None
        if cross_era:
            # Amostra historica: uma temporada por era coberta pela API.
            extras = ["2015-16", "2010-11", "2005-06", "2000-01", "1996-97"]
            extras = [s for s in extras if s != alvo_a]
        res = similarity.most_similar(
            a["id"], alvo_a, n=max(1, min(int(top_n or 5), 10)), cross_era=extras
        )
        if res is None:
            return {"error": "no_season_data", "player": a["full_name"], "season": alvo_a}
        res["notes"] = avisos + ([
            f"{res['excluded']} jogadores ficaram fora do ranking por nao atingirem "
            f"{similarity.MIN_GP} jogos e {similarity.MIN_MPG} min/jogo."
        ] if res.get("excluded") else [])
        if res.get("isolated"):
            res["notes"].append(
                f"{res['player']} nao tem analogo proximo: ate o jogador mais parecido "
                "esta longe. Trate a lista como 'os menos diferentes', nao como iguais."
            )
        res["method"] = ("vetor de estilo normalizado por z-score contra a liga da "
                         "temporada + distancia euclidiana (numpy, deterministico)")
        res["score_meaning"] = (
            "semelhanca 0-100 = percentual dos pares da liga que estao MAIS distantes "
            "entre si do que esta dupla. ATENCAO: 50 NAO e 'meio parecido' -- e "
            "exatamente a semelhanca de dois jogadores sorteados ao acaso. Cada item "
            "traz 'verdict' com a leitura correta; use-o em vez de interpretar o numero. "
            "Nomes com verdict 'pouco parecidos' ou abaixo NAO devem ser apresentados "
            "como jogadores de estilo parecido."
        )
        return res

    b, err_b = _player_or_error(player_b)
    if err_b:
        return err_b

    match_b = _name_match(player_b, b)
    if match_b:
        avisos.append(match_b["message"])

    alvo_b, aviso_b = similarity.season_for_player(b["id"], season_b or season)
    if alvo_b is None:
        return {
            "error": "no_season_data",
            "player": b["full_name"],
            "message": f"{b['full_name']}: {aviso_b}",
        }
    if aviso_b:
        avisos.append(f"{b['full_name']}: {aviso_b}")

    result = similarity.compare(a["id"], alvo_a, b["id"], alvo_b)
    if result is None:
        return {"error": "comparison_failed", "players": [a["full_name"], b["full_name"]]}

    return {
        "mode": "pair",
        "method": ("vetor de estilo normalizado por z-score contra a liga de cada "
                   "temporada + distancia euclidiana e cosseno (numpy, deterministico)"),
        "resemblance": result.resemblance,
        "verdict": similarity.verdict_for(result.resemblance),
        "score_meaning": (
            "0-100 = percentual dos pares da liga que estao MAIS distantes entre si do "
            "que esta dupla. ATENCAO: 50 NAO e 'meio parecido' -- e exatamente a "
            "semelhanca de dois jogadores sorteados ao acaso. Use o campo 'verdict', "
            "que ja traduz o numero; nao invente uma leitura propria da escala."
        ),
        "cosine_similarity": result.cosine,
        "distance": result.distance,
        "features_used": len(result.features_used),
        "features_total": len(similarity.FEATURES),
        "data_tiers": sorted(result.tiers_used),
        "players": {
            "a": {"name": result.a.name, "player_id": result.a.player_id,
                  "season": result.a.season, "team": result.a.team,
                  "games": result.a.games, "minutes_per_game": result.a.minutes},
            "b": {"name": result.b.name, "player_id": result.b.player_id,
                  "season": result.b.season, "team": result.b.team,
                  "games": result.b.games, "minutes_per_game": result.b.minutes},
        },
        # Arquetipos: a leitura de scouting por tras do numero. O score diz o
        # QUANTO se parecem; isto diz EM QUE se parecem e onde divergem.
        "archetypes": {
            "a": result.archetypes_a.get("summary"),
            "b": result.archetypes_b.get("summary"),
            "a_detail": result.archetypes_a.get("categories"),
            "b_detail": result.archetypes_b.get("categories"),
            "comparison": result.archetype_comparison,
            "method": result.archetypes_a.get("method"),
        },
        "biggest_differences": result.per_feature[:6],
        "closest_features": list(reversed(result.per_feature))[:5],
        "all_features": result.per_feature,
        "notes": avisos + result.notes,
        "note": (
            "Estilo medido por COMPOSICAO (de onde arremessa, como cria, papel na "
            "ofensiva), nao por volume de producao: dois jogadores nao sao parecidos "
            "so por marcarem muito."
        ),
    }


# ---------------------------------------------------------------------------
# 4. Arquetipos
# ---------------------------------------------------------------------------
def get_player_archetypes(player_name: str, season: str | None = None) -> dict[str, Any]:
    """
    Arquetipos de scouting de UM jogador, sem precisar de comparacao.

    Existe porque a avaliacao mostrou a lacuna: perguntado "que tipo de jogador
    e o Gobert?", o modelo nao chamava compare_players (nao ha com quem
    comparar) e respondia de memoria. O arquetipo e o mesmo calculo
    deterministico usado na comparacao, so que exposto sozinho.
    """
    player, err = _player_or_error(player_name)
    if err:
        return err

    alvo, aviso = similarity.season_for_player(player["id"], season)
    if alvo is None:
        return {
            "error": "no_season_data",
            "player": player["full_name"],
            "message": f"{player['full_name']}: {aviso}",
        }

    estilo = similarity.get_space(alvo).style_of(player["id"])
    if estilo is None:
        return {
            "error": "not_in_population",
            "player": player["full_name"],
            "season": alvo,
            "message": (
                f"{player['full_name']} nao aparece na base de estilo de {alvo} "
                f"(minimo de {similarity.MIN_GP} jogos e {similarity.MIN_MPG} min/jogo)."
            ),
        }

    perfil = similarity.profile_of(estilo)
    return _with_meta({
        "player": estilo.name,
        "player_id": estilo.player_id,
        "season": alvo,
        "team": estilo.team,
        "games": estilo.games,
        "minutes_per_game": estilo.minutes,
        "small_sample": estilo.small_sample,
        "summary": perfil["summary"],
        "signature": perfil["signature"],
        "categories": perfil["categories"],
        "features_used": len(estilo.z),
        "method": perfil["method"],
        "note": (
            "Arquetipo derivado por regra deterministica sobre os z-scores da "
            "propria temporada. Use os rotulos como vierem; nao crie rotulos novos."
        ),
    },
        name_match=_name_match(player_name, player),
        notes=[aviso] if aviso else None,
    )


# ---------------------------------------------------------------------------
# 5. Bio
# ---------------------------------------------------------------------------
def get_player_bio(player_name: str) -> dict[str, Any]:
    player, err = _player_or_error(player_name)
    if err:
        return err

    info = nba_data.player_info_frame(player["id"])
    if info.empty:
        return {"error": "no_data", "player": player["full_name"]}
    row = info.iloc[0]

    def g(col):
        v = row.get(col)
        return None if v is None or str(v).strip() in ("", "nan", "None") else str(v)

    seasons = nba_data.available_seasons(player["id"])
    return _with_meta({
        "player": player["full_name"],
        "player_id": player["id"],
        "is_active": player["is_active"],
        "position": g("POSITION"),
        "height": g("HEIGHT"),
        "weight_lbs": g("WEIGHT"),
        "birthdate": (g("BIRTHDATE") or "")[:10] or None,
        "country": g("COUNTRY"),
        "school": g("SCHOOL"),
        "team": " ".join(x for x in [g("TEAM_CITY"), g("TEAM_NAME")] if x) or None,
        "team_abbreviation": g("TEAM_ABBREVIATION"),
        "jersey": g("JERSEY"),
        "draft": {
            "year": g("DRAFT_YEAR"),
            "round": g("DRAFT_ROUND"),
            "number": g("DRAFT_NUMBER"),
        },
        "seasons_experience": g("SEASON_EXP"),
        "from_year": g("FROM_YEAR"),
        "to_year": g("TO_YEAR"),
        "seasons_with_data": seasons[-10:],
        "greatest_75": g("GREATEST_75_FLAG"),
        "not_provided": (
            "Este perfil nao inclui salario, contrato, premios individuais, titulos "
            "nem historico de lesoes -- nenhuma tool deste sistema fornece esses dados."
        ),
    },
        name_match=_name_match(player_name, player),
    )


# ---------------------------------------------------------------------------
# 6. Imagem oficial
# ---------------------------------------------------------------------------
def get_player_image(player_name: str) -> dict[str, Any]:
    """
    Headshot oficial, sempre 1040x760 (mesma resolucao e proporcao para todos).

    Endpoint verificado por teste real -- ver nota em nba_data.HEADSHOT_URL.
    Como o CDN responde 200 mesmo para jogador sem foto (entregando uma silhueta
    generica), a deteccao de "sem foto" e feita por hash do conteudo, e o campo
    has_official_photo diz a UI se deve desenhar o fallback proprio (monograma).
    """
    player, err = _player_or_error(player_name)
    if err:
        return err

    url, has_photo = nba_data.headshot_status(player["id"])
    width, height = nba_data.HEADSHOT_SIZE
    initials = "".join(part[0] for part in player["full_name"].split()[:2]).upper()

    return _with_meta({
        "player": player["full_name"],
        "player_id": player["id"],
        "image_url": url,
        "has_official_photo": has_photo,
        "width": width,
        "height": height,
        "aspect_ratio": round(width / height, 3),
        "fallback": {
            "type": "monogram",
            "initials": initials,
            "cdn_silhouette_url": nba_data.HEADSHOT_FALLBACK_URL,
        },
        "note": (
            "Foto oficial encontrada."
            if has_photo
            else "Sem foto oficial no CDN da NBA; a interface exibe um monograma."
        ),
    },
        name_match=_name_match(player_name, player),
    )


# ---------------------------------------------------------------------------
# Registro + schemas (formato OpenRouter / OpenAI)
# ---------------------------------------------------------------------------
TOOL_FUNCTIONS: dict[str, Callable[..., dict]] = {
    "get_player_season_stats": get_player_season_stats,
    "get_recent_games": get_recent_games,
    "compare_players": compare_players,
    "get_player_archetypes": get_player_archetypes,
    "get_player_bio": get_player_bio,
    "get_player_image": get_player_image,
}

_SEASON_DESC = (
    "Temporada no formato AAAA-AA, por exemplo 2025-26. "
    "Omita para usar a temporada mais recente do jogador."
)

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_player_season_stats",
            "description": (
                "Medias e totais oficiais de um jogador em uma temporada: pontos, "
                "rebotes, assistencias, aproveitamentos e true shooting. Use sempre "
                "que a pergunta envolver numeros de temporada."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {"type": "string", "description": "Nome do jogador."},
                    "season": {"type": "string", "description": _SEASON_DESC},
                },
                "required": ["player_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_games",
            "description": (
                "Box scores dos jogos mais recentes do jogador, com medias do recorte "
                "e campanha (vitorias/derrotas). Use para forma recente ou sequencia."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {"type": "string", "description": "Nome do jogador."},
                    "num_games": {
                        "type": "integer",
                        "description": "Quantos jogos retornar (1 a 25). Padrao 5.",
                        "minimum": 1,
                        "maximum": 25,
                    },
                    "season": {"type": "string", "description": _SEASON_DESC},
                },
                "required": ["player_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_players",
            "description": (
                "Compara ESTILO de jogo por vetor estatistico normalizado contra a liga "
                "(numpy, deterministico). Estilo e medido por COMPOSICAO -- de onde o "
                "jogador arremessa (zonas da quadra), como cria (drives, pull-up, catch & "
                "shoot), papel na ofensiva (usage), organizacao, rebote, defesa e fisico -- "
                "e NAO por volume de producao: dois jogadores nao sao parecidos so por "
                "marcarem muitos pontos. mode='pair' mede o quanto dois jogadores se "
                "parecem; mode='similar' lista os mais proximos. O resultado tambem traz "
                "ARQUETIPOS de scouting (ex.: 'Criador de Pick-and-Roll', 'Protetor de "
                "Aro') derivados por regra deterministica dos mesmos dados, com primario "
                "e secundario por categoria, e quais categorias os dois compartilham. "
                "Aceita temporadas diferentes para cada jogador (season_a / season_b), "
                "util para comparar auges de eras distintas. Dados vao de 1996-97 ate hoje."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "player_a": {"type": "string", "description": "Jogador de referencia."},
                    "player_b": {
                        "type": "string",
                        "description": "Segundo jogador. Obrigatorio quando mode='pair'.",
                    },
                    "season": {
                        "type": "string",
                        "description": (
                            "Temporada AAAA-AA aplicada aos dois jogadores. Omita para usar "
                            "a mais recente de cada um. Se o jogador nao tiver jogado nela, "
                            "a tool cai para a temporada mais recente dele e avisa."
                        ),
                    },
                    "season_a": {
                        "type": "string",
                        "description": (
                            "Temporada so do player_a, para comparar momentos diferentes "
                            "de carreira (ex.: o MVP de um contra o MVP do outro)."
                        ),
                    },
                    "season_b": {
                        "type": "string",
                        "description": "Temporada so do player_b.",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["pair", "similar"],
                        "description": "'pair' compara dois jogadores; 'similar' busca semelhantes.",
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "Quantos semelhantes retornar em mode='similar' (1 a 10).",
                        "minimum": 1,
                        "maximum": 10,
                    },
                    "cross_era": {
                        "type": "boolean",
                        "description": (
                            "Em mode='similar', busca tambem em temporadas historicas "
                            "(1996-97 em diante) em vez de so na temporada atual. Use para "
                            "perguntas do tipo 'com quem ele se pareceria em outra era'."
                        ),
                    },
                },
                "required": ["player_a"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_player_archetypes",
            "description": (
                "Arquetipos de scouting de UM jogador, sem precisar comparar com "
                "outro. Devolve o arquetipo primario (e as vezes um secundario) em "
                "cada categoria: perfil de arremesso, criacao, organizacao, defesa, "
                "rebote, papel na equipe e fisico -- com rotulos prontos como "
                "'Protetor de Aro', 'Criador de Pick-and-Roll' ou 'Especialista de "
                "Funcao (3&D)'. Use SEMPRE que a pergunta for do tipo 'que tipo de "
                "jogador e X', 'qual o estilo/perfil/arquetipo de X', 'como X joga'. "
                "Derivado por regra deterministica dos mesmos z-scores da "
                "similaridade -- nao e opiniao."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {"type": "string", "description": "Nome do jogador."},
                    "season": {"type": "string", "description": _SEASON_DESC},
                },
                "required": ["player_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_player_bio",
            "description": (
                "Perfil do jogador: posicao, altura, peso, time atual, draft, pais, "
                "universidade e anos de experiencia."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {"type": "string", "description": "Nome do jogador."},
                },
                "required": ["player_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_player_image",
            "description": (
                "URL da foto oficial do jogador, padronizada em 1040x760. Chame SEMPRE "
                "que o usuario perguntar sobre um jogador especifico, junto das demais "
                "tools, para a interface exibir a imagem ao lado da resposta."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {"type": "string", "description": "Nome do jogador."},
                },
                "required": ["player_name"],
            },
        },
    },
]
