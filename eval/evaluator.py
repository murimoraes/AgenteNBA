"""
Runner da suite de avaliacao.

Diferente de tests/, esta suite CHAMA O MODELO DE VERDADE -- e portanto custa
dinheiro. Todo o desenho aqui gira em torno disso:

  * --budget e um teto RIGIDO de chamadas de API. O runner para antes de
    estourar, nao depois, e reporta o que ficou de fora.
  * --dry-run valida o dataset inteiro sem gastar nada.
  * --limit e --category permitem rodar um recorte.
  * o consumo real e impresso a cada caso, para nunca haver surpresa.

Uso:
    python -m eval.evaluator --dry-run
    python -m eval.evaluator --category out_of_scope     (custa zero: recusa local)
    python -m eval.evaluator --limit 10 --budget 30
    python -m eval.evaluator --budget 60 --out eval/resultados.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import agent  # noqa: E402
import config  # noqa: E402
from eval import metrics  # noqa: E402

DATASET = Path(__file__).with_name("dataset.json")

# Estimativa conservadora de chamadas por caso, usada para decidir se o proximo
# caso cabe no orcamento. Um turno tipico faz 2 (tools + sintese); com correcao
# do fact checker pode chegar a 3.
CALLS_PER_CASE = 3


def load_dataset(path: Path = DATASET) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_dataset(data: dict) -> list[str]:
    """Checagens do proprio dataset -- roda sem gastar API."""
    problemas: list[str] = []
    vistos: set[str] = set()
    conhecidas = set(agent.tool_registry.TOOL_FUNCTIONS)

    for case in data.get("cases", []):
        cid = case.get("id")
        if not cid:
            problemas.append("caso sem id")
            continue
        if cid in vistos:
            problemas.append(f"{cid}: id duplicado")
        vistos.add(cid)

        if not case.get("question"):
            problemas.append(f"{cid}: sem pergunta")
        if not case.get("category"):
            problemas.append(f"{cid}: sem categoria")

        expects = case.get("expects") or {}
        for chave in ("tools_any", "tools_all", "tools_forbidden"):
            for tool in expects.get(chave) or []:
                if tool not in conhecidas:
                    problemas.append(f"{cid}: tool inexistente em {chave}: {tool}")

        season = expects.get("season")
        if season and not (len(season) == 7 and season[4] == "-"):
            problemas.append(f"{cid}: temporada em formato invalido: {season}")

        if expects.get("refuse_scope") and expects.get("tools_any"):
            problemas.append(f"{cid}: nao pode esperar recusa de escopo E chamada de tool")

        # Casos multi-turno: o historico vai direto para a API, entao um
        # formato errado so apareceria como erro do provider no meio da rodada.
        for i, msg in enumerate(case.get("history") or []):
            if not isinstance(msg, dict) or msg.get("role") not in ("user", "assistant"):
                problemas.append(f"{cid}: historico[{i}] precisa ter role user/assistant")
            elif not isinstance(msg.get("content"), str) or not msg["content"].strip():
                problemas.append(f"{cid}: historico[{i}] sem conteudo")

    return problemas


def run(
    cases: list[dict],
    budget: int,
    model: str | None = None,
    verbose: bool = True,
) -> tuple[list[metrics.CaseResult], list[dict], int]:
    """
    Executa os casos respeitando o teto de chamadas.

    Devolve (resultados, casos_nao_executados, chamadas_gastas).
    """
    resultados: list[metrics.CaseResult] = []
    pulados: list[dict] = []
    gastas = 0

    for case in cases:
        # Recusa de escopo nao chama API: sempre cabe no orcamento.
        custa_api = not (case.get("expects") or {}).get("refuse_scope")
        if custa_api and gastas + CALLS_PER_CASE > budget:
            pulados.append(case)
            continue

        turn = agent.run_agent(
            case["question"], history=case.get("history"), model=model
        )
        gastas += turn.usage.get("calls", 0)
        resultado = metrics.evaluate_case(case, turn)
        resultados.append(resultado)

        if verbose:
            marcador = "ok  " if resultado.passed else "FALHA"
            print(
                f"[{marcador}] {resultado.case_id:<14} "
                f"api={turn.usage.get('calls', 0)} "
                f"acumulado={gastas}/{budget} "
                f"{turn.latency_s:.1f}s"
            )
            for falha in resultado.failures:
                print(f"         - {falha}")

    return resultados, pulados, gastas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Avaliacao do agente de scouting NBA.")
    parser.add_argument("--budget", type=int, default=30,
                        help="teto RIGIDO de chamadas de API (padrao: 30)")
    parser.add_argument("--limit", type=int, default=None, help="maximo de casos")
    parser.add_argument("--category", action="append", default=None,
                        help="filtra por categoria (pode repetir)")
    parser.add_argument("--case", action="append", default=None, help="roda ids especificos")
    parser.add_argument("--model", default=None, help="sobrepoe o modelo do .env")
    parser.add_argument("--dry-run", action="store_true",
                        help="valida o dataset sem chamar a API")
    parser.add_argument("--out", default=None, help="arquivo markdown de saida")
    parser.add_argument("--json-out", default=None, help="arquivo json com as metricas")
    args = parser.parse_args(argv)

    data = load_dataset()
    problemas = validate_dataset(data)
    if problemas:
        print("Dataset invalido:")
        for problema in problemas:
            print(f"  - {problema}")
        return 1

    cases = data["cases"]
    if args.category:
        alvos = {c.lower() for c in args.category}
        cases = [c for c in cases if c.get("category", "").lower() in alvos]
    if args.case:
        alvos = set(args.case)
        cases = [c for c in cases if c["id"] in alvos]
    if args.limit:
        cases = cases[: args.limit]

    if args.dry_run:
        print(f"Dataset valido: {len(data['cases'])} casos, {len(cases)} selecionados.")
        categorias: dict[str, int] = {}
        for case in cases:
            categorias[case["category"]] = categorias.get(case["category"], 0) + 1
        for categoria, total in sorted(categorias.items()):
            print(f"  {categoria:<18} {total}")
        sem_api = sum(1 for c in cases if (c.get("expects") or {}).get("refuse_scope"))
        print(
            f"\nCusto estimado: ate {(len(cases) - sem_api) * CALLS_PER_CASE} chamadas "
            f"({sem_api} casos nao chamam a API)."
        )
        return 0

    if not cases:
        print("Nenhum caso selecionado.")
        return 1

    model = args.model or config.get_model()
    print(f"Modelo: {model} | casos: {len(cases)} | teto: {args.budget} chamadas\n")

    resultados, pulados, gastas = run(cases, budget=args.budget, model=args.model)
    summary = metrics.aggregate(resultados)

    print(f"\n{'=' * 60}")
    print(f"Executados: {len(resultados)} | pulados por orcamento: {len(pulados)}")
    print(f"Chamadas de API usadas: {gastas}/{args.budget}")
    print(f"Taxa de sucesso: {summary['success_rate']:.0%}")
    print(f"Correcao numerica: {summary['numeric_accuracy']:.1%}")
    print(f"Custo: US$ {summary['total_cost_usd']}")
    if pulados:
        print("Nao executados: " + ", ".join(c["id"] for c in pulados))

    relatorio = metrics.format_report(summary, resultados, model=model)
    destino = Path(args.out) if args.out else Path(__file__).with_name(
        f"resultados_{date.today().isoformat()}.md"
    )
    destino.write_text(relatorio, encoding="utf-8")
    print(f"\nRelatorio: {destino}")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(
                {"summary": summary, "cases": [r.__dict__ for r in resultados]},
                ensure_ascii=False, indent=2, default=str,
            ),
            encoding="utf-8",
        )

    return 0 if summary["success_rate"] == 1.0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
