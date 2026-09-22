"""
Grounding temporal.

Motivacao vinda de teste real: em 21/09/2026 (pleno off-season), perguntado
"como o Wembanyama jogou ontem?", o agente devolveu o jogo de 10/04/2026 --
cinco meses antes -- e o narrou como "o jogo de ontem". O dado estava certo; a
moldura temporal estava inventada.

A causa e simples: as tools devolviam o ultimo jogo do log sem dizer QUANDO ele
foi em relacao a hoje, e o modelo nao tem relogio. A correcao tem duas pernas:

  1. as tools passam a carregar `data_freshness` (hoje, data do ultimo jogo,
     dias de distancia, se a temporada esta em andamento) -- ver tools.py;
  2. este modulo confere se a resposta usa vocabulario de "agora" quando o dado
     mais recente e velho, e cobra a data explicita quando o usuario perguntou
     em termos de dia.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

# Acima disso, chamar o jogo de "recente" sem qualificar a data engana o leitor.
STALE_AFTER_DAYS = 7

_DAY_LEVEL_WORDS = (
    "ontem", "anteontem", "hoje", "esta noite", "ontem a noite",
    "esta semana", "nesta semana", "semana passada", "nos ultimos dias",
    "nestes ultimos dias", "acabou de", "acaba de", "neste momento",
    "agora ha pouco", "no ultimo jogo de ontem",
)

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


@dataclass(frozen=True)
class TemporalFlag:
    kind: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def parse_game_date(raw: Any) -> date | None:
    """
    Data de jogo da nba_api ("APR 10, 2026") -> date.

    Aceita tambem ISO ("2026-04-10"), que e como alguns endpoints devolvem.
    """
    if isinstance(raw, date):
        return raw
    text = str(raw or "").strip()
    if not text:
        return None

    iso = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None

    match = re.match(r"([A-Za-z]{3})[A-Za-z]*\s+(\d{1,2}),?\s+(\d{4})", text)
    if match:
        month = _MONTHS.get(match.group(1).lower())
        if month:
            try:
                return date(int(match.group(3)), month, int(match.group(2)))
            except ValueError:
                return None

    for fmt in ("%b %d, %Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def describe_freshness(last_game: Any, today: date | None = None) -> dict[str, Any]:
    """
    Bloco `data_freshness` que as tools anexam ao resultado.

    E o relogio que o modelo nao tem: sem isto ele so ve "ultimo jogo do log" e
    assume que log recente significa jogo recente.
    """
    today = today or date.today()
    parsed = parse_game_date(last_game)
    if parsed is None:
        return {
            "today": today.isoformat(),
            "last_game_date": None,
            "days_since_last_game": None,
            "is_recent": None,
            "note": "Nao foi possivel determinar a data do ultimo jogo.",
        }

    days = (today - parsed).days
    recent = days <= STALE_AFTER_DAYS
    if recent:
        note = f"Ultimo jogo ha {days} dia(s). Dados atuais."
    else:
        note = (
            f"ATENCAO: o ultimo jogo deste jogador foi em {parsed.isoformat()}, "
            f"ha {days} dias. Hoje e {today.isoformat()}. NAO descreva estes jogos "
            "como 'ontem', 'hoje' ou 'esta semana' -- cite a data real e, se for o "
            "caso, diga que a temporada nao esta em andamento."
        )
    return {
        "today": today.isoformat(),
        "last_game_date": parsed.isoformat(),
        "days_since_last_game": days,
        "is_recent": recent,
        "note": note,
    }


def _freshness_blocks(tool_results: Iterable[Any]) -> list[dict]:
    blocks: list[dict] = []
    for result in tool_results or []:
        if isinstance(result, dict):
            block = result.get("data_freshness")
            if isinstance(block, dict):
                blocks.append(block)
    return blocks


def _mentions_day_level(text: str) -> list[str]:
    lowered = (text or "").lower()
    return [word for word in _DAY_LEVEL_WORDS if word in lowered]


def check(
    answer: str,
    tool_results: Iterable[Any] | None = None,
    question: str | None = None,
) -> list[TemporalFlag]:
    """Flags de moldura temporal errada na resposta."""
    results = list(tool_results or [])
    blocks = _freshness_blocks(results)
    if not blocks:
        return []

    stale = [b for b in blocks if b.get("is_recent") is False]
    if not stale:
        return []

    flags: list[TemporalFlag] = []
    oldest = max(stale, key=lambda b: b.get("days_since_last_game") or 0)
    days = oldest.get("days_since_last_game")
    last = oldest.get("last_game_date")

    used = _mentions_day_level(answer)
    if used:
        flags.append(
            TemporalFlag(
                kind="stale_as_current",
                detail=(
                    f"a resposta usa \"{used[0]}\" mas o jogo mais recente e de {last} "
                    f"({days} dias atras)"
                ),
            )
        )

    # Usuario perguntou em termos de dia: a resposta precisa dizer a data real.
    if _mentions_day_level(question or "") and last and last not in (answer or ""):
        readable = _readable(last)
        if readable and readable.lower() not in (answer or "").lower():
            flags.append(
                TemporalFlag(
                    kind="missing_date_disclosure",
                    detail=(
                        f"a pergunta fala em dia especifico e o dado tem {days} dias, "
                        f"mas a resposta nao informa a data real ({last})"
                    ),
                )
            )
    return flags


def _readable(iso: str) -> str | None:
    """'2026-04-10' -> '10 de abril de 2026', como o modelo costuma escrever."""
    try:
        parsed = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    meses = [
        "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
    ]
    return f"{parsed.day} de {meses[parsed.month - 1]} de {parsed.year}"


def correction_prompt(flags: list[TemporalFlag]) -> str:
    linhas = [
        "VERIFICACAO TEMPORAL REPROVOU A RESPOSTA ANTERIOR.",
        "",
        "Os resultados das tools trazem o bloco `data_freshness` com a data de hoje "
        "e a data real do ultimo jogo. Problemas encontrados:",
        "",
    ]
    linhas += [f"- {flag.detail}" for flag in flags]
    linhas += [
        "",
        "Reescreva a resposta citando a data real dos jogos e deixando claro ha "
        "quanto tempo eles aconteceram. Se a diferenca for grande, diga que a "
        "temporada provavelmente nao esta em andamento. Responda apenas com a "
        "resposta corrigida.",
    ]
    return "\n".join(linhas)
