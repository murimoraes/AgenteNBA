"""
Similaridade de ESTILO entre jogadores -- 100% deterministico, sem LLM.

Principio central: estilo e FORMA, nao TAMANHO.
Dois jogadores nao sao parecidos por marcarem muito; sao parecidos por marcarem
do mesmo jeito, dos mesmos lugares, criando da mesma maneira. Por isso o vetor e
dominado por features de COMPOSICAO (fracoes que somam 1, taxas por posse),
enquanto magnitude de producao entra com peso deliberadamente baixo.

Isso e o que separa Jokic de Giannis: ambos sao gigantes de alto uso, mas 67% dos
arremessos do Giannis saem do garrafao restrito contra 28% do Jokic, que por sua
vez tira 24% de tres acima da linha contra 7% do Giannis.

Camadas por era (ver nba_data.era_tiers):
  core     1996-97+   box score, advanced, zonas de arremesso, fisico
  tracking 2013-14+   drives, defesa no aro, pull-up vs catch&shoot, post
  hustle   2015-16+   deflexoes, arremessos contestados

Comparar temporadas de eras diferentes usa apenas a INTERSECAO das camadas, e o
resultado declara quais features entraram. Cada jogador e normalizado contra a
liga da PROPRIA temporada, entao a comparacao ja e ajustada por era.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pandas as pd

import nba_data

# Filtro de elegibilidade para a populacao de referencia e para aparecer como
# "parecido". Afrouxado de propósito: 20 jogos descartava 197 dos 582 jogadores
# de 2025-26, escondendo gente relevante sem avisar.
MIN_GP = 10
MIN_MPG = 10.0
SMALL_SAMPLE_GP = 25  # abaixo disso o resultado sai marcado como amostra pequena


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    group: str
    tier: str = "core"


# O peso do grupo e dividido entre as features DISPONIVEIS dele, entao a remocao
# de uma camada nao desequilibra o vetor -- so reduz a resolucao.
FEATURES: tuple[Feature, ...] = (
    # ---- Perfil de arremesso: de onde o jogador ataca. Fracoes que somam 1. ----
    Feature("SHOT_RA",      "% arremessos no garrafao restrito", "shot_profile"),
    Feature("SHOT_PAINT",   "% arremessos no garrafao (fora RA)", "shot_profile"),
    Feature("SHOT_MID",     "% arremessos de media distancia",   "shot_profile"),
    Feature("SHOT_C3",      "% arremessos de 3 do canto",        "shot_profile"),
    Feature("SHOT_AB3",     "% arremessos de 3 acima da linha",  "shot_profile"),
    Feature("FTA_RATE",     "Lances livres por arremesso",       "shot_profile"),
    # ---- Criacao: como o jogador gera o proprio arremesso ----
    Feature("DRIVES_36",     "Drives / 36 min",                  "creation", "tracking"),
    Feature("PULLUP_SHARE",  "% de arremessos em pull-up",       "creation", "tracking"),
    Feature("CATCH_SHARE",   "% de arremessos em catch & shoot", "creation", "tracking"),
    Feature("POST_36",       "Toques de post / 36 min",          "creation", "tracking"),
    # ---- Organizacao: quanto cria para os outros dada a posse que tem ----
    Feature("AST_PCT",      "Assist %",                          "playmaking"),
    Feature("AST_TO",       "Assistencias por turnover",         "playmaking"),
    Feature("AST_PER_USG",  "Assist % por unidade de uso",       "playmaking"),
    Feature("PASS_36",      "Passes / 36 min",                   "playmaking", "tracking"),
    # ---- Rebote: taxa de aproveitamento das chances, nao contagem ----
    Feature("OREB_PCT",     "Rebote ofensivo %",                 "rebounding"),
    Feature("DREB_PCT",     "Rebote defensivo %",                "rebounding"),
    # ---- Defesa ----
    Feature("STL_36",         "Roubos / 36 min",                 "defense"),
    Feature("BLK_36",         "Tocos / 36 min",                  "defense"),
    Feature("RIM_DFGA_36",    "Arremessos no aro defendidos / 36", "defense", "tracking"),
    Feature("RIM_DFG_PCT",    "FG% do adversario no aro",        "defense", "tracking"),
    Feature("DEFLECT_36",     "Deflexoes / 36 min",              "defense", "hustle"),
    Feature("CONTEST_36",     "Arremessos contestados / 36 min", "defense", "hustle"),
    # ---- Fisico: proxy continuo de posicao ----
    Feature("HEIGHT_IN",    "Altura (pol)",                      "physique"),
    Feature("WEIGHT_LB",    "Peso (lb)",                         "physique"),
    # ---- Papel na ofensiva ----
    # Usage NAO e producao: e quanto das posses do time passam por voce. Separa
    # opcao primaria de coadjuvante, e isso e estilo. Sem peso real aqui, um
    # arremessador de banco com o mesmo mapa de arremesso vira "igual ao Curry".
    Feature("USG_PCT",      "Usage %",                           "role"),
    # ---- Producao: PESO BAIXO DE PROPOSITO ----
    # Marcar 30 ou 15 pontos nao faz dois jogadores parecidos nem diferentes:
    # diz o quanto jogam, nao como. Entra so para nao ignorar o patamar.
    Feature("PTS_36",       "Pontos / 36 min",                   "volume"),
    Feature("FGA_36",       "Arremessos / 36 min",               "volume"),
    Feature("TS_PCT",       "True Shooting %",                   "volume"),
)

GROUP_WEIGHTS: dict[str, float] = {
    "shot_profile": 2.0,   # de onde ataca -- o separador mais forte de estilo
    "creation":     1.3,   # como gera o arremesso
    "playmaking":   1.3,   # quanto cria para os outros
    "defense":      1.1,
    "rebounding":   0.9,
    "role":         0.9,   # opcao primaria x coadjuvante
    "physique":     0.8,
    "volume":       0.35,  # baixo de proposito: producao nao define estilo
}

BY_KEY = {f.key: f for f in FEATURES}


@dataclass
class PlayerStyle:
    player_id: int
    name: str
    season: str
    team: str
    raw: dict[str, float]
    z: dict[str, float]            # z-score por feature (sem peso)
    minutes: float
    games: int
    small_sample: bool
    tiers: set[str]


@dataclass
class ComparisonResult:
    a: PlayerStyle
    b: PlayerStyle
    cosine: float
    distance: float
    resemblance: float             # 0-100 em escala ABSOLUTA de distancia
    percentile: float              # 0-100 relativo a liga (o antigo "score")
    features_used: list[str]
    tiers_used: set[str]
    per_feature: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Derivacao das features a partir da tabela league-wide
# ---------------------------------------------------------------------------
_ZONAS = {
    "SHOT_RA":    "Restricted Area_FGA",
    "SHOT_PAINT": "In The Paint (Non-RA)_FGA",
    "SHOT_MID":   "Mid-Range_FGA",
    "SHOT_AB3":   "Above the Break 3_FGA",
}


def _derive(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    minutes = pd.to_numeric(out["MIN"], errors="coerce").replace(0, np.nan)
    per36 = 36.0 / minutes
    fga = pd.to_numeric(out["FGA"], errors="coerce").replace(0, np.nan)

    # --- perfil de arremesso: fracao do total de tentativas por zona ---
    zona_cols = [c for c in _ZONAS.values() if c in out.columns]
    corner = [c for c in ("Left Corner 3_FGA", "Right Corner 3_FGA") if c in out.columns]
    if zona_cols:
        total = sum(pd.to_numeric(out[c], errors="coerce").fillna(0) for c in zona_cols)
        if corner:
            total = total + sum(pd.to_numeric(out[c], errors="coerce").fillna(0) for c in corner)
        total = total.replace(0, np.nan)
        for key, col in _ZONAS.items():
            if col in out.columns:
                out[key] = pd.to_numeric(out[col], errors="coerce") / total
        out["SHOT_C3"] = (
            sum(pd.to_numeric(out[c], errors="coerce").fillna(0) for c in corner) / total
            if corner else np.nan
        )

    out["FTA_RATE"] = pd.to_numeric(out["FTA"], errors="coerce") / fga

    # --- organizacao ---
    usg = pd.to_numeric(out.get("USG_PCT"), errors="coerce").replace(0, np.nan)
    out["AST_PER_USG"] = pd.to_numeric(out.get("AST_PCT"), errors="coerce") / usg
    if "AST_TO" not in out.columns:
        out["AST_TO"] = pd.to_numeric(out["AST"], errors="coerce") / pd.to_numeric(
            out["TOV"], errors="coerce").replace(0, np.nan)

    # --- taxas por 36 ---
    for key, col in [("STL_36", "STL"), ("BLK_36", "BLK"), ("PTS_36", "PTS"),
                     ("FGA_36", "FGA")]:
        out[key] = pd.to_numeric(out[col], errors="coerce") * per36

    # --- tracking ---
    if "DRIVES" in out.columns:
        gp = pd.to_numeric(out["GP"], errors="coerce").replace(0, np.nan)
        # Drives vem como TOTAL da temporada; vira por-36 via minutos totais.
        out["DRIVES_36"] = pd.to_numeric(out["DRIVES"], errors="coerce") / gp * per36
    if "POST_TOUCHES" in out.columns:
        gp = pd.to_numeric(out["GP"], errors="coerce").replace(0, np.nan)
        out["POST_36"] = pd.to_numeric(out["POST_TOUCHES"], errors="coerce") / gp * per36
    if "PASSES_MADE" in out.columns:
        gp = pd.to_numeric(out["GP"], errors="coerce").replace(0, np.nan)
        out["PASS_36"] = pd.to_numeric(out["PASSES_MADE"], errors="coerce") / gp * per36
    if "PULL_UP_FGA" in out.columns:
        gp = pd.to_numeric(out["GP"], errors="coerce").replace(0, np.nan)
        out["PULLUP_SHARE"] = pd.to_numeric(out["PULL_UP_FGA"], errors="coerce") / gp / fga
    if "CATCH_SHOOT_FGA" in out.columns:
        gp = pd.to_numeric(out["GP"], errors="coerce").replace(0, np.nan)
        out["CATCH_SHARE"] = pd.to_numeric(out["CATCH_SHOOT_FGA"], errors="coerce") / gp / fga
    if "DEF_RIM_FGA" in out.columns:
        gp = pd.to_numeric(out["GP"], errors="coerce").replace(0, np.nan)
        out["RIM_DFGA_36"] = pd.to_numeric(out["DEF_RIM_FGA"], errors="coerce") / gp * per36
    if "DEF_RIM_FG_PCT" in out.columns:
        out["RIM_DFG_PCT"] = pd.to_numeric(out["DEF_RIM_FG_PCT"], errors="coerce")

    # --- hustle (ja normalizado por jogo em nba_data) ---
    if "DEFLECTIONS" in out.columns:
        out["DEFLECT_36"] = pd.to_numeric(out["DEFLECTIONS"], errors="coerce") * per36
    if "CONTESTED_SHOTS" in out.columns:
        out["CONTEST_36"] = pd.to_numeric(out["CONTESTED_SHOTS"], errors="coerce") * per36

    out["HEIGHT_IN"] = pd.to_numeric(out.get("PLAYER_HEIGHT_INCHES"), errors="coerce")
    out["WEIGHT_LB"] = pd.to_numeric(out.get("PLAYER_WEIGHT"), errors="coerce")
    for key in ("USG_PCT", "TS_PCT", "AST_PCT", "OREB_PCT", "DREB_PCT"):
        if key in out.columns:
            out[key] = pd.to_numeric(out[key], errors="coerce")
    return out


def _population(df: pd.DataFrame) -> pd.DataFrame:
    gp = pd.to_numeric(df["GP"], errors="coerce")
    mpg = pd.to_numeric(df["MIN"], errors="coerce")
    qualified = df[(gp >= MIN_GP) & (mpg >= MIN_MPG)]
    return qualified if len(qualified) >= 50 else df


class SeasonSpace:
    """Espaco normalizado de uma temporada: quais features existem e seus z."""

    def __init__(self, season: str):
        self.season = season
        self.tiers = nba_data.era_tiers(season)
        self.frame = _derive(nba_data.league_frame(season))

        # Uma feature so entra se a coluna existe E tem dado util.
        self.keys: list[str] = []
        for f in FEATURES:
            if f.tier not in self.tiers:
                continue
            if f.key in self.frame.columns and self.frame[f.key].notna().sum() >= 30:
                self.keys.append(f.key)

        pop = _population(self.frame)
        mat = pop[self.keys].to_numpy(dtype=float)
        self.mean = np.nanmean(mat, axis=0)
        self.std = np.nanstd(mat, axis=0)
        self.std[self.std == 0] = 1.0

        self.pop_frame = pop.reset_index(drop=True)
        self.pop_z = self._z(mat)

    def _z(self, mat: np.ndarray) -> np.ndarray:
        z = (mat - self.mean) / self.std
        z = np.nan_to_num(z, nan=0.0, posinf=0.0, neginf=0.0)
        return np.clip(z, -4.0, 4.0)

    def style_of(self, player_id: int) -> PlayerStyle | None:
        rows = self.frame[self.frame["PLAYER_ID"] == player_id]
        if rows.empty:
            return None
        row = rows.iloc[0]
        vec = self._z(row[self.keys].to_numpy(dtype=float).reshape(1, -1))[0]
        gp = int(pd.to_numeric(row["GP"], errors="coerce") or 0)
        return PlayerStyle(
            player_id=int(row["PLAYER_ID"]),
            name=str(row["PLAYER_NAME"]),
            season=self.season,
            team=str(row.get("TEAM_ABBREVIATION", "")),
            raw={k: _as_float(row[k]) for k in self.keys},
            z={k: float(vec[i]) for i, k in enumerate(self.keys)},
            minutes=_as_float(row["MIN"]) or 0.0,
            games=gp,
            small_sample=gp < SMALL_SAMPLE_GP,
            tiers=self.tiers,
        )


def _as_float(v) -> float | None:
    try:
        f = float(v)
        return None if np.isnan(f) else round(f, 4)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=12)
def get_space(season: str) -> SeasonSpace:
    return SeasonSpace(season)


# ---------------------------------------------------------------------------
# Pesos e metricas
# ---------------------------------------------------------------------------
def _weights(keys: list[str]) -> np.ndarray:
    """Peso do grupo dividido entre as features presentes dele, depois normalizado."""
    por_grupo: dict[str, int] = {}
    for k in keys:
        por_grupo[BY_KEY[k].group] = por_grupo.get(BY_KEY[k].group, 0) + 1
    w = np.array([GROUP_WEIGHTS[BY_KEY[k].group] / por_grupo[BY_KEY[k].group]
                  for k in keys], dtype=float)
    return w / w.sum() * len(w)   # media 1, para a distancia nao depender de quantas


def _vectors(a: PlayerStyle, b: PlayerStyle) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Vetores restritos as features que os DOIS possuem."""
    keys = [k for k in a.z if k in b.z]
    w = _weights(keys)
    va = np.array([a.z[k] for k in keys]) * w
    vb = np.array([b.z[k] for k in keys]) * w
    return va, vb, keys


@lru_cache(maxsize=64)
def _pair_reference(season: str, keys: tuple[str, ...]) -> np.ndarray:
    """
    Distancias de TODOS os pares da temporada, no mesmo subconjunto de features.

    E a regua da escala: em vez de um exp() arbitrario, a semelhanca vira
    "que fracao dos pares da liga esta mais distante do que estes dois".
    Medido em 2025-26 (441 jogadores, 97.020 pares): mediana 7,26; p5 3,96.
    """
    sp = get_space(season)
    idx = [sp.keys.index(k) for k in keys]
    mat = sp.pop_z[:, idx] * _weights(list(keys))
    sq = (mat ** 2).sum(1)
    d2 = sq[:, None] + sq[None, :] - 2 * mat @ mat.T
    dists = np.sqrt(np.maximum(d2, 0.0))[np.triu_indices(len(mat), 1)]
    return np.sort(dists)


# Faixas do veredito. O modelo NAO deve precisar interpretar o numero sozinho:
# 51,6 parece alto para quem le "de 0 a 100", mas significa "tao parecidos quanto
# dois jogadores quaisquer". O rotulo em texto elimina essa leitura errada.
VERDICTS = (
    (88.0, "mesmo arquetipo"),
    (72.0, "bastante parecidos"),
    (58.0, "parecidos em alguns aspectos"),
    (42.0, "pouco parecidos -- proximos da media de qualquer dupla"),
    (20.0, "diferentes"),
    (0.0,  "opostos"),
)


def verdict_for(resemblance: float) -> str:
    for limite, rotulo in VERDICTS:
        if resemblance >= limite:
            return rotulo
    return VERDICTS[-1][1]


def _resemblance(dist: float, keys: list[str], *seasons: str) -> float:
    """
    Distancia -> 0-100 calibrado pela distribuicao real de pares.

    100 = mais parecidos que qualquer par da liga; 50 = tao parecidos quanto
    dois jogadores quaisquer. Quando as temporadas diferem, tira a media das
    duas reguas, para o valor nao depender de qual foi perguntado primeiro.
    """
    if not keys:
        return 0.0
    kt = tuple(keys)
    pcts = []
    for s in dict.fromkeys(seasons):
        ref = _pair_reference(s, kt)
        if ref.size:
            pcts.append(100.0 * float(np.searchsorted(ref, dist, "right")) / ref.size)
    if not pcts:
        return 0.0
    return round(100.0 - float(np.mean(pcts)), 1)


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------
def season_for_player(player_id: int, season: str | None) -> tuple[str | None, str | None]:
    """
    Temporada utilizavel para o jogador.

    Se a pedida nao existir para ele (lesao, aposentadoria, ainda nao estreou),
    cai para a mais recente em que ele de fato jogou. Devolve (temporada, aviso).
    """
    disponiveis = [s for s in nba_data.available_seasons(player_id)
                   if s >= nba_data.FIRST_SEASON]
    if not disponiveis:
        return None, "sem temporadas cobertas pela API (dados comecam em 1996-97)"

    if season and season in disponiveis:
        return season, None
    if season:
        alvo = disponiveis[-1]
        return alvo, f"nao jogou em {season}; usando {alvo}, a mais recente dele"
    return disponiveis[-1], None


def compare(player_a_id: int, season_a: str,
            player_b_id: int, season_b: str) -> ComparisonResult | None:
    """
    Compara dois jogadores, cada um normalizado contra a liga da propria
    temporada. Temporadas diferentes sao permitidas e a comparacao fica
    ajustada por era.
    """
    space_a, space_b = get_space(season_a), get_space(season_b)
    a, b = space_a.style_of(player_a_id), space_b.style_of(player_b_id)
    if a is None or b is None:
        return None

    va, vb, keys = _vectors(a, b)
    dist = float(np.linalg.norm(va - vb))
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    cos = float(np.dot(va, vb) / (na * nb)) if na and nb else 0.0

    d_all = np.linalg.norm(space_a.pop_z[:, [space_a.keys.index(k) for k in keys]]
                           * _weights(keys) - va, axis=1)
    d_all = d_all[d_all > 1e-9]
    percentil = round(float(100.0 * (d_all > dist).mean()), 1) if d_all.size else 0.0

    w = _weights(keys)
    per_feature = []
    for i, k in enumerate(keys):
        f = BY_KEY[k]
        per_feature.append({
            "feature": k, "label": f.label, "group": f.group,
            "a": a.raw.get(k), "b": b.raw.get(k),
            "z_a": round(a.z[k], 2), "z_b": round(b.z[k], 2),
            "gap_z": round(abs(a.z[k] - b.z[k]), 2),
            "peso": round(float(w[i]), 3),
            "contribuicao": round(float((w[i] * (a.z[k] - b.z[k])) ** 2), 3),
        })
    per_feature.sort(key=lambda d: d["contribuicao"], reverse=True)

    notes: list[str] = []
    tiers = space_a.tiers & space_b.tiers
    if season_a != season_b:
        notes.append(
            f"Temporadas diferentes ({season_a} x {season_b}): cada jogador foi "
            "normalizado contra a liga do proprio ano, entao a comparacao e ajustada por era."
        )
    faltando = {f.tier for f in FEATURES} - tiers - {"core"}
    if faltando:
        notes.append(
            f"Camadas indisponiveis nesta comparacao: {', '.join(sorted(faltando))}. "
            f"Usadas {len(keys)} features de {len(FEATURES)}."
        )
    for p in (a, b):
        if p.small_sample:
            notes.append(f"{p.name} tem apenas {p.games} jogos em {p.season}: amostra pequena.")

    return ComparisonResult(
        a=a, b=b, cosine=round(cos, 4), distance=round(dist, 4),
        resemblance=_resemblance(dist, keys, season_a, season_b), percentile=percentil,
        features_used=keys, tiers_used=tiers,
        per_feature=per_feature, notes=notes,
    )


def most_similar(player_id: int, season: str, n: int = 5,
                 cross_era: list[str] | None = None) -> dict | None:
    """
    Jogadores de estilo mais proximo.

    `cross_era` permite buscar tambem em outras temporadas (comparacao historica);
    cada temporada e normalizada contra si mesma antes da comparacao.
    """
    space = get_space(season)
    alvo = space.style_of(player_id)
    if alvo is None:
        return None

    temporadas = [season] + [s for s in (cross_era or []) if s != season]
    resultados: list[dict] = []

    for s in temporadas:
        sp = get_space(s)
        keys = [k for k in alvo.z if k in sp.keys]
        if not keys:
            continue
        w = _weights(keys)
        idx = [sp.keys.index(k) for k in keys]
        mat = sp.pop_z[:, idx] * w
        va = np.array([alvo.z[k] for k in keys]) * w
        dists = np.linalg.norm(mat - va, axis=1)
        for j, dist in enumerate(dists):
            row = sp.pop_frame.iloc[j]
            if int(row["PLAYER_ID"]) == player_id and s == season:
                continue
            resultados.append({
                "player_id": int(row["PLAYER_ID"]),
                "name": str(row["PLAYER_NAME"]),
                "team": str(row.get("TEAM_ABBREVIATION", "")),
                "season": s,
                "games": int(pd.to_numeric(row["GP"], errors="coerce") or 0),
                "distance": round(float(dist), 4),
                "resemblance": (res := _resemblance(float(dist), keys, s)),
                "verdict": verdict_for(res),
            })

    # Ordenar por distancia bruta seria errado ao misturar eras: uma temporada
    # sem tracking usa menos features e produz distancias sistematicamente
    # menores. A semelhanca e calibrada por temporada/subconjunto, entao e ela
    # que torna os numeros comparaveis entre eras.
    resultados.sort(key=lambda r: (-r["resemblance"], r["distance"]))
    top = resultados[:max(1, n)]

    # Isolamento: se ate o vizinho mais proximo esta longe, o jogador nao tem
    # analogo -- dizer isso e mais honesto do que entregar um nome qualquer.
    isolado = bool(top) and top[0]["resemblance"] < 55.0

    return {
        "player": alvo.name,
        "player_id": alvo.player_id,
        "season": season,
        "features_used": len(alvo.z),
        "most_similar": top,
        "isolated": isolado,
        "pool_size": len(space.pop_frame),
        "excluded": int(len(space.frame) - len(space.pop_frame)),
    }
