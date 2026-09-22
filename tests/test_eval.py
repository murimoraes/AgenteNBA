"""
Testes da propria suite de avaliacao.

Avaliacao que nao e testada nao serve como evidencia: se o evaluator aprovar
caso errado, todas as metricas do projeto passam a mentir. Aqui os turnos sao
falsos, entao nada disso custa API.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from eval import evaluator, metrics
from validation import facts, temporal


# ---------------------------------------------------------------------------
# Turno falso com a mesma superficie de agent.AgentTurn
# ---------------------------------------------------------------------------
@dataclass
class FakeRecord:
    name: str
    result: dict = field(default_factory=dict)


@dataclass
class FakeTurn:
    answer: str = ""
    tool_calls: list = field(default_factory=list)
    fact_check: facts.FactCheckReport | None = None
    temporal_flags: list = field(default_factory=list)
    refused_scope: bool = False
    error: str | None = None
    latency_s: float = 1.0
    usage: dict = field(default_factory=lambda: {"calls": 2})

    def metrics(self) -> dict:
        report = self.fact_check
        return {
            "latency_s": self.latency_s,
            "api_calls": self.usage.get("calls", 0),
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "cost_usd": 0.00035,
            "tool_calls": [r.name for r in self.tool_calls],
            "corrections": 0,
            "contract_issues": [],
            "numeric_claims": len(report.claims) if report else 0,
            "unverified_claims": len(report.unverified) if report else 0,
            "out_of_contract": [f.metric for f in report.out_of_contract] if report else [],
            "error": self.error,
        }


def _ok_report(answer: str, payload: dict) -> facts.FactCheckReport:
    return facts.check(answer, [payload])


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------
def test_dataset_carrega_e_e_valido():
    data = evaluator.load_dataset()
    assert evaluator.validate_dataset(data) == []


def test_dataset_cobre_os_casos_exigidos_pela_auditoria():
    """A auditoria lista 10 tipos de caso que precisam existir."""
    data = evaluator.load_dataset()
    categorias = {c["category"] for c in data["cases"]}
    exigidas = {
        "stats", "recent_form", "comparison", "similarity", "cross_era",
        "error_handling", "ambiguous", "out_of_contract", "multi_tool", "out_of_scope",
    }
    assert exigidas <= categorias


def test_dataset_tem_tamanho_minimo_do_roadmap():
    """Fase 1 pede dataset inicial de 30 a 50 perguntas."""
    assert 30 <= len(evaluator.load_dataset()["cases"]) <= 50


def test_validador_de_dataset_pega_tool_inexistente():
    problemas = evaluator.validate_dataset({
        "cases": [{"id": "x", "category": "y", "question": "z",
                   "expects": {"tools_any": ["get_salary"]}}]
    })
    assert any("tool inexistente" in p for p in problemas)


def test_validador_pega_id_duplicado():
    caso = {"id": "dup", "category": "c", "question": "q"}
    problemas = evaluator.validate_dataset({"cases": [caso, dict(caso)]})
    assert any("duplicado" in p for p in problemas)


def test_validador_pega_expectativa_contraditoria():
    problemas = evaluator.validate_dataset({
        "cases": [{"id": "x", "category": "c", "question": "q",
                   "expects": {"refuse_scope": True, "tools_any": ["get_player_bio"]}}]
    })
    assert any("nao pode esperar" in p for p in problemas)


# ---------------------------------------------------------------------------
# Avaliacao de caso
# ---------------------------------------------------------------------------
def test_caso_perfeito_passa(season_stats_payload):
    answer = "Em 2024-25, Jokic fez 29.6 pontos por jogo."
    turn = FakeTurn(
        answer=answer,
        tool_calls=[FakeRecord("get_player_season_stats", season_stats_payload)],
        fact_check=_ok_report(answer, season_stats_payload),
    )
    case = {
        "id": "t1", "category": "stats", "question": "q",
        "expects": {"tools_any": ["get_player_season_stats"], "season": "2024-25"},
    }
    resultado = metrics.evaluate_case(case, turn)
    assert resultado.passed, resultado.failures


def test_numero_sem_lastro_reprova(season_stats_payload):
    answer = "Jokic fez 33.1 pontos por jogo."
    turn = FakeTurn(
        answer=answer,
        tool_calls=[FakeRecord("get_player_season_stats", season_stats_payload)],
        fact_check=_ok_report(answer, season_stats_payload),
    )
    case = {"id": "t2", "category": "stats", "question": "q", "expects": {}}
    resultado = metrics.evaluate_case(case, turn)

    assert not resultado.passed
    assert any("sem lastro" in f for f in resultado.failures)


def test_tool_esperada_nao_chamada_reprova():
    turn = FakeTurn(answer="Acho que ele foi bem.")
    case = {"id": "t3", "category": "stats", "question": "q",
            "expects": {"tools_any": ["get_player_season_stats"]}}
    resultado = metrics.evaluate_case(case, turn)

    assert not resultado.passed
    assert any("nenhuma tool esperada" in f for f in resultado.failures)


def test_recusa_de_escopo_esperada_e_cumprida():
    turn = FakeTurn(answer="So respondo sobre NBA.", refused_scope=True)
    case = {"id": "t4", "category": "out_of_scope", "question": "q",
            "expects": {"refuse_scope": True, "no_tools": True}}
    assert metrics.evaluate_case(case, turn).passed


def test_recusa_esperada_mas_respondida_reprova():
    turn = FakeTurn(answer="A capital da Franca e Paris.")
    case = {"id": "t5", "category": "out_of_scope", "question": "q",
            "expects": {"refuse_scope": True}}
    resultado = metrics.evaluate_case(case, turn)

    assert not resultado.passed
    assert any("deveria ter sido recusada" in f for f in resultado.failures)


def test_recusa_indevida_de_pergunta_valida_reprova():
    turn = FakeTurn(answer="So respondo sobre NBA.", refused_scope=True)
    case = {"id": "t6", "category": "stats", "question": "q",
            "expects": {"tools_any": ["get_player_season_stats"]}}
    resultado = metrics.evaluate_case(case, turn)

    assert not resultado.passed
    assert any("indevidamente" in f for f in resultado.failures)


def test_erro_estruturado_esperado():
    turn = FakeTurn(
        answer="Nao encontrei esse jogador.",
        tool_calls=[FakeRecord("get_player_bio", {"error": "player_not_found"})],
    )
    case = {"id": "t7", "category": "error_handling", "question": "q",
            "expects": {"tool_error": "player_not_found"}}
    assert metrics.evaluate_case(case, turn).passed


def test_flag_temporal_reprova(recent_games_payload):
    turn = FakeTurn(
        answer="No jogo de ontem ele fez 40 pontos.",
        tool_calls=[FakeRecord("get_recent_games", recent_games_payload)],
        temporal_flags=temporal.check(
            "No jogo de ontem ele fez 40 pontos.", [recent_games_payload]
        ),
    )
    case = {"id": "t8", "category": "recent_form", "question": "q", "expects": {}}
    resultado = metrics.evaluate_case(case, turn)

    assert not resultado.passed
    assert any("temporal" in f for f in resultado.failures)


def test_termo_proibido_na_resposta():
    turn = FakeTurn(answer="Ele e o atual MVP da liga.")
    case = {"id": "t9", "category": "ambiguous", "question": "q",
            "expects": {"answer_not_contains": ["atual MVP"]}}
    resultado = metrics.evaluate_case(case, turn)
    assert not resultado.passed


def test_pedido_de_esclarecimento_aceita_varias_formas():
    """
    Respostas reais do agente. Cobrar frase exata reprovava resposta certa --
    foi o que aconteceu na primeira rodada da avaliacao.
    """
    for resposta in [
        "Por favor, me informe o nome do jogador que você gostaria de analisar.",
        "De qual jogador voce esta falando?",
        "Qual jogador voce quer analisar?",
        "Poderia especificar o atleta?",
        "Nao ficou claro a quem voce se refere.",
    ]:
        assert metrics.asks_for_clarification(resposta), resposta


def test_resposta_que_adivinha_nao_conta_como_esclarecimento():
    assert not metrics.asks_for_clarification("Ele esta indo muito bem na temporada.")


def test_expectativa_de_esclarecimento_reprova_quem_adivinha():
    turn = FakeTurn(answer="Ele esta jogando muito bem.")
    case = {"id": "t12", "category": "ambiguous", "question": "q",
            "expects": {"asks_clarification": True}}
    resultado = metrics.evaluate_case(case, turn)

    assert not resultado.passed
    assert any("esclarecimento" in f for f in resultado.failures)


def test_reconhecimento_de_limitacao_ignora_acento():
    turn = FakeTurn(answer="Não tenho esse dado: nenhuma tool fornece salário.")
    case = {"id": "t10", "category": "out_of_contract", "question": "q",
            "expects": {"answer_contains_any": ["nao tenho"]}}
    assert metrics.evaluate_case(case, turn).passed


def test_erro_do_agente_reprova():
    turn = FakeTurn(answer="", error="429 rate limit")
    case = {"id": "t11", "category": "stats", "question": "q", "expects": {}}
    resultado = metrics.evaluate_case(case, turn)

    assert not resultado.passed
    assert any("erro do agente" in f for f in resultado.failures)


# ---------------------------------------------------------------------------
# Agregacao
# ---------------------------------------------------------------------------
def _resultado(passed: bool, **m) -> metrics.CaseResult:
    base = {
        "latency_s": 10.0, "api_calls": 2, "prompt_tokens": 1000,
        "completion_tokens": 200, "cost_usd": 0.0005, "numeric_claims": 10,
        "unverified_claims": 0, "out_of_contract": [], "corrections": 0,
        "contract_issues": [], "error": None,
    }
    base.update(m)
    return metrics.CaseResult(
        case_id="x", category=m.get("categoria", "stats"), question="q",
        passed=passed, metrics=base,
    )


def test_agregacao_calcula_as_metricas_da_fase_1():
    resultados = [
        _resultado(True),
        _resultado(True),
        _resultado(False, unverified_claims=2, numeric_claims=10),
    ]
    resumo = metrics.aggregate(resultados)

    assert resumo["cases"] == 3
    assert resumo["success_rate"] == pytest.approx(2 / 3)
    assert resumo["numeric_claims"] == 30
    assert resumo["unverified_claims"] == 2
    assert resumo["numeric_accuracy"] == pytest.approx(28 / 30)
    assert resumo["hallucination_rate_by_answer"] == pytest.approx(1 / 3)
    assert resumo["total_api_calls"] == 6
    assert resumo["total_cost_usd"] == pytest.approx(0.0015)
    assert resumo["latency_p50_s"] == 10.0


def test_agregacao_sem_casos_nao_quebra():
    assert metrics.aggregate([])["cases"] == 0


def test_resposta_sem_numero_nao_penaliza_a_correcao_numerica():
    resumo = metrics.aggregate([_resultado(True, numeric_claims=0, unverified_claims=0)])
    assert resumo["numeric_accuracy"] == 1.0


def test_relatorio_markdown_sai_completo():
    resultados = [_resultado(True), _resultado(False, unverified_claims=1)]
    resultados[1].failures = ["numeros sem lastro nas tools: 44.5"]
    texto = metrics.format_report(metrics.aggregate(resultados), resultados, model="gpt-4o-mini")

    assert "Taxa de sucesso" in texto
    assert "Correcao numerica" in texto
    assert "44.5" in texto
    assert "| PASS |" in texto and "| FAIL |" in texto
