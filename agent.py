"""
Loop de tool use no formato OpenAI.

Serve OpenRouter e OpenAI sem distincao: o provider e so um base_url diferente,
resolvido em config.py. Nada neste arquivo depende de qual dos dois esta ativo.

Diferencas para o formato antigo da Anthropic, ja aplicadas aqui:
  - as tools sao lidas de choices[0].message.tool_calls, nao de blocos tool_use;
  - os argumentos chegam como STRING JSON em .function.arguments;
  - o resultado volta numa mensagem com role="tool" + tool_call_id (a Anthropic
    usava um bloco tool_result dentro de uma mensagem de user);
  - a mensagem do assistant com tool_calls precisa ser reenviada no historico
    antes das respostas de tool, senao a API rejeita a sequencia.

Orquestracao manual, sem framework.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable

import config
import tools as tool_registry
from validation import facts, schemas, scope, temporal

MAX_ITERATIONS = 6

# Quantas vezes o modelo pode ser chamado de volta para corrigir a propria
# resposta quando a verificacao reprova. Cada tentativa custa uma chamada de
# API, entao o padrao e uma; FACT_CHECK_RETRIES=0 desliga a correcao (o
# relatorio continua sendo produzido e exibido).
FACT_CHECK_RETRIES = int(os.getenv("FACT_CHECK_RETRIES", "1"))

SYSTEM_PROMPT = """\
Voce e um analista de scouting da NBA. Seu trabalho e transformar dados reais em
leitura tatica clara, em portugues do Brasil.

REGRA ABSOLUTA E INEGOCIAVEL — NUMEROS:
Voce NAO tem conhecimento proprio de estatisticas. Todo numero que aparecer na sua
resposta (pontos, rebotes, aproveitamento, altura, datas, scores de similaridade)
DEVE ter vindo de um resultado de tool nesta conversa. E proibido estimar,
arredondar de memoria, completar lacunas ou citar numero de temporada que voce nao
consultou. Se a tool nao retornou o dado, diga que nao tem o dado e ofereca buscar.
Se a tool retornar um erro, explique o erro ao usuario — nunca preencha com memoria.

Um validador deterministico confere cada numero da sua resposta contra o retorno
das tools depois que voce escreve. Numero sem lastro reprova a resposta inteira e
ela volta para voce corrigir — nao ha ganho em arriscar.

O QUE AS TOOLS FORNECEM — consulte antes de dizer que nao tem:
  get_player_season_stats  medias e totais da temporada, aproveitamentos, TS%
  get_recent_games         box scores recentes, medias do recorte, campanha
  get_player_bio           posicao, altura, peso, time, PAIS, UNIVERSIDADE,
                           ANO/RODADA/NUMERO DO DRAFT, anos de experiencia
  compare_players          similaridade de estilo + ARQUETIPOS de scouting
  get_player_archetypes    arquetipos de um jogador, sem precisar comparar
  get_player_image         foto oficial

FORA DO CONTRATO DE DADOS — NUNCA RESPONDA DE MEMORIA:
Nao existe tool para salario, contrato, valor de mercado, premios (MVP, DPOY,
All-Star, All-NBA), titulos, campanha do time, classificacao na conferencia,
lesoes ou transferencias. Perguntado sobre qualquer um desses, diga com todas as
letras que este sistema nao tem esse dado. Nao cite numero, nao estime, nao diga
"se nao me engano" — e nao use conhecimento proprio como substituto.

Essa recusa vale SO para a lista acima. Para tudo que esta na tabela de tools,
CHAME A TOOL em vez de recusar: dizer "nao tenho esse dado" sobre algo que uma
tool devolve e tao errado quanto inventar o dado.

ESCOPO:
Voce so responde sobre NBA. Pergunta de outro assunto: recuse em uma frase e
reoriente para o que o sistema faz.

TEMPO:
Voce nao tem relogio. Os resultados de get_recent_games trazem o bloco
`data_freshness` com a data de hoje, a data do ultimo jogo e a distancia em dias.
Use SEMPRE esse bloco antes de escrever "ontem", "hoje", "esta semana" ou
"recentemente". Se `is_recent` for falso, diga a data real do jogo e quantos dias
faz; se a distancia for de meses, avise que a temporada nao esta em andamento.

COMO TRABALHAR:
- Chame as tools necessarias antes de responder. Pode chamar varias de uma vez.
- Sempre que a pergunta for sobre um jogador especifico, chame get_player_image
  para ele, junto das demais tools — a interface mostra a foto ao lado da resposta.
- "Compare X e Y" sem dizer o que comparar quer dizer as DUAS coisas: chame
  get_player_season_stats para cada um (producao) e compare_players com
  mode='pair' (estilo). Comparar so o estilo responde metade da pergunta.
- Para "quem joga parecido com X", use compare_players com mode='similar'.
  Para "X se parece com Y?", use mode='pair'.
- Se o resultado trouxer `name_match`, o nome que voce pediu nao era exatamente o
  do jogador encontrado: diga ao usuario qual jogador voce assumiu.
- Se a pergunta usar pronome ambiguo ("ele", "os dois") e o turno anterior citou
  mais de um jogador, declare no inicio da resposta de quem voce esta falando.
- A similaridade e calculada em Python (z-score contra a liga + distancia
  euclidiana). A escala NAO e intuitiva: 50 nao significa "meio parecido", e sim
  "tao parecidos quanto dois jogadores sorteados ao acaso". Por isso cada
  resultado traz o campo `verdict` ja traduzido -- USE O VERDICT, nunca sua
  propria leitura do numero.
- O resultado traz tambem `archetypes`, com o arquetipo primario (e as vezes um
  secundario) por categoria: perfil de arremesso, criacao, organizacao, defesa,
  rebote, papel e fisico. ESSA E A PARTE MAIS UTIL DA COMPARACAO -- comece a
  resposta pelo arquetipo ("os dois sao criadores de pick-and-roll, mas...") e
  so depois use os numeros para sustentar a leitura. Em
  `archetypes.comparison` vem o que os dois compartilham e onde divergem; use
  essas categorias para estruturar a analise em vez de listar features soltas.
- Arquetipo e rotulo de regra deterministica, nao opiniao sua: use exatamente os
  rotulos que vierem no resultado. Se uma categoria vier com `note` de perfil
  equilibrado ou sem features na era, diga isso em vez de inventar um rotulo.
- Em mode='similar', a lista e ordenada por proximidade, mas estar na lista NAO
  quer dizer ser parecido. Quem vem com verdict "pouco parecidos", "diferentes"
  ou "opostos" deve ser apresentado como tal, ou simplesmente omitido. Nunca
  chame de "estilo parecido" quem o verdict nao sustenta.
- Se `isolated` for verdadeiro, diga que o jogador nao tem analogo proximo na liga
  antes de listar qualquer nome.
- Se o nome do jogador nao for encontrado, use as sugestoes retornadas e pergunte
  qual deles o usuario quis dizer. Nao chute.

COMO ESCREVER:
- Direto e analitico, como um relatorio de olheiro: o que o numero significa em
  quadra, nao so o numero.
- Sempre diga a que temporada os dados se referem.
- Markdown leve: paragrafos curtos e, quando ajudar, bullets. Sem emoji.
- Interprete livremente (estilo, papel no time, pontos fortes e fracos) — a
  restricao vale para NUMEROS, nao para analise.
"""


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict
    result: dict
    issues: list[str] = field(default_factory=list)


@dataclass
class AgentTurn:
    answer: str
    messages: list[dict]
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    model: str = ""
    usage: dict = field(default_factory=dict)
    error: str | None = None
    # --- verificacao (Fase 1) ---
    fact_check: facts.FactCheckReport | None = None
    temporal_flags: list[temporal.TemporalFlag] = field(default_factory=list)
    corrections: int = 0
    refused_scope: bool = False
    scope_reason: str = ""
    # --- observabilidade minima exigida pelo criterio de conclusao da Fase 1 ---
    latency_s: float = 0.0
    iterations: int = 0

    @property
    def contract_issues(self) -> list[str]:
        return [issue for rec in self.tool_calls for issue in rec.issues]

    @property
    def cost_usd(self) -> float | None:
        return config.estimate_cost(
            self.model,
            self.usage.get("prompt_tokens", 0),
            self.usage.get("completion_tokens", 0),
        )

    @property
    def verified(self) -> bool:
        """Resposta entregue sem pendencia de verificacao."""
        if self.refused_scope:
            return True
        if self.fact_check is None:
            return not self.temporal_flags
        return self.fact_check.ok and not self.temporal_flags

    def metrics(self) -> dict:
        """Linha de telemetria do turno, usada pela suite de eval."""
        report = self.fact_check
        return {
            "model": self.model,
            "latency_s": round(self.latency_s, 2),
            "iterations": self.iterations,
            "api_calls": self.usage.get("calls", 0),
            "prompt_tokens": self.usage.get("prompt_tokens", 0),
            "completion_tokens": self.usage.get("completion_tokens", 0),
            "cost_usd": self.cost_usd,
            "tool_calls": [rec.name for rec in self.tool_calls],
            "corrections": self.corrections,
            "refused_scope": self.refused_scope,
            "contract_issues": self.contract_issues,
            "numeric_claims": len(report.claims) if report else 0,
            "unverified_claims": len(report.unverified) if report else 0,
            "hallucination_rate": report.hallucination_rate if report else 0.0,
            "out_of_contract": [f.metric for f in report.out_of_contract] if report else [],
            "temporal_flags": [f.kind for f in self.temporal_flags],
            "verified": self.verified,
            "error": self.error,
        }


def _extract_error(response) -> str:
    """Le o campo 'error' que o OpenRouter devolve no lugar de 'choices'."""
    try:
        payload = response.model_dump()
    except Exception:
        payload = {}
    err = payload.get("error") or {}
    if isinstance(err, dict):
        msg = err.get("message") or ""
        code = err.get("code") or err.get("type") or ""
        meta = err.get("metadata") or {}
        provider = meta.get("provider_name") if isinstance(meta, dict) else None
        bits = [b for b in (str(msg), f"codigo {code}" if code else "", f"provider {provider}" if provider else "") if b]
        if bits:
            return " | ".join(bits) + "."
    return "A API nao detalhou o motivo."


def _execute(name: str, arguments: dict) -> tuple[dict, dict, list[str]]:
    """
    Valida os argumentos, roda a tool e confere o contrato de saida.

    Argumento vindo de LLM nao e confiavel: tipo errado, parametro inventado e
    temporada em formato livre chegam com frequencia. A validacao acontece antes
    da funcao Python rodar, e o que sobra vira erro estruturado que o modelo
    consegue ler e corrigir.

    Devolve (resultado, argumentos_usados, problemas_registrados).
    """
    fn = tool_registry.TOOL_FUNCTIONS.get(name)
    if fn is None:
        return (
            {
                "error": "unknown_tool",
                "tool": name,
                "message": (
                    f"A tool '{name}' nao existe. Disponiveis: "
                    + ", ".join(sorted(tool_registry.TOOL_FUNCTIONS))
                    + "."
                ),
            },
            arguments,
            [f"tool desconhecida: {name}"],
        )

    cleaned, arg_issues = schemas.validate_arguments(
        name, arguments, tool_registry.TOOL_SCHEMAS
    )
    # Problemas que a validacao ja resolveu (parametro ignorado, faixa ajustada)
    # nao impedem a execucao; os demais impedem.
    blocking = [i for i in arg_issues if "ignorado" not in i and "ajustado" not in i]
    if blocking:
        return schemas.arguments_error(name, blocking), cleaned, arg_issues

    try:
        result = fn(**cleaned)
    except TypeError as exc:
        return {"error": "bad_arguments", "tool": name, "detail": str(exc),
                "message": f"Chamada invalida de {name}: {exc}"}, cleaned, arg_issues
    except Exception as exc:  # a tool falhou: o modelo precisa saber, nao inventar
        return (
            {"error": "tool_failed", "tool": name, "detail": f"{type(exc).__name__}: {exc}",
             "message": f"A consulta {name} falhou: {type(exc).__name__}."},
            cleaned,
            arg_issues,
        )

    return result, cleaned, arg_issues + schemas.validate_output(name, result)


def _collect_player_ids(records: list[ToolCallRecord]) -> list[tuple[int, str]]:
    """Jogadores citados por qualquer tool, para garantir a foto na interface."""
    found: dict[int, str] = {}
    for rec in records:
        res = rec.result
        if not isinstance(res, dict) or res.get("error"):
            continue
        if res.get("player_id") and res.get("player"):
            found[int(res["player_id"])] = str(res["player"])
        for side in (res.get("players") or {}).values():
            if isinstance(side, dict) and side.get("player_id"):
                found[int(side["player_id"])] = str(side.get("name", ""))
    return list(found.items())


def _ensure_images(records: list[ToolCallRecord]) -> list[dict]:
    """
    Garantia deterministica da regra "pergunta sobre jogador -> mostra a foto".

    O prompt ja instrui o modelo a chamar get_player_image, mas a interface nao
    pode depender disso. Aqui a imagem e buscada para todo jogador que apareceu
    nos resultados e ainda nao tem foto carregada.
    """
    images: dict[int, dict] = {}
    for rec in records:
        if rec.name == "get_player_image" and not rec.result.get("error"):
            images[int(rec.result["player_id"])] = rec.result

    for pid, name in _collect_player_ids(records):
        if pid in images or not name:
            continue
        payload = tool_registry.get_player_image(name)
        if not payload.get("error"):
            images[pid] = payload

    return list(images.values())


def _verify(
    answer: str, records: list[ToolCallRecord], question: str
) -> tuple[facts.FactCheckReport, list[temporal.TemporalFlag]]:
    """Confere a resposta contra o que as tools devolveram neste turno."""
    results = [rec.result for rec in records]
    report = facts.check(answer, results, question=question)
    flags = temporal.check(answer, results, question=question)
    return report, flags


def _correction_message(
    report: facts.FactCheckReport, flags: list[temporal.TemporalFlag]
) -> str:
    blocos: list[str] = []
    if not report.ok:
        blocos.append(report.correction_prompt())
    if flags:
        blocos.append(temporal.correction_prompt(flags))
    return "\n\n".join(blocos)


def run_agent(
    user_message: str,
    history: list[dict] | None = None,
    on_event: Callable[[str, dict], None] | None = None,
    model: str | None = None,
    verify: bool = True,
    max_corrections: int | None = None,
) -> AgentTurn:
    """
    Executa um turno completo: chama o modelo, resolve as tools, devolve a resposta.

    `history` sao as mensagens dos turnos anteriores (ja no formato OpenAI).
    `on_event` recebe ("tool_start"|"tool_end"|"thinking"|"verifying", payload).
    `model` sobrepoe OPENROUTER_MODEL -- util para comparar modelos lado a lado
    sem mexer no .env. O client e o mesmo; so o campo `model` da request muda.
    `verify` liga a verificacao factual/temporal; `max_corrections` limita
    quantas vezes o modelo e chamado de volta para corrigir (custo por tentativa).

    Perguntas fora do dominio NBA sao recusadas ANTES da primeira chamada de API:
    custam zero token e nao passam pelo modelo, que responderia de memoria.
    """
    started = time.perf_counter()
    model = model or config.get_model()
    corrections_allowed = FACT_CHECK_RETRIES if max_corrections is None else max_corrections

    verdict = scope.classify(user_message, has_history=bool(history))
    if not verdict.in_scope:
        if on_event:
            on_event("scope_refused", {"reason": verdict.reason})
        return AgentTurn(
            answer=verdict.refusal_message(),
            messages=[{"role": "user", "content": user_message}],
            model=model,
            refused_scope=True,
            scope_reason=verdict.reason,
            latency_s=time.perf_counter() - started,
        )

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += history or []
    messages.append({"role": "user", "content": user_message})

    records: list[ToolCallRecord] = []
    usage: dict = {}
    corrections = 0
    iterations = 0
    provider = config.get_provider().label

    try:
        client = config.get_client()
    except config.ConfigError as exc:
        return AgentTurn(
            answer="", messages=messages, error=str(exc),
            latency_s=time.perf_counter() - started,
        )

    for _ in range(MAX_ITERATIONS):
        iterations += 1
        if on_event:
            on_event("thinking", {"model": model})

        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tool_registry.TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.3,
            )
        except Exception as exc:
            return AgentTurn(
                answer="",
                messages=messages,
                tool_calls=records,
                images=_ensure_images(records),
                model=model,
                usage=usage,
                iterations=iterations,
                latency_s=time.perf_counter() - started,
                error=f"Falha ao chamar o {provider} ({type(exc).__name__}): {exc}",
            )

        # Um turno faz varias chamadas (rodada de tools + rodada de sintese).
        # O consumo tem de ser SOMADO: guardar so a ultima subestima o custo real.
        if getattr(response, "usage", None):
            usage["prompt_tokens"] = usage.get("prompt_tokens", 0) + (response.usage.prompt_tokens or 0)
            usage["completion_tokens"] = usage.get("completion_tokens", 0) + (response.usage.completion_tokens or 0)
            usage["total_tokens"] = usage.get("total_tokens", 0) + (response.usage.total_tokens or 0)
            usage["calls"] = usage.get("calls", 0) + 1

        # O OpenRouter responde HTTP 200 com {"error": {...}} e choices=None quando
        # o provider recusa (rate limit do tier free, contexto estourado, modelo
        # fora do ar). A OpenAI levanta excecao nesses casos, entao este guarda so
        # dispara no OpenRouter -- mas sem ele o acesso a choices[0] estoura TypeError.
        if not getattr(response, "choices", None):
            detail = _extract_error(response)
            return AgentTurn(
                answer="",
                messages=messages,
                tool_calls=records,
                images=_ensure_images(records),
                model=model,
                usage=usage,
                iterations=iterations,
                latency_s=time.perf_counter() - started,
                error=(
                    f"O modelo '{model}' nao retornou resposta em {provider}. {detail}"
                    + (
                        " Modelos ':free' tem limite diario e por minuto; tente de "
                        "novo ou troque o modelo no .env."
                        if ":free" in model
                        else " Tente de novo ou troque o modelo no .env."
                    )
                ),
            )

        choice = response.choices[0]
        message = choice.message
        calls = message.tool_calls or []

        # A mensagem do assistant precisa entrar no historico exatamente como veio.
        assistant_entry: dict = {"role": "assistant", "content": message.content or ""}
        if calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.function.name, "arguments": c.function.arguments},
                }
                for c in calls
            ]
        messages.append(assistant_entry)

        if not calls:
            answer = message.content or ""

            report: facts.FactCheckReport | None = None
            flags: list[temporal.TemporalFlag] = []
            if verify:
                if on_event:
                    on_event("verifying", {"claims": None})
                report, flags = _verify(answer, records, user_message)

                # Reprovou e ainda ha tentativa: o modelo recebe a lista exata do
                # que ficou sem lastro e reescreve. E aqui que "nao inventar
                # numero" deixa de ser instrucao e vira etapa do pipeline.
                if (not report.ok or flags) and corrections < corrections_allowed:
                    corrections += 1
                    if on_event:
                        on_event(
                            "correcting",
                            {
                                "attempt": corrections,
                                "unverified": [c.raw for c in report.unverified],
                                "out_of_contract": [f.metric for f in report.out_of_contract],
                                "temporal": [f.kind for f in flags],
                            },
                        )
                    messages.append(
                        {"role": "user", "content": _correction_message(report, flags)}
                    )
                    continue

            return AgentTurn(
                answer=answer,
                messages=messages,
                tool_calls=records,
                images=_ensure_images(records),
                model=model,
                usage=usage,
                fact_check=report,
                temporal_flags=flags,
                corrections=corrections,
                iterations=iterations,
                latency_s=time.perf_counter() - started,
            )

        for call in calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if on_event:
                on_event("tool_start", {"name": name, "arguments": args})

            result, used_args, issues = _execute(name, args)
            records.append(
                ToolCallRecord(name=name, arguments=used_args, result=result, issues=issues)
            )

            if on_event:
                on_event(
                    "tool_end",
                    {"name": name, "arguments": used_args, "result": result, "issues": issues},
                )

            # Formato OpenAI para devolver resultado de tool.
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )

    return AgentTurn(
        answer="",
        messages=messages,
        tool_calls=records,
        images=_ensure_images(records),
        model=model,
        usage=usage,
        corrections=corrections,
        iterations=iterations,
        latency_s=time.perf_counter() - started,
        error=f"Limite de {MAX_ITERATIONS} rodadas de tools atingido sem resposta final.",
    )
