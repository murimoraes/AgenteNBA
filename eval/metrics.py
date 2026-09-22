"""
Metricas da suite de avaliacao.

Separado do evaluator de proposito: aqui nao ha I/O nem chamada de API, so
funcoes puras que transformam (caso esperado, turno obtido) em veredito. Isso
permite testar a propria avaliacao sem gastar um centavo -- ver
tests/test_eval.py.

As metricas sao as que o criterio de conclusao da Fase 1 exige: taxa de
sucesso, taxa de alucinacao, correcao numerica, latencia e custo.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from validation import facts


def normalize(text: str) -> str:
    """Comparacao de texto insensivel a acento e caixa."""
    stripped = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    return " ".join(stripped.lower().split())


# Pedir esclarecimento diante de pergunta ambigua e acerto, nao falha. A forma
# varia demais entre execucoes ("de qual jogador?", "me informe o nome...")
# para ser cobrada por frase fixa -- cobrar frase fixa reprovava resposta certa.
_CLARIFICATION_RE = re.compile(
    r"\b(?:qual|quais)\s+(?:e\s+o\s+)?(?:jogador|atleta|time|dupla)\b"
    r"|\bde\s+(?:qual|quem)\b"
    r"|\bme\s+(?:informe|diga|fale|passe)\b"
    r"|\b(?:informe|especifique|indique|diga)\s+(?:o\s+)?(?:nome|qual|quem)\b"
    r"|\bnao\s+(?:sei|ficou\s+claro)\s+a\s+(?:quem|qual)\b"
    r"|\bsobre\s+(?:qual|quem)\b"
    r"|\bpoderia\s+(?:informar|especificar|dizer)\b",
    re.IGNORECASE,
)


def asks_for_clarification(text: str) -> bool:
    """A resposta pede o dado que faltava em vez de adivinhar."""
    return bool(_CLARIFICATION_RE.search(normalize(text)))


@dataclass
class CaseResult:
    case_id: str
    category: str
    question: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    answer: str = ""
    metrics: dict = field(default_factory=dict)

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"


# ---------------------------------------------------------------------------
# Avaliacao de um caso
# ---------------------------------------------------------------------------
def evaluate_case(case: dict, turn: Any) -> CaseResult:
    """
    Confronta o turno obtido com as expectativas declaradas no dataset.

    `turn` e um agent.AgentTurn (ou qualquer objeto com a mesma superficie).
    """
    expects: dict = case.get("expects") or {}
    failures: list[str] = []

    answer = getattr(turn, "answer", "") or ""
    norm_answer = normalize(answer)
    tools_called = [rec.name for rec in getattr(turn, "tool_calls", [])]
    report = getattr(turn, "fact_check", None)

    if getattr(turn, "error", None):
        failures.append(f"erro do agente: {turn.error}")

    # --- escopo ---------------------------------------------------------
    refusal_expected = bool(expects.get("refuse_scope"))
    refused = bool(getattr(turn, "refused_scope", False))
    if refusal_expected and not refused:
        failures.append("deveria ter sido recusada por escopo, mas foi respondida")
    if not refusal_expected and refused:
        failures.append("recusada por escopo indevidamente")

    # --- selecao de tools ------------------------------------------------
    if not refused:
        tools_any = expects.get("tools_any") or []
        if tools_any and not any(t in tools_called for t in tools_any):
            failures.append(
                f"nenhuma tool esperada foi chamada (esperava uma de {tools_any}, "
                f"chamou {tools_called or 'nenhuma'})"
            )
        for tool in expects.get("tools_all") or []:
            if tool not in tools_called:
                failures.append(f"tool obrigatoria nao chamada: {tool}")
        for tool in expects.get("tools_forbidden") or []:
            if tool in tools_called:
                failures.append(f"tool proibida foi chamada: {tool}")
        if expects.get("no_tools") and tools_called:
            failures.append(f"nao deveria chamar tool, chamou {tools_called}")

    # --- erro estruturado esperado ---------------------------------------
    esperado_erro = expects.get("tool_error")
    if esperado_erro:
        erros = {
            rec.result.get("error")
            for rec in getattr(turn, "tool_calls", [])
            if isinstance(rec.result, dict)
        }
        if esperado_erro not in erros:
            failures.append(f"esperava erro estruturado '{esperado_erro}', obteve {erros or 'nenhum'}")

    # --- temporada correta -------------------------------------------------
    season = expects.get("season")
    if season:
        seasons_consultadas = {
            rec.result.get("season")
            for rec in getattr(turn, "tool_calls", [])
            if isinstance(rec.result, dict) and rec.result.get("season")
        }
        if season not in seasons_consultadas and season not in answer:
            failures.append(
                f"temporada {season} nao aparece nem nas tools nem na resposta "
                f"(consultadas: {sorted(s for s in seasons_consultadas if s)})"
            )

    # --- fidelidade numerica ----------------------------------------------
    if expects.get("no_hallucination", True) and report is not None:
        if report.unverified:
            failures.append(
                "numeros sem lastro nas tools: "
                + ", ".join(c.raw for c in report.unverified)
            )
        if report.unverified_seasons:
            failures.append(
                "temporadas nao consultadas citadas: " + ", ".join(report.unverified_seasons)
            )
        if report.out_of_contract:
            failures.append(
                "afirmacoes fora do contrato de dados: "
                + ", ".join(f.metric for f in report.out_of_contract)
            )

    if getattr(turn, "temporal_flags", None):
        failures.append(
            "moldura temporal errada: "
            + "; ".join(str(f) for f in turn.temporal_flags)
        )

    # --- conteudo da resposta ----------------------------------------------
    contains_any = expects.get("answer_contains_any") or []
    if contains_any and not any(normalize(t) in norm_answer for t in contains_any):
        failures.append(f"resposta nao contem nenhum dos termos esperados {contains_any}")

    # Para metrica fora do contrato, o acerto e ADMITIR a ausencia do dado. A
    # forma exata varia demais entre execucoes para ser cobrada por frase fixa.
    if expects.get("acknowledges_missing_data") and not facts.declines_to_answer(answer):
        failures.append("resposta nao admite explicitamente que o dado nao existe no sistema")

    if expects.get("asks_clarification") and not asks_for_clarification(answer):
        failures.append("resposta nao pede o esclarecimento que faltava (pergunta ambigua)")

    # Campos que precisam existir no payload da tool -- verifica o encanamento,
    # nao o texto: se o agente parar de receber o bloco, o eval acusa.
    for campo in expects.get("tool_result_has") or []:
        presente = any(
            isinstance(rec.result, dict) and rec.result.get(campo)
            for rec in getattr(turn, "tool_calls", [])
        )
        if not presente:
            failures.append(f"nenhum resultado de tool trouxe o campo '{campo}'")

    for termo in expects.get("answer_not_contains") or []:
        if normalize(termo) in norm_answer:
            failures.append(f"resposta contem termo proibido: '{termo}'")

    if expects.get("answer_not_empty", True) and not answer.strip():
        failures.append("resposta vazia")

    telemetria = turn.metrics() if hasattr(turn, "metrics") else {}

    return CaseResult(
        case_id=case["id"],
        category=case.get("category", "sem-categoria"),
        question=case["question"],
        passed=not failures,
        failures=failures,
        answer=answer,
        metrics=telemetria,
    )


# ---------------------------------------------------------------------------
# Agregacao
# ---------------------------------------------------------------------------
def _percentil(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    k = max(0, min(len(ordenados) - 1, int(round((len(ordenados) - 1) * p))))
    return ordenados[k]


def aggregate(results: list[CaseResult]) -> dict:
    """Numeros que o criterio de conclusao da Fase 1 pede."""
    if not results:
        return {"cases": 0}

    metrics = [r.metrics for r in results]
    latencias = [m.get("latency_s", 0.0) for m in metrics]
    custos = [m.get("cost_usd") for m in metrics]
    custos_validos = [c for c in custos if c is not None]

    claims = sum(m.get("numeric_claims", 0) for m in metrics)
    sem_lastro = sum(m.get("unverified_claims", 0) for m in metrics)

    com_alucinacao = sum(1 for m in metrics if m.get("unverified_claims", 0) > 0)
    fora_contrato = sum(1 for m in metrics if m.get("out_of_contract"))
    corrigidos = sum(1 for m in metrics if m.get("corrections", 0) > 0)
    com_erro = sum(1 for m in metrics if m.get("error"))
    violacoes = sum(len(m.get("contract_issues") or []) for m in metrics)

    por_categoria: dict[str, dict] = {}
    for r in results:
        bucket = por_categoria.setdefault(r.category, {"total": 0, "passou": 0})
        bucket["total"] += 1
        bucket["passou"] += int(r.passed)

    return {
        "cases": len(results),
        "passed": sum(1 for r in results if r.passed),
        "success_rate": sum(1 for r in results if r.passed) / len(results),
        # fidelidade numerica
        "numeric_claims": claims,
        "unverified_claims": sem_lastro,
        "numeric_accuracy": (claims - sem_lastro) / claims if claims else 1.0,
        "hallucination_rate_by_answer": com_alucinacao / len(results),
        "out_of_contract_answers": fora_contrato,
        # pipeline
        "answers_corrected": corrigidos,
        "contract_violations": violacoes,
        "agent_errors": com_erro,
        # custo e tempo
        "total_api_calls": sum(m.get("api_calls", 0) for m in metrics),
        "total_tokens": sum(
            m.get("prompt_tokens", 0) + m.get("completion_tokens", 0) for m in metrics
        ),
        "total_cost_usd": round(sum(custos_validos), 5) if custos_validos else None,
        "avg_cost_usd": (
            round(sum(custos_validos) / len(custos_validos), 6) if custos_validos else None
        ),
        "latency_avg_s": round(statistics.fmean(latencias), 2) if latencias else 0.0,
        "latency_p50_s": round(_percentil(latencias, 0.50), 2),
        "latency_p95_s": round(_percentil(latencias, 0.95), 2),
        "by_category": por_categoria,
    }


# ---------------------------------------------------------------------------
# Relatorio
# ---------------------------------------------------------------------------
def format_report(summary: dict, results: list[CaseResult], model: str = "") -> str:
    """Relatorio markdown da rodada, pronto para versionar."""
    if not results:
        return "# Avaliacao\n\nNenhum caso executado.\n"

    linhas = [
        "# Avaliacao do agente",
        "",
        f"- Modelo: `{model}`",
        f"- Casos: {summary['cases']}",
        f"- Taxa de sucesso: **{summary['success_rate']:.0%}** "
        f"({summary['passed']}/{summary['cases']})",
        f"- Correcao numerica: **{summary['numeric_accuracy']:.1%}** "
        f"({summary['numeric_claims'] - summary['unverified_claims']}/"
        f"{summary['numeric_claims']} numeros com lastro)",
        f"- Respostas com alucinacao numerica: {summary['hallucination_rate_by_answer']:.0%}",
        f"- Respostas fora do contrato de dados: {summary['out_of_contract_answers']}",
        f"- Respostas reescritas pelo fact checker: {summary['answers_corrected']}",
        f"- Violacoes de contrato nas tools: {summary['contract_violations']}",
        f"- Erros do agente: {summary['agent_errors']}",
        f"- Latencia: media {summary['latency_avg_s']}s - "
        f"p50 {summary['latency_p50_s']}s - p95 {summary['latency_p95_s']}s",
        f"- Chamadas de API: {summary['total_api_calls']} - "
        f"tokens {summary['total_tokens']}",
        f"- Custo total: US$ {summary['total_cost_usd']} "
        f"(media US$ {summary['avg_cost_usd']}/pergunta)"
        if summary.get("total_cost_usd") is not None
        else "- Custo: nao tabelado para este modelo",
        "",
        "## Por categoria",
        "",
        "| Categoria | Passou | Total |",
        "|---|---|---|",
    ]
    for categoria, dados in sorted(summary["by_category"].items()):
        linhas.append(f"| {categoria} | {dados['passou']} | {dados['total']} |")

    linhas += ["", "## Casos", "", "| ID | Status | Pergunta | Observacao |", "|---|---|---|---|"]
    for r in results:
        obs = "; ".join(r.failures) if r.failures else "-"
        pergunta = r.question.replace("|", "/")
        linhas.append(f"| {r.case_id} | {r.status} | {pergunta} | {obs[:180]} |")

    return "\n".join(linhas) + "\n"
