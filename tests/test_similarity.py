"""
Testes do motor de similaridade.

O calculo depende de uma populacao da liga inteira (chamada de rede), entao os
testes cobrem as propriedades que NAO dependem dela: invariantes da escala, dos
pesos, das features e da traducao do score em veredito. A estabilidade empirica
do ranking fica para a Fase 5 do roadmap, que precisa de dataset anotado.
"""

from __future__ import annotations

import numpy as np
import pytest

import similarity


# ---------------------------------------------------------------------------
# Catalogo de features
# ---------------------------------------------------------------------------
def test_features_tem_chave_unica():
    keys = [f.key for f in similarity.FEATURES]
    assert len(keys) == len(set(keys))


def test_indice_por_chave_cobre_todas_as_features():
    assert set(similarity.BY_KEY) == {f.key for f in similarity.FEATURES}


def test_todo_grupo_de_feature_tem_peso_definido():
    grupos = {f.group for f in similarity.FEATURES}
    faltando = grupos - set(similarity.GROUP_WEIGHTS)
    assert not faltando, f"grupos sem peso: {faltando}"


def test_toda_feature_declara_camada_de_era_conhecida():
    assert {f.tier for f in similarity.FEATURES} <= {"core", "tracking", "hustle"}


def test_peso_de_producao_e_menor_que_o_de_perfil_de_arremesso():
    """A tese do projeto: estilo e forma, nao volume. Se inverter, quebrou."""
    assert similarity.GROUP_WEIGHTS["volume"] < similarity.GROUP_WEIGHTS["shot_profile"]
    assert similarity.GROUP_WEIGHTS["volume"] < 0.5


def test_pesos_sao_positivos():
    assert all(w > 0 for w in similarity.GROUP_WEIGHTS.values())


def _uma_chave_de(group: str) -> str:
    return next(f.key for f in similarity.FEATURES if f.group == group)


def test_pesos_sao_normalizados_para_media_um():
    """
    A distancia nao pode depender de QUANTAS features entraram, senao comparar
    eras (que usam menos features) daria sempre "mais parecido".
    """
    for corte in (5, 12, len(similarity.FEATURES)):
        keys = [f.key for f in similarity.FEATURES[:corte]]
        pesos = similarity._weights(keys)
        assert len(pesos) == len(keys)
        assert float(pesos.mean()) == pytest.approx(1.0)


def test_grupo_mais_importante_pesa_mais_que_o_menos_importante():
    keys = [_uma_chave_de("shot_profile"), _uma_chave_de("volume")]
    shot, volume = similarity._weights(keys)
    assert shot > volume


def test_peso_do_grupo_e_dividido_entre_suas_features():
    """Um grupo com duas features nao pode valer o dobro de um com uma."""
    grupo = next(
        g for g in similarity.GROUP_WEIGHTS
        if sum(1 for f in similarity.FEATURES if f.group == g) >= 2
    )
    duas = [f.key for f in similarity.FEATURES if f.group == grupo][:2]
    outra = _uma_chave_de(next(g for g in similarity.GROUP_WEIGHTS if g != grupo))

    pesos = similarity._weights(duas + [outra])
    assert pesos[0] == pytest.approx(pesos[1])


# ---------------------------------------------------------------------------
# Escala e veredito
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("score", [0, 0.6, 25, 50, 51.6, 77, 93.5, 99.4, 100])
def test_veredito_existe_para_toda_a_escala(score):
    assert isinstance(similarity.verdict_for(score), str)
    assert similarity.verdict_for(score)


def test_veredito_e_monotonico():
    """Score maior nunca pode significar 'menos parecido'."""
    faixas = [similarity.verdict_for(s) for s in range(0, 101, 5)]
    ordem = list(dict.fromkeys(faixas))
    # A ordem de aparicao tem de ser a ordem inversa da tabela VERDICTS.
    esperado = [v for _, v in sorted(similarity.VERDICTS, key=lambda x: x[0])]
    assert ordem == [v for v in esperado if v in ordem]


def test_extremos_da_escala_nao_quebram():
    assert similarity.verdict_for(0.0)
    assert similarity.verdict_for(100.0)


def test_resemblance_fica_na_faixa_0_100(monkeypatch):
    """A escala e um percentual de pares da liga: nao pode sair de 0-100."""
    ref = np.linspace(0.0, 20.0, 500)
    monkeypatch.setattr(similarity, "_pair_reference", lambda season, keys: ref)
    keys = [f.key for f in similarity.FEATURES[:6]]

    for dist in (0.0, 0.5, 4.2, 10.0, 50.0):
        score = similarity._resemblance(dist, keys, "2024-25")
        assert 0.0 <= score <= 100.0


def test_distancia_menor_significa_semelhanca_maior(monkeypatch):
    ref = np.linspace(0.0, 20.0, 500)
    monkeypatch.setattr(similarity, "_pair_reference", lambda season, keys: ref)
    keys = [f.key for f in similarity.FEATURES[:6]]

    perto = similarity._resemblance(1.0, keys, "2024-25")
    longe = similarity._resemblance(15.0, keys, "2024-25")
    assert perto > longe


def test_resemblance_e_simetrico_por_construcao(monkeypatch):
    """
    A distancia euclidiana e simetrica, entao A x B e B x A dao o mesmo score.
    O teste trava a propriedade no nivel em que ela e garantida sem rede.
    """
    ref = np.linspace(0.0, 20.0, 300)
    monkeypatch.setattr(similarity, "_pair_reference", lambda season, keys: ref)
    keys = [f.key for f in similarity.FEATURES[:6]]

    va = np.array([1.0, -0.5, 0.2, 2.0, -1.0, 0.3])
    vb = np.array([0.4, 0.1, -0.7, 1.2, 0.5, -0.2])
    d_ab = float(np.linalg.norm(va - vb))
    d_ba = float(np.linalg.norm(vb - va))

    assert d_ab == pytest.approx(d_ba)
    assert similarity._resemblance(d_ab, keys, "2024-25") == pytest.approx(
        similarity._resemblance(d_ba, keys, "2024-25")
    )


# ---------------------------------------------------------------------------
# Amostra e limiares
# ---------------------------------------------------------------------------
def test_limiares_de_amostra_sao_coerentes():
    assert similarity.MIN_GP > 0
    assert similarity.MIN_MPG > 0
    assert similarity.SMALL_SAMPLE_GP > similarity.MIN_GP


def test_conversao_numerica_tolera_lixo():
    assert similarity._as_float(None) is None
    assert similarity._as_float("") is None
    assert similarity._as_float("abc") is None
    assert similarity._as_float(3) == 3.0
    assert similarity._as_float("2.5") == 2.5
