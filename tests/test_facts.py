"""
Testes do fact checker numerico.

Os dois casos que abrem o arquivo sao reproducoes exatas de falhas observadas
em teste manual do agente rodando (relatorio de 2026-09-21): o salario inventado
do LeBron e a resposta sem tool nenhuma. Se o checker parar de peg -los, a
regressao aparece aqui antes de chegar no usuario.
"""

from __future__ import annotations

from validation import facts


# ---------------------------------------------------------------------------
# Regressao: as falhas reais que motivaram o modulo
# ---------------------------------------------------------------------------
def test_salario_inventado_e_barrado(season_stats_payload):
    """O caso #9 do relatorio: '$44.5 milhoes' sem nenhuma tool de salario."""
    answer = (
        "Na temporada 2024-25, LeBron James tem um salario de $44.5 milhoes. "
        "Ele teve media de 29.6 pontos por jogo."
    )
    report = facts.check(answer, [season_stats_payload], question="Qual o salario do LeBron?")

    assert not report.ok
    metricas = {flag.metric for flag in report.out_of_contract}
    assert "salario/contrato" in metricas
    assert "valores monetarios" in metricas


def test_resposta_sem_tool_deixa_todo_numero_sem_lastro():
    """Zero tools chamadas: qualquer numero e necessariamente de memoria."""
    answer = "LeBron esta em sua 20a temporada e tem media de 25.4 pontos."
    report = facts.check(answer, [], question="Quem e o melhor jogador da liga?")

    assert not report.ok
    assert {claim.raw for claim in report.unverified} == {"20", "25.4"}
    assert report.hallucination_rate == 1.0


# ---------------------------------------------------------------------------
# Caminho feliz: nao pode reprovar resposta correta
# ---------------------------------------------------------------------------
def test_numeros_vindos_da_tool_passam(season_stats_payload):
    answer = (
        "Na temporada 2024-25, Nikola Jokic teve media de 29.6 pontos, 12.7 rebotes "
        "e 10.2 assistencias em 70 jogos, com 36.7 minutos por partida."
    )
    report = facts.check(answer, [season_stats_payload])

    assert report.ok, [str(c) for c in report.unverified]
    assert report.verified_count == len(report.claims)


def test_percentual_citado_como_fracao_ou_como_porcentagem(season_stats_payload):
    """A tool guarda 0.576; o texto escreve 57.6%. Sao o mesmo dado."""
    report = facts.check("Ele acertou 57.6% dos arremessos e 41.7% dos tres.",
                         [season_stats_payload])
    assert report.ok


def test_arredondamento_dentro_da_precisao_escrita(season_stats_payload):
    """29.6 na tool; escrever 'quase 30 pontos' e arredondamento, nao invencao."""
    report = facts.check("Jokic ficou em 30 pontos por jogo.", [season_stats_payload])
    assert report.ok


def test_aproveitamento_derivado_de_dois_campos_da_tool(season_stats_payload):
    """10.5 convertidos / 18.2 tentados = 57.7%: aritmetica sobre dado real."""
    report = facts.check("Converteu 10.5 de 18.2 arremessos, 57.7% de aproveitamento.",
                         [season_stats_payload])
    assert report.ok


def test_fracao_em_string_libera_os_componentes(recent_games_payload):
    """'14/23' na tool -> 14, 23 e 60.9% sao todos rastreaveis."""
    report = facts.check("Acertou 14 de 23 arremessos (60.9%).", [recent_games_payload])
    assert report.ok


def test_numero_da_pergunta_do_usuario_nao_e_alucinacao(season_stats_payload):
    report = facts.check(
        "Nos ultimos 7 jogos ele manteve 29.6 pontos.",
        [season_stats_payload],
        question="Como foi nos ultimos 7 jogos?",
    )
    assert report.ok


def test_marcador_de_lista_nao_vira_claim(season_stats_payload):
    answer = "Destaques:\n1. Pontuacao alta\n2. Boa visao de jogo\n3. Rebote solido"
    report = facts.check(answer, [season_stats_payload])
    assert report.claims == []
    assert report.ok


# ---------------------------------------------------------------------------
# Deteccao
# ---------------------------------------------------------------------------
def test_numero_fora_da_evidencia_e_pego(season_stats_payload):
    report = facts.check("Jokic teve media de 33.1 pontos por jogo.", [season_stats_payload])
    assert [claim.raw for claim in report.unverified] == ["33.1"]
    assert report.hallucination_rate == 1.0


def test_derivacao_legitima_nao_e_tratada_como_invencao(season_stats_payload):
    """
    1.9 convertidos / 4.6 tentados = 41.3%. O numero nao esta literalmente no
    payload, mas os dois insumos estao -- calcular nao e inventar.

    Esta e a fronteira do checker e ela e deliberada: aceitar derivacao evita
    reprovar resposta correta, ao custo de ampliar um pouco o conjunto aceito.
    """
    report = facts.check("Acertou 41.3% das bolas de tres.", [season_stats_payload])
    assert report.ok


def test_temporada_nao_consultada_e_pega(season_stats_payload):
    report = facts.check(
        "Em 2019-20 ele jogou melhor, com 29.6 pontos.", [season_stats_payload]
    )
    assert report.unverified_seasons == ["2019-20"]
    assert not report.ok


def test_temporada_consultada_passa(season_stats_payload):
    report = facts.check("Na temporada 2024-25 ele fez 29.6 pontos.", [season_stats_payload])
    assert report.unverified_seasons == []


def test_premio_individual_esta_fora_do_contrato(season_stats_payload):
    report = facts.check("Jokic e o atual MVP da liga.", [season_stats_payload])
    assert [f.metric for f in report.out_of_contract] == ["premios individuais"]


def test_recusar_o_dado_nao_conta_como_violacao(season_stats_payload):
    """
    Respostas reais capturadas na avaliacao. Citar a metrica para dizer que ela
    nao existe e o comportamento desejado -- punir isso ensinaria o agente a
    esconder a limitacao em vez de declara-la.
    """
    corretas = [
        "Desculpe, mas este sistema nao tem dados sobre salarios, contratos ou "
        "valores de mercado de jogadores da NBA.",
        "Este sistema nao tem dados sobre titulos da NBA.",
        "Este sistema nao tem dados sobre premios, como MVP, entao nao consigo "
        "confirmar se Nikola Jokic ganhou o MVP na temporada 2024-25.",
        "Este sistema nao tem dados sobre a classificacao dos times.",
        "Nao possuo dados sobre quem e o melhor jogador, como premios ou reconhecimentos.",
    ]
    for resposta in corretas:
        assert facts.declines_to_answer(resposta), resposta
        assert facts.find_out_of_contract(resposta) == [], resposta


def test_recusa_com_acento_e_reconhecida():
    assert facts.declines_to_answer("Não tenho esse dado disponível.")
    assert facts.declines_to_answer("Nenhuma ferramenta fornece essa informação.")
    assert not facts.declines_to_answer("O salario dele e de 44.5 milhoes.")


def test_afirmacao_e_recusa_na_mesma_resposta(season_stats_payload):
    """Julgamento e por frase: a recusa nao absolve a afirmacao seguinte."""
    answer = "Nao tenho dados de salario. De todo modo, o Curry tem 4 titulos da NBA."
    flags = facts.find_out_of_contract(answer)

    metricas = {f.metric for f in flags}
    assert "titulos/playoffs" in metricas       # a afirmacao foi pega
    assert "salario/contrato" not in metricas   # a recusa nao foi punida


def test_contrato_pode_ser_desligado(season_stats_payload):
    report = facts.check(
        "Jokic e o atual MVP.", [season_stats_payload], enforce_contract=False
    )
    assert report.out_of_contract == []


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def test_decimal_pt_br_e_en_sao_equivalentes(season_stats_payload):
    assert facts.check("Media de 29,6 pontos.", [season_stats_payload]).ok
    assert facts.check("Media de 29.6 pontos.", [season_stats_payload]).ok


def test_separador_de_milhar(season_stats_payload):
    """2071 pontos no total, escrito como 2.071."""
    assert facts.check("Somou 2.071 pontos na temporada.", [season_stats_payload]).ok


def test_evidencia_percorre_estruturas_aninhadas(season_stats_payload):
    evidence = facts.build_evidence([season_stats_payload])
    assert evidence.supports(29.6, 1)      # per_game.points
    assert evidence.supports(2566, 0)      # season_totals.minutes
    assert evidence.supports(57.6, 1)      # shooting.fg_pct como percentual
    assert evidence.supports_season("2024-25")
    assert not evidence.supports(44.5, 1)


def test_relatorio_serializa_para_metricas(season_stats_payload):
    report = facts.check("Media de 33.1 pontos.", [season_stats_payload])
    data = report.as_dict()
    assert data["ok"] is False
    assert data["unverified"] == ["33.1"]
    assert 0.0 <= data["hallucination_rate"] <= 1.0


def test_prompt_de_correcao_lista_o_que_reprovou(season_stats_payload):
    report = facts.check(
        "Ganhou 44.5 milhoes de salario e fez 33.1 pontos.", [season_stats_payload]
    )
    prompt = report.correction_prompt()
    assert "33.1" in prompt
    assert "salario" in prompt.lower()
    assert "nunca substitua por estimativa" in prompt


def test_resposta_vazia_nao_quebra():
    report = facts.check("", [])
    assert report.ok
    assert report.claims == []
    assert report.hallucination_rate == 0.0
