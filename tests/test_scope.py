"""
Testes do guardrail de escopo.

O criterio de projeto e assimetrico e os testes refletem isso: recusar pergunta
valida (falso negativo) e pior do que deixar passar uma duvidosa, porque o
usuario perde a resposta e nao entende por que. Por isso ha mais casos
cobrindo "deve passar" do que "deve recusar".
"""

from __future__ import annotations

import pytest

from validation import scope


@pytest.mark.parametrize(
    "pergunta",
    [
        "Como foi a temporada do Victor Wembanyama?",
        "Quem joga num estilo parecido com o Jokic?",
        "Compare o estilo do Anthony Edwards com o do Donovan Mitchell",
        "Como esta a forma recente do Giannis nos ultimos 7 jogos?",
        "Quantos pontos por jogo o Jokic fez em 2024-25?",
        "Quem e o melhor jogador da liga?",
        "Qual o aproveitamento de tres do Curry?",
        "Fale sobre o desempenho defensivo dos Celtics",
        "quem sao os melhores armadores hoje",
        "me explica o que e true shooting",
        # Pergunta ambigua SEM historico: falta o antecedente do pronome, mas o
        # assunto e basquete. O certo e o agente pedir de quem se trata, nao
        # tratar como fora de escopo (falha real pega na avaliacao).
        "Como ele esta jogando?",
        "Ele jogou bem?",
        "como ela vem atuando",
    ],
)
def test_pergunta_de_nba_passa(pergunta):
    verdict = scope.classify(pergunta)
    assert verdict.in_scope, f"recusou indevidamente ({verdict.reason})"


@pytest.mark.parametrize(
    "pergunta",
    [
        "Qual a capital da Franca e qual o melhor restaurante de la?",
        "Me da uma receita de bolo de cenoura",
        "Qual a previsao do tempo para amanha?",
        "Escreve um codigo Python que ordena uma lista",
        "Quem ganhou a Copa do Mundo de futebol?",
        "O que voce acha do meu signo?",
    ],
)
def test_pergunta_fora_do_dominio_e_recusada(pergunta):
    verdict = scope.classify(pergunta)
    assert not verdict.in_scope
    assert verdict.reason


def test_caso_real_do_relatorio_de_testes():
    """Teste #4 do relatorio: respondida normalmente, com zero tools."""
    verdict = scope.classify("Qual a capital da Franca e qual o melhor restaurante de la?")
    assert not verdict.in_scope
    assert "NBA" in verdict.refusal_message()


def test_followup_curto_herda_escopo_da_conversa():
    """'E ele?' sozinho nao tem sinal de basquete -- mas e continuacao valida."""
    assert not scope.classify("E ele?").in_scope
    assert scope.classify("E ele?", has_history=True).in_scope


def test_followup_com_pronome_longo_ainda_passa_com_historico():
    pergunta = "e como foi o desempenho dele no recorte anterior que voce mencionou agora"
    assert scope.classify(pergunta, has_history=True).in_scope


def test_nome_de_jogador_sozinho_e_suficiente():
    verdict = scope.classify("Wembanyama")
    assert verdict.in_scope
    assert "jogador" in verdict.reason


def test_temporada_sozinha_e_sinal_de_dominio():
    assert scope.classify("e em 2019-20?").in_scope


def test_pergunta_vazia_e_recusada():
    assert not scope.classify("").in_scope
    assert not scope.classify("   ").in_scope


def test_mensagem_de_recusa_explica_e_reorienta():
    msg = scope.classify("Me da uma receita de bolo").refusal_message()
    assert "NBA" in msg
    assert "Wembanyama" in msg  # sugere um caminho valido
