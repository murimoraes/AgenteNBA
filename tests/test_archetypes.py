"""
Testes dos arquetipos de estilo.

Dois grupos de teste, com propositos diferentes:

  INVARIANTES   propriedades que precisam valer para qualquer entrada (escala do
                score, catalogo coerente, secundario nunca acima do primario).
  RECONHECIMENTO perfis sinteticos de z-score construidos para representar um
                estilo conhecido, verificando se o rotulo certo sai. E o que
                impede os pesos de virarem numeros arbitrarios: mexer neles e
                quebrar o reconhecimento aparece aqui.

Nenhum teste chama rede: o classificador trabalha sobre um dicionario de
z-scores, entao a suite roda offline.
"""

from __future__ import annotations

import pytest

import archetypes


# ---------------------------------------------------------------------------
# Perfis sinteticos
# ---------------------------------------------------------------------------
def _perfil(**ajustes: float) -> dict[str, float]:
    """Jogador exatamente na media da liga, com os desvios que o teste pedir."""
    base = {feature: 0.0 for feature in (
        "SHOT_RA", "SHOT_PAINT", "SHOT_MID", "SHOT_C3", "SHOT_AB3", "FTA_RATE",
        "DRIVES_36", "PULLUP_SHARE", "CATCH_SHARE", "POST_36",
        "AST_PCT", "AST_TO", "AST_PER_USG", "PASS_36",
        "OREB_PCT", "DREB_PCT",
        "STL_36", "BLK_36", "RIM_DFGA_36", "RIM_DFG_PCT", "DEFLECT_36", "CONTEST_36",
        "HEIGHT_IN", "WEIGHT_LB", "USG_PCT", "PTS_36", "FGA_36", "TS_PCT",
    )}
    base.update(ajustes)
    return base


ARMADOR_ARREMESSADOR = _perfil(
    SHOT_AB3=2.4, SHOT_C3=0.3, SHOT_RA=-1.2, SHOT_PAINT=-0.9, SHOT_MID=-0.7,
    PULLUP_SHARE=2.0, CATCH_SHARE=-0.3, DRIVES_36=0.4, POST_36=-0.8,
    AST_PCT=1.3, AST_TO=0.6, AST_PER_USG=0.5, PASS_36=0.9,
    OREB_PCT=-0.9, DREB_PCT=-0.6, STL_36=0.7, BLK_36=-0.8,
    RIM_DFGA_36=-1.0, DEFLECT_36=0.5, CONTEST_36=-0.9,
    HEIGHT_IN=-1.3, WEIGHT_LB=-1.1, USG_PCT=1.8, PTS_36=1.9, FGA_36=1.8, TS_PCT=1.5,
)

PIVO_PROTETOR = _perfil(
    SHOT_AB3=-1.4, SHOT_C3=-1.0, SHOT_RA=2.5, SHOT_PAINT=0.5, SHOT_MID=-1.2,
    FTA_RATE=1.1, PULLUP_SHARE=-1.5, CATCH_SHARE=0.6, DRIVES_36=-1.2, POST_36=0.7,
    AST_PCT=-1.1, AST_PER_USG=-0.6, PASS_36=-0.9,
    OREB_PCT=2.2, DREB_PCT=1.9, STL_36=-0.6, BLK_36=2.3,
    RIM_DFGA_36=2.1, RIM_DFG_PCT=-1.6, CONTEST_36=1.8,
    HEIGHT_IN=2.0, WEIGHT_LB=1.7, USG_PCT=-0.7, TS_PCT=1.8,
)

ESPECIALISTA_3AND_D = _perfil(
    SHOT_AB3=1.6, SHOT_C3=2.2, SHOT_MID=-1.0, SHOT_RA=-0.8,
    CATCH_SHARE=2.1, PULLUP_SHARE=-1.4, DRIVES_36=-1.0,
    AST_PCT=-0.9, USG_PCT=-1.5, PTS_36=-0.4, FGA_36=-0.6,
    STL_36=0.8, DEFLECT_36=1.1, CONTEST_36=0.7,
    HEIGHT_IN=0.4, WEIGHT_LB=0.2, TS_PCT=0.9,
)

PIVO_PASSADOR = _perfil(
    SHOT_RA=0.6, SHOT_PAINT=0.9, POST_36=1.8,
    AST_PCT=2.1, AST_PER_USG=2.0, PASS_36=1.7, AST_TO=1.2,
    OREB_PCT=1.1, DREB_PCT=1.6,
    HEIGHT_IN=1.8, WEIGHT_LB=1.6, USG_PCT=1.2, TS_PCT=1.4,
)


# ---------------------------------------------------------------------------
# Catalogo
# ---------------------------------------------------------------------------
def test_chaves_sao_unicas():
    chaves = [a.key for a in archetypes.ARCHETYPES]
    assert len(chaves) == len(set(chaves))


def test_rotulos_sao_unicos():
    rotulos = [a.label for a in archetypes.ARCHETYPES]
    assert len(rotulos) == len(set(rotulos))


def test_toda_categoria_declarada_tem_arquetipos():
    for categoria in archetypes.CATEGORY_ORDER:
        presentes = [a for a in archetypes.ARCHETYPES if a.category == categoria]
        assert len(presentes) >= 5, f"{categoria} tem so {len(presentes)}"


def test_nenhum_arquetipo_fora_das_categorias_declaradas():
    for arch in archetypes.ARCHETYPES:
        assert arch.category in archetypes.CATEGORY_LABELS


def test_todo_arquetipo_tem_descricao_e_peso():
    for arch in archetypes.ARCHETYPES:
        assert arch.description.strip()
        assert arch.total_weight() > 0


def test_sinais_usam_apenas_features_que_existem():
    """
    Um sinal com chave errada seria invisivel: o arquetipo simplesmente nunca
    pontuaria por ela. O teste amarra o catalogo ao vetor real do similarity.
    """
    import similarity

    validas = set(similarity.BY_KEY)
    for arch in archetypes.ARCHETYPES:
        for chave in list(arch.signals) + list(arch.bands):
            assert chave in validas, f"{arch.key} usa feature inexistente: {chave}"


# ---------------------------------------------------------------------------
# Invariantes do score
# ---------------------------------------------------------------------------
def test_score_fica_na_faixa_menos_um_a_um():
    for perfil in (ARMADOR_ARREMESSADOR, PIVO_PROTETOR, ESPECIALISTA_3AND_D, _perfil()):
        for arch in archetypes.ARCHETYPES:
            score, _cobertura, _ev = archetypes._score(arch, perfil)
            assert -1.0 <= score <= 1.0, f"{arch.key} saiu da escala: {score}"


def test_jogador_medio_nao_recebe_rotulo_forcado():
    """z = 0 em tudo e a definicao de 'sem estilo marcante'."""
    perfil = archetypes.classify(_perfil())
    rotulados = [
        c for c in perfil["categories"].values()
        if c["primary"] and c["category"] not in ("physique", "role")
    ]
    assert not rotulados, f"rotulou um jogador medio: {[c['primary'] for c in rotulados]}"


def test_perfil_medio_cai_no_arquetipo_de_meio_no_fisico():
    """As bands existem justamente para isso: o meio tambem e um perfil."""
    perfil = archetypes.classify(_perfil())
    fisico = perfil["categories"]["physique"]
    assert fisico["primary"]["key"] == "ala_padrao"


def test_secundario_nunca_supera_o_primario():
    for perfil_z in (ARMADOR_ARREMESSADOR, PIVO_PROTETOR, PIVO_PASSADOR):
        perfil = archetypes.classify(perfil_z)
        for categoria in perfil["categories"].values():
            if categoria["primary"] and categoria["secondary"]:
                assert categoria["secondary"]["score"] <= categoria["primary"]["score"]


def test_secundario_so_aparece_quando_esta_perto():
    for perfil_z in (ARMADOR_ARREMESSADOR, PIVO_PROTETOR, ESPECIALISTA_3AND_D):
        perfil = archetypes.classify(perfil_z)
        for categoria in perfil["categories"].values():
            if categoria["primary"] and categoria["secondary"]:
                distancia = categoria["primary"]["score"] - categoria["secondary"]["score"]
                assert distancia <= archetypes.SECONDARY_MARGIN


def test_primario_respeita_o_piso():
    perfil = archetypes.classify(ARMADOR_ARREMESSADOR)
    for categoria in perfil["categories"].values():
        if categoria["primary"]:
            assert categoria["primary"]["score"] >= archetypes.MIN_PRIMARY_SCORE


def test_categoria_sem_destaque_explica_em_vez_de_chutar():
    perfil = archetypes.classify(_perfil())
    rebote = perfil["categories"]["rebounding"]
    assert rebote["primary"] is None
    assert "equilibrado" in rebote["note"]


def test_evidencia_vem_ordenada_e_limitada():
    perfil = archetypes.classify(PIVO_PROTETOR)
    entrada = perfil["categories"]["defense"]["primary"]
    evidencia = entrada["evidence"]

    assert 0 < len(evidencia) <= 3
    contribuicoes = [e["encaixe"] * e["peso"] for e in evidencia]
    assert contribuicoes == sorted(contribuicoes, reverse=True)


def test_todas_as_categorias_aparecem_no_resultado():
    perfil = archetypes.classify(ARMADOR_ARREMESSADOR)
    assert set(perfil["categories"]) == set(archetypes.CATEGORY_ORDER)


# ---------------------------------------------------------------------------
# Reconhecimento de estilo
# ---------------------------------------------------------------------------
def test_armador_arremessador_e_reconhecido():
    perfil = archetypes.classify(ARMADOR_ARREMESSADOR)
    cats = perfil["categories"]

    assert cats["shot_profile"]["primary"]["key"] == "arremessador_elite"
    assert cats["creation"]["primary"]["key"] in ("criador_pullup", "pick_and_roll")
    assert cats["role"]["primary"]["key"] == "protagonista"
    assert cats["physique"]["primary"]["key"] == "armador_compacto"


def test_pivo_protetor_e_reconhecido():
    cats = archetypes.classify(PIVO_PROTETOR)["categories"]

    assert cats["shot_profile"]["primary"]["key"] == "muralha_garrafao"
    assert cats["defense"]["primary"]["key"] == "protetor_aro"
    assert cats["rebounding"]["primary"]["key"] in (
        "reboteiro_ofensivo", "dominante_dois_lados", "reboteiro_defensivo"
    )
    assert cats["physique"]["primary"]["key"] == "pivo_classico"


def test_especialista_de_funcao_e_reconhecido():
    cats = archetypes.classify(ESPECIALISTA_3AND_D)["categories"]

    assert cats["role"]["primary"]["key"] == "especialista_funcao"
    assert cats["shot_profile"]["primary"]["key"] in ("tres_do_canto", "arremessador_elite")
    assert cats["creation"]["primary"]["key"] == "finalizador_sem_bola"


def test_pivo_passador_e_reconhecido():
    cats = archetypes.classify(PIVO_PASSADOR)["categories"]

    assert cats["playmaking"]["primary"]["key"] == "pivo_passador"
    assert cats["creation"]["primary"]["key"] in ("pivo_criador", "jogo_de_costas")


def test_arquetipos_opostos_nao_se_confundem():
    armador = archetypes.classify(ARMADOR_ARREMESSADOR)["categories"]
    pivo = archetypes.classify(PIVO_PROTETOR)["categories"]

    for categoria in ("shot_profile", "physique"):
        assert armador[categoria]["primary"]["key"] != pivo[categoria]["primary"]["key"]


def test_assinatura_traz_as_categorias_mais_marcantes():
    perfil = archetypes.classify(PIVO_PROTETOR)

    assert 1 <= len(perfil["signature"]) <= 3
    scores = [item["score"] for item in perfil["signature"]]
    assert scores == sorted(scores, reverse=True)
    assert perfil["summary"]


# ---------------------------------------------------------------------------
# Cobertura por era
# ---------------------------------------------------------------------------
_SO_CORE = ("DRIVES_36", "PULLUP_SHARE", "CATCH_SHARE", "POST_36", "PASS_36",
            "RIM_DFGA_36", "RIM_DFG_PCT", "DEFLECT_36", "CONTEST_36")


def _sem_tracking(perfil: dict[str, float]) -> dict[str, float]:
    """O mesmo jogador visto por uma temporada anterior a 2013-14."""
    return {k: v for k, v in perfil.items() if k not in _SO_CORE}


def test_arquetipo_dependente_de_tracking_nao_concorre_em_era_antiga():
    """
    Em 1996-97 nao existe pull-up nem drives. "Criador Pull-Up" sem a feature de
    pull-up nao e uma classificacao fraca -- e uma classificacao sem sentido.
    O corte de cobertura tira o arquetipo da disputa em vez de pontua-lo com
    meio vetor e fingir confianca.
    """
    era_antiga = _sem_tracking(ARMADOR_ARREMESSADOR)

    for chave in ("criador_pullup", "motorista_drives", "incomodador_passe"):
        _score, cobertura, _ev = archetypes._score(archetypes.BY_KEY[chave], era_antiga)
        assert cobertura < archetypes.MIN_COVERAGE, chave


def test_era_antiga_preserva_o_que_nao_depende_de_tracking():
    cats = archetypes.classify(_sem_tracking(ARMADOR_ARREMESSADOR))["categories"]

    assert cats["shot_profile"]["primary"]["key"] == "arremessador_elite"
    assert cats["physique"]["primary"]["key"] == "armador_compacto"
    assert cats["role"]["primary"]["key"] == "protagonista"


def test_era_antiga_nao_inventa_rotulo_de_criacao_para_armador():
    """
    Sobram poucos arquetipos de criacao sem tracking, e nenhum descreve bem este
    jogador. Admitir isso e melhor do que entregar o menos ruim.
    """
    criacao = archetypes.classify(_sem_tracking(ARMADOR_ARREMESSADOR))["categories"]["creation"]

    assert criacao["primary"] is None
    assert criacao["note"]


def test_categoria_sem_nenhum_arquetipo_viavel_explica_a_era():
    """Vetor so com fisico: defesa nao tem como ser classificada."""
    cats = archetypes.classify({"HEIGHT_IN": 1.0, "WEIGHT_LB": 1.0})["categories"]

    assert cats["defense"]["primary"] is None
    assert "era" in cats["defense"]["note"]


def test_vetor_vazio_nao_quebra():
    perfil = archetypes.classify({})
    assert perfil["summary"] == "Perfil sem arquetipo dominante"
    assert all(c["primary"] is None for c in perfil["categories"].values())


# ---------------------------------------------------------------------------
# Comparacao de perfis
# ---------------------------------------------------------------------------
def test_comparacao_entre_opostos_nao_encontra_nada_em_comum():
    resultado = archetypes.compare_profiles(
        archetypes.classify(ARMADOR_ARREMESSADOR),
        archetypes.classify(PIVO_PROTETOR),
        "Armador", "Pivo",
    )
    assert resultado["shared_count"] == 0
    assert resultado["divergent"]
    assert "nao coincidem" in resultado["reading"]


def test_comparacao_de_um_jogador_com_ele_mesmo_e_identica():
    perfil = archetypes.classify(PIVO_PROTETOR)
    resultado = archetypes.compare_profiles(perfil, perfil, "X", "X")

    assert resultado["divergent"] == []
    assert resultado["shared_count"] == resultado["categories_compared"]
    assert "mesmo arquetipo em todas" in resultado["reading"]


def test_comparacao_parcial_lista_os_dois_lados():
    parecido = dict(PIVO_PROTETOR)
    parecido.update({"AST_PCT": 2.0, "AST_PER_USG": 1.9, "PASS_36": 1.6})

    resultado = archetypes.compare_profiles(
        archetypes.classify(PIVO_PROTETOR),
        archetypes.classify(parecido),
        "Gobert-like", "Jokic-like",
    )
    assert resultado["shared_count"] >= 1
    assert resultado["categories_compared"] >= resultado["shared_count"]


def test_comparacao_sem_perfis_nao_quebra():
    resultado = archetypes.compare_profiles({}, {}, "A", "B")
    assert resultado["shared_count"] == 0
    assert resultado["categories_compared"] == 0
    assert resultado["reading"]
