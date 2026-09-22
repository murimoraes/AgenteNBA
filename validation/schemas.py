"""
Contrato de dados das tools, nos dois sentidos.

ENTRADA (o que o modelo manda): a auditoria pede para nunca confiar em argumento
gerado por LLM. Aqui os argumentos sao validados contra o proprio schema
declarado em tools.py -- tipo, enum, faixa, propriedade desconhecida, formato de
temporada -- antes de a funcao Python rodar. Erro vira dict estruturado, que o
modelo consegue ler e corrigir, em vez de TypeError.

SAIDA (o que a tool devolve): cada payload e conferido contra invariantes do
dominio -- percentual entre 0 e 1, contagem nao negativa, temporada no formato
AAAA-AA, player_id coerente, campos obrigatorios presentes. Violacao nao derruba
a resposta: fica registrada no turno, porque um contrato quebrado silenciosamente
e como um numero errado chega ate o usuario.
"""

from __future__ import annotations

import re
from typing import Any

SEASON_RE = re.compile(r"^(19|20)\d{2}-\d{2}$")

_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
}


# ---------------------------------------------------------------------------
# Entrada: argumentos vindos do modelo
# ---------------------------------------------------------------------------
def _schema_for(tool_name: str, schemas: list[dict]) -> dict | None:
    for entry in schemas:
        function = entry.get("function") or {}
        if function.get("name") == tool_name:
            return function.get("parameters") or {}
    return None


def validate_arguments(
    tool_name: str, arguments: dict, schemas: list[dict]
) -> tuple[dict, list[str]]:
    """
    Confere os argumentos contra o schema publicado da tool.

    Devolve (argumentos_limpos, erros). Argumentos desconhecidos sao removidos
    em vez de repassados: chamar a funcao com um kwarg inventado viraria
    TypeError, e o modelo as vezes inventa parametro plausivel.
    """
    errors: list[str] = []
    if not isinstance(arguments, dict):
        return {}, [f"{tool_name}: argumentos deveriam ser um objeto JSON."]

    schema = _schema_for(tool_name, schemas)
    if schema is None:
        return dict(arguments), [f"{tool_name}: tool desconhecida."]

    properties: dict[str, dict] = schema.get("properties") or {}
    required: list[str] = schema.get("required") or []
    cleaned: dict[str, Any] = {}

    for key, value in arguments.items():
        spec = properties.get(key)
        if spec is None:
            errors.append(f"{tool_name}: parametro '{key}' nao existe no schema; ignorado.")
            continue
        if value is None:
            continue

        expected = spec.get("type")
        allowed = _JSON_TYPES.get(expected, ())
        # bool e subclasse de int em Python: nao deixar True virar 1.
        if expected in ("integer", "number") and isinstance(value, bool):
            errors.append(f"{tool_name}: '{key}' deveria ser {expected}, veio booleano.")
            continue
        if allowed and not isinstance(value, allowed):
            if expected == "integer" and isinstance(value, str) and value.strip().isdigit():
                value = int(value)  # modelo manda "5" em vez de 5 com frequencia
            elif expected == "number" and isinstance(value, str):
                try:
                    value = float(value.replace(",", "."))
                except ValueError:
                    errors.append(f"{tool_name}: '{key}' deveria ser {expected}.")
                    continue
            else:
                errors.append(f"{tool_name}: '{key}' deveria ser {expected}.")
                continue

        enum = spec.get("enum")
        if enum and value not in enum:
            errors.append(f"{tool_name}: '{key}'='{value}' fora do enum {enum}.")
            continue

        if expected == "integer":
            minimum, maximum = spec.get("minimum"), spec.get("maximum")
            if minimum is not None and value < minimum:
                errors.append(f"{tool_name}: '{key}'={value} abaixo do minimo {minimum}; ajustado.")
                value = minimum
            if maximum is not None and value > maximum:
                errors.append(f"{tool_name}: '{key}'={value} acima do maximo {maximum}; ajustado.")
                value = maximum

        if key.startswith("season") and isinstance(value, str) and value.strip():
            if not SEASON_RE.match(value.strip()):
                errors.append(
                    f"{tool_name}: temporada '{value}' fora do formato AAAA-AA (ex.: 2025-26)."
                )
                continue
            value = value.strip()

        cleaned[key] = value

    for key in required:
        if key not in cleaned or cleaned[key] in (None, ""):
            errors.append(f"{tool_name}: parametro obrigatorio '{key}' ausente.")

    return cleaned, errors


def arguments_error(tool_name: str, errors: list[str]) -> dict[str, Any]:
    """Erro estruturado de argumento, no mesmo padrao das demais tools."""
    return {
        "error": "invalid_arguments",
        "tool": tool_name,
        "issues": errors,
        "message": (
            f"Os argumentos enviados para {tool_name} nao passaram na validacao: "
            + " ".join(errors)
            + " Corrija a chamada e tente de novo."
        ),
    }


# ---------------------------------------------------------------------------
# Saida: contrato do payload devolvido
# ---------------------------------------------------------------------------
_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "get_player_season_stats": ("player", "player_id", "season", "games_played", "per_game"),
    "get_recent_games": ("player", "player_id", "season", "games", "games_returned"),
    "get_player_bio": ("player", "player_id"),
    "get_player_image": ("player", "player_id", "image_url", "has_official_photo"),
    "compare_players": (),  # varia entre mode='pair' e mode='similar'
}

# Campos que sao fracao (0..1) e nao percentual (0..100).
_FRACTION_HINTS = ("_pct", "_percentage", "fg_pct", "ts_pct")

# Campos que nunca podem ser negativos.
_NON_NEGATIVE_HINTS = (
    "games", "games_played", "games_started", "games_returned", "points", "rebounds",
    "assists", "steals", "blocks", "turnovers", "fouls", "minutes", "wins", "losses",
    "attempted", "made", "weight_lbs",
)


def _iter_leaves(node: Any, prefix: str = "") -> Any:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _iter_leaves(value, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            yield from _iter_leaves(value, f"{prefix}[{index}]")
    else:
        yield prefix, node


def validate_output(tool_name: str, payload: Any) -> list[str]:
    """Invariantes de dominio do resultado da tool. Lista vazia = contrato ok."""
    if not isinstance(payload, dict):
        return [f"{tool_name}: resultado deveria ser um objeto, veio {type(payload).__name__}."]

    if payload.get("error"):
        # Erro estruturado e um resultado valido -- desde que se explique.
        if not payload.get("message") and not payload.get("detail"):
            return [f"{tool_name}: erro '{payload['error']}' sem mensagem explicativa."]
        return []

    issues: list[str] = []

    for field in _REQUIRED_FIELDS.get(tool_name, ()):  # noqa: A001 - nome do dominio
        if payload.get(field) is None:
            issues.append(f"{tool_name}: campo obrigatorio '{field}' ausente.")

    player_id = payload.get("player_id")
    if player_id is not None and (not isinstance(player_id, int) or player_id <= 0):
        issues.append(f"{tool_name}: player_id invalido ({player_id!r}).")

    for key, value in _iter_leaves(payload):
        leaf = key.split(".")[-1].split("[")[0]

        if leaf == "season" and isinstance(value, str) and value:
            if not SEASON_RE.match(value):
                issues.append(f"{tool_name}: temporada '{value}' fora do formato AAAA-AA.")

        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue

        if any(leaf.endswith(hint) for hint in _FRACTION_HINTS):
            if not (0.0 <= float(value) <= 1.0):
                issues.append(f"{tool_name}: {key}={value} deveria ser fracao entre 0 e 1.")

        if any(leaf == hint or leaf.endswith(f"_{hint}") for hint in _NON_NEGATIVE_HINTS):
            if float(value) < 0:
                issues.append(f"{tool_name}: {key}={value} nao pode ser negativo.")

    resemblance = payload.get("resemblance")
    if isinstance(resemblance, (int, float)) and not (0.0 <= float(resemblance) <= 100.0):
        issues.append(f"{tool_name}: resemblance={resemblance} fora da escala 0-100.")

    if tool_name == "get_recent_games":
        games = payload.get("games")
        returned = payload.get("games_returned")
        if isinstance(games, list) and isinstance(returned, int) and len(games) != returned:
            issues.append(
                f"{tool_name}: games_returned={returned} nao bate com {len(games)} jogos."
            )

    return issues
