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
from dataclasses import dataclass, field
from typing import Callable

import config
import tools as tool_registry

MAX_ITERATIONS = 6

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

COMO TRABALHAR:
- Chame as tools necessarias antes de responder. Pode chamar varias de uma vez.
- Sempre que a pergunta for sobre um jogador especifico, chame get_player_image
  para ele, junto das demais tools — a interface mostra a foto ao lado da resposta.
- Para "quem joga parecido com X", use compare_players com mode='similar'.
  Para "X se parece com Y?", use mode='pair'.
- A similaridade e calculada em Python (z-score contra a liga + distancia
  euclidiana). A escala NAO e intuitiva: 50 nao significa "meio parecido", e sim
  "tao parecidos quanto dois jogadores sorteados ao acaso". Por isso cada
  resultado traz o campo `verdict` ja traduzido -- USE O VERDICT, nunca sua
  propria leitura do numero.
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


@dataclass
class AgentTurn:
    answer: str
    messages: list[dict]
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    model: str = ""
    usage: dict = field(default_factory=dict)
    error: str | None = None


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


def _execute(name: str, arguments: dict) -> dict:
    fn = tool_registry.TOOL_FUNCTIONS.get(name)
    if fn is None:
        return {"error": "unknown_tool", "tool": name}
    try:
        return fn(**arguments)
    except TypeError as exc:
        return {"error": "bad_arguments", "tool": name, "detail": str(exc)}
    except Exception as exc:  # a tool falhou: o modelo precisa saber, nao inventar
        return {"error": "tool_failed", "tool": name, "detail": f"{type(exc).__name__}: {exc}"}


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


def run_agent(
    user_message: str,
    history: list[dict] | None = None,
    on_event: Callable[[str, dict], None] | None = None,
    model: str | None = None,
) -> AgentTurn:
    """
    Executa um turno completo: chama o modelo, resolve as tools, devolve a resposta.

    `history` sao as mensagens dos turnos anteriores (ja no formato OpenAI).
    `on_event` recebe ("tool_start"|"tool_end"|"thinking", payload) para a UI.
    `model` sobrepoe OPENROUTER_MODEL -- util para comparar modelos lado a lado
    sem mexer no .env. O client e o mesmo; so o campo `model` da request muda.
    """
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += history or []
    messages.append({"role": "user", "content": user_message})

    records: list[ToolCallRecord] = []
    usage: dict = {}
    model = model or config.get_model()
    provider = config.get_provider().label

    try:
        client = config.get_client()
    except config.ConfigError as exc:
        return AgentTurn(answer="", messages=messages, error=str(exc))

    for _ in range(MAX_ITERATIONS):
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
            return AgentTurn(
                answer=message.content or "",
                messages=messages,
                tool_calls=records,
                images=_ensure_images(records),
                model=model,
                usage=usage,
            )

        for call in calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if on_event:
                on_event("tool_start", {"name": name, "arguments": args})

            result = _execute(name, args)
            records.append(ToolCallRecord(name=name, arguments=args, result=result))

            if on_event:
                on_event("tool_end", {"name": name, "arguments": args, "result": result})

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
        error=f"Limite de {MAX_ITERATIONS} rodadas de tools atingido sem resposta final.",
    )
