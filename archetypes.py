"""
Arquetipos de estilo: traducao do vetor de z-scores para vocabulario de scouting.

O problema que este modulo resolve
----------------------------------
A similaridade ja dizia QUANTO dois jogadores se parecem (0-100) e QUAIS features
mais os separam. Mas "Rebote defensivo %: 0.2 x 0.11" nao e uma frase de scouting
-- e uma linha de planilha. Faltava o passo que um olheiro humano da
automaticamente: olhar o perfil e dizer "esse e um armador de pick-and-roll",
"aquele e um protetor de aro".

Como funciona
-------------
Cada arquetipo e uma REGRA DETERMINISTICA sobre os z-scores que o
`similarity.py` ja calcula -- nenhum dado novo, nenhuma chamada ao modelo. Dois
tipos de sinal:

  signals  quanto MAIOR (ou menor, se o peso for negativo) o z, melhor.
           Serve para arquetipos de extremo: "Protetor de Aro" quer tocos alto.
  bands    quanto MAIS PERTO de um alvo, melhor.
           Serve para arquetipos de meio, que sinal linear nunca elegeria:
           "Coadjuvante de Luxo" e uso ACIMA da media mas longe de protagonista.

O encaixe de cada sinal vira uma "satisfacao" em [-1, 1], e o score do arquetipo
e a media ponderada dessas satisfacoes. Isso torna arquetipos com numeros
diferentes de sinais comparaveis entre si.

Primario e secundario
---------------------
Jogador raramente e um arquetipo puro. Por categoria devolvemos o primario e,
quando o segundo colocado esta perto, tambem o secundario -- em vez de forcar
uma gaveta unica onde a realidade e um espectro. Quando nem o primeiro colocado
atinge o piso, a resposta honesta e "perfil equilibrado", nao o menos ruim.

Este modulo nao importa `similarity` (a dependencia e de la para ca) e trabalha
apenas com um dicionario {chave_da_feature: z}. Por isso e testavel sem rede.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# z a partir do qual um sinal linear conta como totalmente satisfeito. 2.0 e
# ~2 desvios acima da liga: excepcional sem ser exigir outlier absoluto.
FULL_SIGNAL_Z = 2.0

# Fracao minima do peso do arquetipo que precisa estar disponivel na era.
# Temporada sem tracking nao tem "% em pull-up"; em vez de pontuar com meio
# vetor e fingir confianca, o arquetipo simplesmente nao concorre.
MIN_COVERAGE = 0.6

# Pisos de decisao.
MIN_PRIMARY_SCORE = 0.30     # abaixo disso: perfil equilibrado, sem rotulo
MIN_SECONDARY_SCORE = 0.22
SECONDARY_MARGIN = 0.15      # secundario so aparece se estiver perto do primario

CATEGORY_LABELS: dict[str, str] = {
    "shot_profile": "Perfil de arremesso",
    "creation": "Criacao de jogadas",
    "playmaking": "Organizacao e passe",
    "defense": "Defesa",
    "rebounding": "Rebote",
    "role": "Papel na equipe",
    "physique": "Perfil fisico",
}

CATEGORY_ORDER: tuple[str, ...] = tuple(CATEGORY_LABELS)


@dataclass(frozen=True)
class Band:
    """Sinal de proximidade: o ideal e ficar perto de `target`, nao no extremo."""

    weight: float
    target: float
    tolerance: float = 1.2


@dataclass(frozen=True)
class Archetype:
    key: str
    label: str
    category: str
    description: str
    signals: dict[str, float] = field(default_factory=dict)
    bands: dict[str, Band] = field(default_factory=dict)

    def total_weight(self) -> float:
        return (
            sum(abs(w) for w in self.signals.values())
            + sum(abs(b.weight) for b in self.bands.values())
        )


# ---------------------------------------------------------------------------
# Catalogo
# ---------------------------------------------------------------------------
# Os pesos sao hipoteses de dominio, no mesmo espirito de GROUP_WEIGHTS: sao
# defensaveis e explicitos, mas NAO estao validados empiricamente contra
# anotacao humana. Validar isso e a Fase 5 do roadmap.
ARCHETYPES: tuple[Archetype, ...] = (
    # ---------------------------------------------------------- arremesso ----
    Archetype(
        "arremessador_elite", "Arremessador de Elite", "shot_profile",
        "Bombardeiro de longa distancia que estica a defesa ate o meio da quadra.",
        signals={"SHOT_AB3": 1.0, "SHOT_C3": 0.2, "FGA_36": 0.3,
                 "SHOT_RA": -0.7, "SHOT_PAINT": -0.3},
    ),
    Archetype(
        "catch_and_shoot", "Especialista em Catch-and-Shoot", "shot_profile",
        "Nao cria o proprio arremesso, mas converte com eficiencia quando recebe pronto.",
        signals={"CATCH_SHARE": 1.0, "SHOT_AB3": 0.4, "SHOT_C3": 0.4,
                 "PULLUP_SHARE": -0.7, "USG_PCT": -0.4, "DRIVES_36": -0.3},
    ),
    Archetype(
        "media_distancia", "Pontuador de Media Distancia", "shot_profile",
        "Vive do arremesso intermediario, estilo raro hoje mas ainda letal.",
        signals={"SHOT_MID": 1.0, "PULLUP_SHARE": 0.3,
                 "SHOT_AB3": -0.3, "SHOT_RA": -0.3},
    ),
    Archetype(
        "finalizador_aro", "Finalizador Acrobatico no Aro", "shot_profile",
        "Usa explosao e criatividade para converter perto da cesta mesmo sob contato.",
        signals={"SHOT_RA": 0.9, "DRIVES_36": 0.6, "FTA_RATE": 0.4,
                 "SHOT_AB3": -0.6, "HEIGHT_IN": -0.3},
    ),
    Archetype(
        "muralha_garrafao", "Muralha do Garrafao", "shot_profile",
        "Converte quase tudo perto do aro, em geral via alley-oop ou rebote ofensivo.",
        signals={"SHOT_RA": 1.0, "SHOT_PAINT": 0.3, "HEIGHT_IN": 0.5, "TS_PCT": 0.3,
                 "SHOT_AB3": -0.7, "SHOT_MID": -0.4, "PULLUP_SHARE": -0.4},
    ),
    Archetype(
        "tres_do_canto", "Especialista de Tres do Canto", "shot_profile",
        "Ocupa o canto e converte quando a defesa fecha no garrafao.",
        signals={"SHOT_C3": 1.0, "CATCH_SHARE": 0.4, "USG_PCT": -0.5, "SHOT_MID": -0.2},
    ),
    Archetype(
        "mestre_lance_livre", "Mestre do Lance-Livre", "shot_profile",
        "Atrai faltas constantemente e vive da linha do lance livre.",
        signals={"FTA_RATE": 1.0, "DRIVES_36": 0.3, "USG_PCT": 0.3},
    ),
    # ------------------------------------------------------------ criacao ----
    Archetype(
        "pick_and_roll", "Criador de Pick-and-Roll", "creation",
        "Comanda o jogo de tela, decidindo entre arremessar, passar ou finalizar.",
        signals={"PULLUP_SHARE": 0.8, "USG_PCT": 0.6, "AST_PCT": 0.5,
                 "DRIVES_36": 0.4, "CATCH_SHARE": -0.5},
    ),
    Archetype(
        "isolamento", "Especialista em Isolamento", "creation",
        "Resolve a posse sozinho no 1x1, geralmente em momentos decisivos.",
        signals={"USG_PCT": 0.9, "PULLUP_SHARE": 0.6, "SHOT_MID": 0.4,
                 "AST_PER_USG": -0.6, "CATCH_SHARE": -0.4},
    ),
    Archetype(
        "motorista_drives", "Motorista de Drives", "creation",
        "Vive de ataques ao aro a partir do perimetro, forcando faltas e rotacoes.",
        signals={"DRIVES_36": 1.0, "FTA_RATE": 0.4, "SHOT_RA": 0.3,
                 "SHOT_AB3": -0.3, "POST_36": -0.2},
    ),
    Archetype(
        "criador_pullup", "Criador Pull-Up", "creation",
        "Para e arremessa no meio do drible, sem depender de tela ou passe.",
        signals={"PULLUP_SHARE": 1.0, "SHOT_AB3": 0.4, "CATCH_SHARE": -0.6},
    ),
    Archetype(
        "jogo_de_costas", "Jogador de Costas para a Cesta", "creation",
        "Ataca a partir do poste baixo, usando fisico e repertorio de pivo classico.",
        signals={"POST_36": 1.0, "SHOT_PAINT": 0.4, "HEIGHT_IN": 0.4,
                 "SHOT_AB3": -0.4, "DRIVES_36": -0.3},
    ),
    Archetype(
        "pivo_criador", "Pivo-Criador", "creation",
        "Arma jogadas a partir do garrafao ou do meio da quadra, funcao rara para um pivo.",
        signals={"AST_PCT": 0.7, "AST_PER_USG": 0.6, "HEIGHT_IN": 0.6,
                 "POST_36": 0.5, "PASS_36": 0.4},
    ),
    Archetype(
        "finalizador_sem_bola", "Finalizador Sem Bola", "creation",
        "Vive de cortes e rolamentos: quem cria e o companheiro, ele conclui.",
        signals={"CATCH_SHARE": 0.7, "SHOT_RA": 0.5,
                 "USG_PCT": -0.5, "PULLUP_SHARE": -0.5, "DRIVES_36": -0.3},
    ),
    # ------------------------------------------------------- organizacao ----
    Archetype(
        "armador_puro", "Armador Puro", "playmaking",
        "Prioriza encontrar o companheiro livre antes de pensar no proprio arremesso.",
        signals={"AST_PCT": 1.0, "AST_PER_USG": 0.8, "PASS_36": 0.6,
                 "AST_TO": 0.5, "USG_PCT": -0.2},
    ),
    Archetype(
        "pivo_passador", "Pivo Passador", "playmaking",
        "Distribui o jogo do alto do garrafao, criando para cortes e arremessadores.",
        signals={"AST_PER_USG": 0.8, "HEIGHT_IN": 0.8, "PASS_36": 0.5,
                 "AST_PCT": 0.4, "SHOT_AB3": -0.2},
    ),
    Archetype(
        "ala_facilitador", "Ala Facilitador", "playmaking",
        "Sem ser o armador titular, enxerga o jogo e cria para os outros com frequencia.",
        signals={"AST_PCT": 0.7, "PASS_36": 0.5, "AST_PER_USG": 0.4},
        bands={"HEIGHT_IN": Band(weight=0.5, target=0.4, tolerance=1.2)},
    ),
    Archetype(
        "combo_guard", "Combo Guard com Visao de Jogo", "playmaking",
        "Mistura pontuacao e passe, decidindo conforme a defesa reage.",
        signals={"USG_PCT": 0.7, "AST_PCT": 0.6, "PULLUP_SHARE": 0.4,
                 "HEIGHT_IN": -0.4, "AST_TO": -0.2},
    ),
    Archetype(
        "conector_ritmo", "Conector de Ritmo", "playmaking",
        "Nao busca protagonismo, mas mantem a bola circulando e o ataque fluindo.",
        signals={"PASS_36": 0.9, "AST_TO": 0.6, "AST_PCT": 0.2, "USG_PCT": -0.5},
    ),
    Archetype(
        "seguro_com_a_bola", "Seguro com a Bola", "playmaking",
        "Cria sem entregar posse: volume de assistencia muito acima do de erros.",
        signals={"AST_TO": 1.0, "AST_PER_USG": 0.4, "USG_PCT": -0.2},
    ),
    # ------------------------------------------------------------- defesa ----
    Archetype(
        "trancafiador_perimetro", "Trancafiador de Perimetro", "defense",
        "Assume a marcacao do principal criador adversario no 1x1.",
        signals={"DEFLECT_36": 0.6, "STL_36": 0.6, "CONTEST_36": 0.5,
                 "HEIGHT_IN": -0.3, "BLK_36": -0.2},
    ),
    Archetype(
        "protetor_aro", "Protetor de Aro", "defense",
        "Domina a area pintada bloqueando e intimidando finalizacoes perto da cesta.",
        signals={"BLK_36": 1.0, "RIM_DFGA_36": 0.8, "HEIGHT_IN": 0.6,
                 "RIM_DFG_PCT": -0.6},
    ),
    Archetype(
        "ladrao_de_bola", "Ladrao de Bola", "defense",
        "Especialista em interceptacao: le a linha de passe e gera transicao.",
        signals={"STL_36": 1.0, "DEFLECT_36": 0.8, "BLK_36": -0.1},
    ),
    Archetype(
        "ala_versatil", "Ala Versatil (defende 1 a 4)", "defense",
        "Troca de marcacao sem perder eficiencia, peca-chave de esquemas modernos.",
        signals={"CONTEST_36": 0.6, "DEFLECT_36": 0.5, "STL_36": 0.4, "BLK_36": 0.4},
        bands={"HEIGHT_IN": Band(weight=0.5, target=0.5, tolerance=1.3)},
    ),
    Archetype(
        "muralha_movel", "Muralha Movel", "defense",
        "Grandalhao com mobilidade para defender no garrafao e sobreviver no perimetro.",
        signals={"BLK_36": 0.7, "HEIGHT_IN": 0.6, "STL_36": 0.5,
                 "DEFLECT_36": 0.5, "RIM_DFGA_36": 0.4},
    ),
    Archetype(
        "incomodador_passe", "Incomodador de Passe", "defense",
        "Nao necessariamente rouba, mas desvia e atrapalha linhas de passe o tempo todo.",
        signals={"DEFLECT_36": 1.0, "CONTEST_36": 0.5, "STL_36": 0.3},
    ),
    Archetype(
        "contestador_volume", "Contestador de Volume", "defense",
        "Aparece em quantidade enorme de arremessos contestados, por posicionamento.",
        signals={"CONTEST_36": 1.0, "RIM_DFGA_36": 0.5, "HEIGHT_IN": 0.3},
    ),
    # ------------------------------------------------------------- rebote ----
    Archetype(
        "reboteiro_ofensivo", "Reboteiro Ofensivo", "rebounding",
        "Persegue a bola perdida no ataque para gerar segundas chances.",
        signals={"OREB_PCT": 1.0, "SHOT_RA": 0.3, "DREB_PCT": 0.2},
    ),
    Archetype(
        "reboteiro_defensivo", "Reboteiro Defensivo Dominante", "rebounding",
        "Encerra a posse adversaria com consistencia no garrafao.",
        signals={"DREB_PCT": 1.0, "HEIGHT_IN": 0.3, "OREB_PCT": 0.2},
    ),
    Archetype(
        "dominante_dois_lados", "Dominante nos Dois Lados do Rebote", "rebounding",
        "Alto volume de rebote tanto no ataque quanto na defesa.",
        signals={"OREB_PCT": 0.9, "DREB_PCT": 0.9, "HEIGHT_IN": 0.3},
    ),
    Archetype(
        "ala_reboteira", "Ala Reboteira", "rebounding",
        "Sem ser pivo, briga bem no rebote por envergadura e posicionamento.",
        signals={"DREB_PCT": 0.7, "OREB_PCT": 0.4},
        bands={"HEIGHT_IN": Band(weight=0.6, target=0.3, tolerance=1.2)},
    ),
    Archetype(
        "rebote_de_armador", "Reboteiro de Armador", "rebounding",
        "Baixo que rebota como ala e ja sai conduzindo o contra-ataque.",
        signals={"DREB_PCT": 0.8, "HEIGHT_IN": -0.7, "AST_PCT": 0.3},
    ),
    # ----------------------------------------------------- papel na equipe ----
    Archetype(
        "protagonista", "Protagonista Ofensivo", "role",
        "A equipe roda em torno dele: alto volume de posses e de responsabilidade.",
        signals={"USG_PCT": 1.0, "PTS_36": 0.6, "FGA_36": 0.6},
    ),
    Archetype(
        "coadjuvante_luxo", "Coadjuvante de Luxo", "role",
        "Segunda ou terceira opcao: pontua bem sem precisar da bola o tempo todo.",
        signals={"TS_PCT": 0.3},
        bands={"USG_PCT": Band(weight=1.0, target=0.6, tolerance=1.0),
               "PTS_36": Band(weight=0.5, target=0.5, tolerance=1.2)},
    ),
    Archetype(
        "especialista_funcao", "Especialista de Funcao (3&D)", "role",
        "Papel definido e sem floreio: arremessar de tres e defender bem.",
        signals={"USG_PCT": -0.8, "SHOT_AB3": 0.5, "SHOT_C3": 0.5,
                 "CATCH_SHARE": 0.5, "DEFLECT_36": 0.3},
    ),
    Archetype(
        "pontuador_eficiente", "Pontuador Eficiente", "role",
        "Produz muito por arremesso tomado: aproveitamento acima do volume.",
        signals={"TS_PCT": 1.0, "PTS_36": 0.6, "FGA_36": 0.2},
    ),
    Archetype(
        "faz_tudo", "Faz-Tudo", "role",
        "Contribui em varias frentes sem concentrar posse; o time piora sem ele.",
        signals={"AST_PCT": 0.5, "DREB_PCT": 0.4, "STL_36": 0.4, "TS_PCT": 0.3},
        bands={"USG_PCT": Band(weight=0.5, target=0.0, tolerance=1.2)},
    ),
    Archetype(
        "volume_sobre_eficiencia", "Volume Acima da Eficiencia", "role",
        "Arremessa muito para o retorno que da: alto uso com aproveitamento baixo.",
        signals={"FGA_36": 0.9, "USG_PCT": 0.6, "TS_PCT": -0.8},
    ),
    # ------------------------------------------------------- perfil fisico ----
    Archetype(
        "armador_compacto", "Armador Compacto", "physique",
        "Baixa estatura compensada por agilidade e mudanca de direcao.",
        signals={"HEIGHT_IN": -1.0, "WEIGHT_LB": -0.7},
    ),
    Archetype(
        "guarda_encorpado", "Guarda Encorpado", "physique",
        "Baixo, porem forte: aguenta contato e defende acima do tamanho.",
        signals={"WEIGHT_LB": 0.6},
        bands={"HEIGHT_IN": Band(weight=0.7, target=-0.8, tolerance=1.0)},
    ),
    Archetype(
        "ala_longilineo", "Ala Longilineo", "physique",
        "Altura acima da media para a posicao, com estrutura leve.",
        signals={"HEIGHT_IN": 0.8, "WEIGHT_LB": -0.4},
    ),
    Archetype(
        "ala_padrao", "Porte de Ala Padrao", "physique",
        "Fisico dentro da media da liga, sem extremo de altura nem de peso.",
        bands={"HEIGHT_IN": Band(weight=1.0, target=0.0, tolerance=1.0),
               "WEIGHT_LB": Band(weight=1.0, target=0.0, tolerance=1.0)},
    ),
    Archetype(
        "ala_pivo_musculoso", "Ala-Pivo Musculoso", "physique",
        "Forca e estrutura para atuar tanto no perimetro quanto no garrafao.",
        signals={"WEIGHT_LB": 1.0},
        bands={"HEIGHT_IN": Band(weight=0.6, target=0.8, tolerance=1.2)},
    ),
    Archetype(
        "pivo_classico", "Estrutura de Pivo Classico", "physique",
        "Porte tradicional de pivo: alto e pesado, dominante no espaco curto.",
        signals={"HEIGHT_IN": 0.9, "WEIGHT_LB": 0.9},
    ),
)

BY_KEY: dict[str, Archetype] = {a.key: a for a in ARCHETYPES}

_BY_CATEGORY: dict[str, list[Archetype]] = {}
for _arch in ARCHETYPES:
    _BY_CATEGORY.setdefault(_arch.category, []).append(_arch)


# ---------------------------------------------------------------------------
# Pontuacao
# ---------------------------------------------------------------------------
def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _score(arch: Archetype, z: dict[str, float]) -> tuple[float, float, list[dict]]:
    """
    (score, cobertura, evidencia) do arquetipo para um vetor de z-scores.

    score em [-1, 1]: 1 = encaixe perfeito, 0 = indiferente, negativo = o oposto.
    A media ponderada usa apenas os sinais DISPONIVEIS, entao eras com menos
    features nao sao penalizadas -- quem controla isso e a cobertura.
    """
    total = arch.total_weight()
    if not total:
        return 0.0, 0.0, []

    acumulado = 0.0
    disponivel = 0.0
    evidencia: list[dict] = []

    for key, weight in arch.signals.items():
        if key not in z:
            continue
        satisfacao = _clip(z[key] / FULL_SIGNAL_Z)
        if weight < 0:
            satisfacao = -satisfacao
        peso = abs(weight)
        acumulado += satisfacao * peso
        disponivel += peso
        evidencia.append({
            "feature": key,
            "z": round(z[key], 2),
            "esperado": "alto" if weight > 0 else "baixo",
            "encaixe": round(satisfacao, 3),
            "peso": peso,
        })

    for key, band in arch.bands.items():
        if key not in z:
            continue
        satisfacao = _clip(1.0 - abs(z[key] - band.target) / band.tolerance)
        peso = abs(band.weight)
        acumulado += satisfacao * peso
        disponivel += peso
        evidencia.append({
            "feature": key,
            "z": round(z[key], 2),
            "esperado": f"proximo de {band.target:+.1f}",
            "encaixe": round(satisfacao, 3),
            "peso": peso,
        })

    if not disponivel:
        return 0.0, 0.0, []

    evidencia.sort(key=lambda e: e["encaixe"] * e["peso"], reverse=True)
    return acumulado / disponivel, disponivel / total, evidencia


def _entry(arch: Archetype, score: float, evidencia: list[dict]) -> dict:
    return {
        "key": arch.key,
        "label": arch.label,
        "description": arch.description,
        "score": round(score, 3),
        "evidence": evidencia[:3],
    }


def classify_category(z: dict[str, float], category: str) -> dict:
    """Arquetipo primario e secundario de uma categoria."""
    candidatos: list[tuple[float, Archetype, list[dict]]] = []
    for arch in _BY_CATEGORY.get(category, []):
        score, cobertura, evidencia = _score(arch, z)
        if cobertura < MIN_COVERAGE:
            continue
        candidatos.append((score, arch, evidencia))

    resultado: dict = {
        "category": category,
        "label": CATEGORY_LABELS.get(category, category),
        "primary": None,
        "secondary": None,
    }

    if not candidatos:
        resultado["note"] = (
            "Sem features suficientes nesta era para classificar esta categoria."
        )
        return resultado

    candidatos.sort(key=lambda item: item[0], reverse=True)
    melhor_score, melhor, melhor_evid = candidatos[0]

    if melhor_score < MIN_PRIMARY_SCORE:
        resultado["note"] = (
            "Perfil equilibrado nesta categoria: nenhum arquetipo se destaca."
        )
        resultado["ranking"] = [
            {"key": a.key, "label": a.label, "score": round(s, 3)}
            for s, a, _ in candidatos[:3]
        ]
        return resultado

    resultado["primary"] = _entry(melhor, melhor_score, melhor_evid)

    # Secundario: so quando o segundo colocado esta realmente perto. Forcar um
    # sempre transformaria ruido em rotulo.
    if len(candidatos) > 1:
        segundo_score, segundo, segundo_evid = candidatos[1]
        if (
            segundo_score >= MIN_SECONDARY_SCORE
            and (melhor_score - segundo_score) <= SECONDARY_MARGIN
        ):
            resultado["secondary"] = _entry(segundo, segundo_score, segundo_evid)

    return resultado


def classify(z: dict[str, float]) -> dict:
    """
    Perfil completo de arquetipos a partir do vetor de z-scores.

    `z` e o mesmo dicionario que `similarity.PlayerStyle.z` carrega.
    """
    categorias = [classify_category(z, cat) for cat in CATEGORY_ORDER]

    # A "assinatura" e o resumo curto: as categorias em que o jogador mais se
    # destaca, que e como um olheiro apresentaria o jogador em uma linha.
    com_primario = [c for c in categorias if c["primary"]]
    destaques = sorted(
        com_primario, key=lambda c: c["primary"]["score"], reverse=True
    )[:3]

    return {
        "categories": {c["category"]: c for c in categorias},
        "signature": [
            {"category": c["category"], "label": c["primary"]["label"],
             "score": c["primary"]["score"]}
            for c in destaques
        ],
        "summary": " / ".join(c["primary"]["label"] for c in destaques)
                   or "Perfil sem arquetipo dominante",
        "method": (
            "regras deterministicas sobre os z-scores da propria temporada "
            f"({len(ARCHETYPES)} arquetipos em {len(CATEGORY_ORDER)} categorias)"
        ),
    }


# ---------------------------------------------------------------------------
# Comparacao entre dois perfis
# ---------------------------------------------------------------------------
def compare_profiles(perfil_a: dict, perfil_b: dict,
                     nome_a: str = "A", nome_b: str = "B") -> dict:
    """
    Onde dois jogadores jogam igual e onde divergem, em vocabulario de scouting.

    E a peca que faltava para a comparacao: o score 0-100 diz o quanto sao
    parecidos, isto diz EM QUE sao parecidos.
    """
    iguais: list[dict] = []
    diferentes: list[dict] = []

    for categoria in CATEGORY_ORDER:
        ca = (perfil_a.get("categories") or {}).get(categoria) or {}
        cb = (perfil_b.get("categories") or {}).get(categoria) or {}
        pa, pb = ca.get("primary"), cb.get("primary")
        if not pa or not pb:
            continue

        rotulo = CATEGORY_LABELS.get(categoria, categoria)
        if pa["key"] == pb["key"]:
            iguais.append({
                "category": categoria,
                "category_label": rotulo,
                "archetype": pa["label"],
                "score_a": pa["score"],
                "score_b": pb["score"],
            })
        else:
            diferentes.append({
                "category": categoria,
                "category_label": rotulo,
                "a": pa["label"],
                "b": pb["label"],
                "gap": round(abs(pa["score"] - pb["score"]), 3),
            })

    total = len(iguais) + len(diferentes)
    if not total:
        leitura = "Nao foi possivel classificar arquetipos comparaveis."
    elif not diferentes:
        leitura = f"{nome_a} e {nome_b} tem o mesmo arquetipo em todas as categorias comparaveis."
    elif not iguais:
        leitura = (
            f"{nome_a} e {nome_b} nao coincidem em nenhuma categoria: "
            "funcoes diferentes em quadra."
        )
    else:
        leitura = (
            f"{nome_a} e {nome_b} coincidem em "
            + ", ".join(i["category_label"].lower() for i in iguais)
            + "; divergem em "
            + ", ".join(d["category_label"].lower() for d in diferentes)
            + "."
        )

    return {
        "shared": iguais,
        "divergent": diferentes,
        "shared_count": len(iguais),
        "categories_compared": total,
        "reading": leitura,
    }
