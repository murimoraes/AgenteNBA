"""
Fact checker numerico deterministico.

O README promete que "o LLM nunca inventa numero". Ate aqui isso era uma
instrucao de system prompt -- ou seja, um comportamento provavel, nao uma
garantia. Este modulo fecha a lacuna: depois que o modelo escreve, cada numero
da resposta e confrontado com o que as tools realmente devolveram no turno.

Como funciona
-------------
1. EVIDENCIA -- percorre recursivamente o JSON de todas as tools do turno e
   coleta todo valor numerico, inclusive os que estao dentro de strings
   ("13/19", "Apr 10, 2026", "0-100"). Entram tambem os numeros da pergunta do
   usuario e dos argumentos passados as tools, porque sao dados legitimos da
   conversa. Percentuais guardados como fracao (0.513) entram tambem na forma
   51.3, que e como o texto os cita.
2. DERIVACAO -- aproveitamentos que o modelo calcula a partir de dois numeros
   presentes na evidencia (13/19 -> 68.4%) sao aceitos: o insumo veio da tool.
3. CLAIMS -- extrai os numeros escritos pelo modelo, ignorando marcadores de
   lista e lendo separador decimal tanto en quanto pt-BR.
4. CONFRONTO -- um claim e valido se casar com alguma evidencia dentro da
   tolerancia da propria precisao com que foi escrito (29.6 casa com 29.6428).
5. CONTRATO -- metricas que NENHUMA tool fornece (salario, contrato, premios,
   titulos, posicao na tabela) sao barradas por padrao, mesmo que o numero
   coincida com alguma evidencia por acaso. E o caso que quebrou no teste real:
   "LeBron tem um salario de 44.5 milhoes" -- nenhuma tool devolve salario.

O modulo nao apaga texto: ele relata. Quem decide o que fazer com o relatorio
e o agente (pedir correcao ao modelo) e a interface (avisar o usuario).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# Margem para ruido de ponto flutuante.
_EPS = 1e-9

# Quanto de texto ao redor do numero entra no contexto do claim.
_CONTEXT_WINDOW = 60

_NUMBER_RE = re.compile(r"\d[\d.,]*")
_SEASON_RE = re.compile(r"\b(?:19|20)\d{2}-\d{2}\b")
_FRACTION_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_LIST_MARKER_RE = re.compile(r"(?m)^\s{0,6}\d{1,2}[.)]\s")

# Metricas fora do contrato de dados: nenhuma tool do projeto as fornece, entao
# qualquer afirmacao sobre elas so pode ter vindo da memoria do modelo.
# (chave legivel -> padrao no texto)
OUT_OF_CONTRACT_METRICS: dict[str, str] = {
    "salario/contrato": r"\b(sal[aá]rio|sal[aá]rios|contrato|contratos|remunera[cç][aã]o|"
                        r"luxury\s*tax|teto\s+salarial|market\s+value|valor\s+de\s+mercado)\b",
    "valores monetarios": r"(?:US\$|R\$|\$|USD)\s*\d|\b\d+[.,]?\d*\s*(?:milh[oõ]es|milh[aã]o|bilh[oõ]es)\b",
    "premios individuais": r"\b(MVP|DPOY|ROY|Sexto\s+Homem|All[-\s]?Star|All[-\s]?NBA|"
                           r"Hall\s+da\s+Fama|Hall\s+of\s+Fame|melhor\s+defensor\s+do\s+ano)\b",
    "titulos/playoffs": r"\b(t[ií]tulos?|campe[aã]o|campeonatos?|an[eé]is?|finais\s+da\s+NBA|"
                        r"playoffs?)\b",
    "classificacao do time": r"\b(lidera\s+a\s+confer[eê]ncia|primeiro\s+lugar\s+d[ao]|"
                             r"\d+[oº]\s+lugar|posi[cç][aã]o\s+na\s+tabela|campanha\s+do\s+time)\b",
    "lesoes/contexto de elenco": r"\b(les[aã]o|lesionado|contundido|machucado|trade|troca\s+para\s+o|"
                                 r"assinou\s+com|foi\s+negociado)\b",
}

_COMPILED_OUT_OF_CONTRACT = {
    label: re.compile(pattern, re.IGNORECASE)
    for label, pattern in OUT_OF_CONTRACT_METRICS.items()
}

# Reconhecer a ausencia do dado e o comportamento DESEJADO. Sem isto, "este
# sistema nao tem dados sobre salarios" seria punido igual a "o salario e 44.5
# milhoes", so por citar a palavra -- e o agente aprenderia a esconder a
# limitacao em vez de declara-la.
_DECLINE_PATTERN = re.compile(
    r"\bn[ao]o\s+(?:tem|tenho|ha|possui|possuo|disponho|dispoe|dispomos|fornece|"
    r"forneco|consigo|consegue|posso|sei|inclui|cobre|trabalho\s+com|"
    r"e\s+fornecid\w*|sao\s+fornecid\w*|esta\s+disponivel|estao\s+disponiveis)\b"
    r"|\bnenhuma\s+(?:tool|ferramenta|fonte)\b"
    r"|\bsem\s+(?:dados|acesso|informacao)\b"
    r"|\bfora\s+do\s+(?:meu\s+)?escopo\b"
    r"|\b(?:tool|ferramenta)\s+necessaria\s+.{0,30}nao\s+esta\s+disponivel\b"
    r"|\bindisponivel\b|\bnao\s+disponivel\b",
    re.IGNORECASE,
)


def _strip_accents(text: str) -> str:
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def declines_to_answer(text: str) -> bool:
    """A resposta admite explicitamente que o dado nao existe no sistema."""
    return bool(_DECLINE_PATTERN.search(_strip_accents(text or "")))


def _sentence_around(text: str, index: int) -> str:
    """Frase que contem a posicao dada -- a granularidade certa para julgar."""
    inicio = max(
        text.rfind(".", 0, index), text.rfind("!", 0, index),
        text.rfind("?", 0, index), text.rfind("\n", 0, index),
    ) + 1
    fins = [p for p in (
        text.find(".", index), text.find("!", index),
        text.find("?", index), text.find("\n", index),
    ) if p != -1]
    fim = min(fins) + 1 if fins else len(text)
    return text[inicio:fim]


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Claim:
    """Um numero escrito pelo modelo, com o trecho em que apareceu."""

    raw: str
    values: tuple[tuple[float, int], ...]  # (valor, casas decimais) por leitura plausivel
    context: str
    position: int

    @property
    def value(self) -> float:
        return self.values[0][0] if self.values else float("nan")

    def __str__(self) -> str:
        return f"{self.raw} (em \"{self.context.strip()}\")"


@dataclass(frozen=True)
class ContractFlag:
    """Afirmacao sobre uma metrica que nenhuma tool fornece."""

    metric: str
    excerpt: str

    def __str__(self) -> str:
        return f"{self.metric}: \"{self.excerpt.strip()}\""


@dataclass
class Evidence:
    """Tudo que o turno realmente produziu de numero."""

    values: set[float] = field(default_factory=set)
    seasons: set[str] = field(default_factory=set)

    def add_number(self, value: float) -> None:
        if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
            return
        self.values.add(float(value))
        # Percentual guardado como fracao (0.513) e citado como 51.3.
        if 0.0 <= value <= 1.0:
            self.values.add(round(float(value) * 100.0, 6))

    def add_text(self, text: str) -> None:
        for season in _SEASON_RE.findall(text):
            self.seasons.add(season)
        for match in _NUMBER_RE.finditer(text):
            for value, _decimals in _parse_candidates(match.group()):
                self.add_number(value)
        # "13/19" -> tambem vale o aproveitamento que o modelo calcula a partir dele.
        for made, attempted in _FRACTION_RE.findall(text):
            self._add_ratio(float(made), float(attempted))

    def _add_ratio(self, made: float, attempted: float) -> None:
        if attempted:
            self.add_number(round(made / attempted * 100.0, 6))

    def supports(self, value: float, decimals: int) -> bool:
        """
        Um numero escrito com N casas decimais pode ser o arredondamento de
        qualquer evidencia dentro de meia casa -- e assim que arredondamento
        funciona, entao a tolerancia acompanha a precisao do proprio claim.
        """
        tolerance = 0.5 * (10.0 ** -decimals) + _EPS
        return any(abs(candidate - value) <= tolerance for candidate in self.values)

    def supports_season(self, season: str) -> bool:
        return season in self.seasons

    def __len__(self) -> int:  # pragma: no cover - conveniencia de debug
        return len(self.values)


@dataclass
class FactCheckReport:
    """Resultado do confronto entre a resposta do modelo e as tools."""

    claims: list[Claim] = field(default_factory=list)
    unverified: list[Claim] = field(default_factory=list)
    unverified_seasons: list[str] = field(default_factory=list)
    out_of_contract: list[ContractFlag] = field(default_factory=list)
    evidence_size: int = 0
    checked: bool = True

    @property
    def ok(self) -> bool:
        return not self.unverified and not self.unverified_seasons and not self.out_of_contract

    @property
    def verified_count(self) -> int:
        return len(self.claims) - len(self.unverified)

    @property
    def hallucination_rate(self) -> float:
        """Fracao dos numeros escritos que nao tem lastro em tool."""
        if not self.claims:
            return 0.0
        return len(self.unverified) / len(self.claims)

    def summary(self) -> str:
        if not self.checked:
            return "Verificacao factual nao aplicada."
        if not self.claims and not self.out_of_contract:
            return "Resposta sem numeros a verificar."
        parts = [f"{self.verified_count}/{len(self.claims)} numeros conferidos contra as tools"]
        if self.unverified:
            parts.append(f"{len(self.unverified)} sem lastro")
        if self.unverified_seasons:
            parts.append(f"{len(self.unverified_seasons)} temporada(s) nao consultada(s)")
        if self.out_of_contract:
            parts.append(f"{len(self.out_of_contract)} fora do contrato de dados")
        return " - ".join(parts) + "."

    def correction_prompt(self) -> str:
        """Mensagem enviada ao modelo para ele mesmo corrigir a resposta."""
        linhas: list[str] = [
            "VERIFICACAO AUTOMATICA REPROVOU A RESPOSTA ANTERIOR.",
            "",
            "Um validador deterministico comparou cada numero que voce escreveu com o "
            "que as tools desta conversa realmente devolveram. Os itens abaixo NAO tem "
            "lastro em nenhum resultado de tool:",
            "",
        ]
        for claim in self.unverified:
            linhas.append(f"- numero {claim.raw} -- trecho: \"{claim.context.strip()}\"")
        for season in self.unverified_seasons:
            linhas.append(f"- temporada {season} -- nenhuma tool desta conversa retornou dados dela")
        for flag in self.out_of_contract:
            linhas.append(
                f"- {flag.metric} -- nenhuma tool deste sistema fornece esse dado. "
                f"Trecho: \"{flag.excerpt.strip()}\""
            )
        linhas += [
            "",
            "Reescreva a resposta inteira removendo ou corrigindo esses pontos. Onde o "
            "dado nao existe, diga explicitamente que voce nao tem essa informacao e "
            "qual tool seria necessaria -- nunca substitua por estimativa. Mantenha "
            "tudo que ja estava correto. Responda apenas com a resposta corrigida.",
        ]
        return "\n".join(linhas)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked": self.checked,
            "claims": len(self.claims),
            "verified": self.verified_count,
            "unverified": [c.raw for c in self.unverified],
            "unverified_seasons": list(self.unverified_seasons),
            "out_of_contract": [f.metric for f in self.out_of_contract],
            "hallucination_rate": round(self.hallucination_rate, 4),
            "evidence_size": self.evidence_size,
        }


# ---------------------------------------------------------------------------
# Parsing de numeros
# ---------------------------------------------------------------------------
def _parse_candidates(raw: str) -> list[tuple[float, int]]:
    """
    Leituras plausiveis de um numero escrito em texto livre.

    "1.710" pode ser mil setecentos e dez (separador de milhar) ou 1.71 com tres
    casas; "29,6" e decimal em pt-BR. Em vez de adivinhar o idioma do modelo,
    devolvemos todas as leituras e o confronto aceita qualquer uma delas.
    """
    cleaned = raw.strip().strip(".,")
    if not cleaned or not cleaned[0].isdigit():
        return []

    out: list[tuple[float, int]] = []
    seen: set[tuple[float, int]] = set()

    def add(value: float, decimals: int) -> None:
        key = (round(value, 6), decimals)
        if key not in seen:
            seen.add(key)
            out.append((value, decimals))

    if re.fullmatch(r"\d+", cleaned):
        add(float(cleaned), 0)
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", cleaned):  # 1.710
        add(float(cleaned.replace(".", "")), 0)
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", cleaned):  # 1,710
        add(float(cleaned.replace(",", "")), 0)
    if re.fullmatch(r"\d+\.\d+", cleaned):  # 29.6
        add(float(cleaned), len(cleaned.split(".")[1]))
    if re.fullmatch(r"\d+,\d+", cleaned):  # 29,6
        add(float(cleaned.replace(",", ".")), len(cleaned.split(",")[1]))
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+[.,]\d+", cleaned):  # 1.234,5
        normalized = cleaned.replace(".", "@").replace(",", ".").replace("@", "")
        try:
            add(float(normalized), len(normalized.split(".")[1]))
        except (ValueError, IndexError):
            pass
    return out


# ---------------------------------------------------------------------------
# Evidencia
# ---------------------------------------------------------------------------
_MADE_SUFFIXES = ("_made", "_made_per_game", "made")


def _add_derived_ratios(node: dict, evidence: Evidence) -> None:
    """
    Aproveitamentos que o modelo pode calcular a partir de dois campos da tool.

    Se a tool entregou 9.3 convertidos e 18.1 tentados, escrever "51.4%" nao e
    invencao -- e aritmetica sobre dado real. Aceitar isso evita falso positivo
    sem abrir a porta para numero sem origem.
    """
    for key, value in node.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        for suffix in _MADE_SUFFIXES:
            if not key.endswith(suffix):
                continue
            twin = key[: -len(suffix)] + suffix.replace("made", "attempted")
            other = node.get(twin)
            if isinstance(other, (int, float)) and not isinstance(other, bool) and other:
                evidence.add_number(round(float(value) / float(other) * 100.0, 6))


def _walk(node: Any, evidence: Evidence) -> None:
    if isinstance(node, dict):
        _add_derived_ratios(node, evidence)
        for key, value in node.items():
            evidence.add_text(str(key))
            _walk(value, evidence)
    elif isinstance(node, (list, tuple, set)):
        for item in node:
            _walk(item, evidence)
    elif isinstance(node, bool):
        return
    elif isinstance(node, (int, float)):
        evidence.add_number(float(node))
    elif isinstance(node, str):
        evidence.add_text(node)


def build_evidence(
    tool_results: Iterable[Any] | None = None,
    extra_texts: Iterable[str] | None = None,
) -> Evidence:
    """
    Conjunto de numeros legitimos do turno.

    `tool_results` sao os payloads das tools (pode incluir os argumentos usados);
    `extra_texts` serve para a pergunta do usuario -- se ele pediu "ultimos 7
    jogos", o 7 da resposta veio dele, nao da memoria do modelo.
    """
    evidence = Evidence()
    for result in tool_results or []:
        _walk(result, evidence)
    for text in extra_texts or []:
        if text:
            evidence.add_text(str(text))
    return evidence


# ---------------------------------------------------------------------------
# Extracao de claims
# ---------------------------------------------------------------------------
def _mask_list_markers(text: str) -> str:
    """Marcadores de lista ("1." no inicio da linha) nao sao afirmacoes."""
    return _LIST_MARKER_RE.sub(lambda m: " " * len(m.group()), text)


def extract_claims(text: str) -> list[Claim]:
    if not text:
        return []

    masked = _mask_list_markers(text)
    # As temporadas sao conferidas a parte; sem mascarar, "2024-25" viraria
    # dois claims numericos sem sentido (2024 e 25).
    masked = _SEASON_RE.sub(lambda m: " " * len(m.group()), masked)

    claims: list[Claim] = []
    for match in _NUMBER_RE.finditer(masked):
        candidates = _parse_candidates(match.group())
        if not candidates:
            continue
        start = max(0, match.start() - _CONTEXT_WINDOW // 2)
        end = min(len(text), match.end() + _CONTEXT_WINDOW // 2)
        claims.append(
            Claim(
                raw=match.group().strip().strip(".,"),
                values=tuple(candidates),
                context=text[start:end].replace("\n", " "),
                position=match.start(),
            )
        )
    return claims


def extract_seasons(text: str) -> list[str]:
    return list(dict.fromkeys(_SEASON_RE.findall(text or "")))


def find_out_of_contract(text: str) -> list[ContractFlag]:
    """
    Afirmacoes sobre metricas que nenhuma tool do sistema fornece.

    Julga FRASE A FRASE: citar a metrica para dizer que ela nao existe e o
    comportamento correto, e nao pode contar como violacao. So conta quando a
    metrica aparece numa frase que a afirma.
    """
    flags: list[ContractFlag] = []
    texto = text or ""

    for label, pattern in _COMPILED_OUT_OF_CONTRACT.items():
        for match in pattern.finditer(texto):
            frase = _sentence_around(texto, match.start())
            if declines_to_answer(frase):
                continue
            start = max(0, match.start() - 50)
            end = min(len(texto), match.end() + 50)
            flags.append(
                ContractFlag(metric=label, excerpt=texto[start:end].replace("\n", " "))
            )
            break  # uma ocorrencia afirmativa ja basta para a metrica
    return flags


# ---------------------------------------------------------------------------
# Confronto
# ---------------------------------------------------------------------------
def check(
    answer: str,
    tool_results: Iterable[Any] | None = None,
    question: str | None = None,
    enforce_contract: bool = True,
) -> FactCheckReport:
    """
    Confere a resposta do modelo contra os resultados de tool do turno.

    Uma resposta sem nenhuma tool chamada e o pior cenario: se ela contem
    numeros, todos sao necessariamente sem lastro.
    """
    results = list(tool_results or [])
    evidence = build_evidence(results, extra_texts=[question] if question else None)

    claims = extract_claims(answer)
    unverified = [
        claim for claim in claims
        if not any(evidence.supports(value, decimals) for value, decimals in claim.values)
    ]

    seasons = extract_seasons(answer)
    unverified_seasons = [s for s in seasons if not evidence.supports_season(s)]

    flags = find_out_of_contract(answer) if enforce_contract else []

    return FactCheckReport(
        claims=claims,
        unverified=unverified,
        unverified_seasons=unverified_seasons,
        out_of_contract=flags,
        evidence_size=len(evidence),
    )
