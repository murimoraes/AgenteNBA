"""
Guardrail de escopo: a pergunta e sobre NBA?

Motivacao vinda de teste real: perguntado sobre a capital da Franca e um
restaurante em Paris, o agente respondeu normalmente, sem chamar tool nenhuma --
ou seja, entregou conhecimento paramétrico como se fosse dado verificado, que e
exatamente o que o projeto promete nao fazer.

A checagem roda ANTES da chamada ao modelo, entao pergunta fora do dominio custa
zero token. O criterio e deliberadamente permissivo: so recusa quando NAO ha
nenhum sinal de basquete e, ao mesmo tempo, ha sinal de outro dominio ou a
pergunta e autocontida (nao e um follow-up curto do tipo "e ele?").

Falso negativo (recusar pergunta valida) e pior que falso positivo aqui, porque
o usuario perde a resposta. Na duvida, deixa passar.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Vocabulario do dominio. Qualquer ocorrencia ja coloca a pergunta em escopo.
DOMAIN_TERMS: frozenset[str] = frozenset(
    """
    nba basquete basket basketball jogador jogadores jogadora atleta atletas time times
    equipe equipes franquia liga temporada temporadas jogo jogos partida partidas
    jogar jogando joga jogam jogou jogaram atuar atuando atua atuou rendendo rende
    rendimento marcando pontuando defendendo enfrentou enfrenta
    ponto pontos pontuacao rebote rebotes assistencia assistencias toco tocos bloqueio
    roubo roubos roubada turnover turnovers falta faltas cesta cestas arremesso arremessos
    arremessador arremessadores aproveitamento eficiencia estatistica estatisticas
    numeros medias media shooting scoring rating percentual aproveitamentos
    quadra garrafao perimetro poste pivo ala armador armadores alapivo escolta
    pontuador pontuadores reboteiro marcador marcadores
    draft rookie veterano titular reserva banco elenco rotacao minutos
    triplo duplo duplos triplos double cortina bandeja enterrada
    defesa defensivo defensiva ofensivo ofensiva ataque
    comparar comparacao parecido parecidos semelhante semelhantes similar similaridade
    estilo arquetipo scouting olheiro desempenho forma
    playoff playoffs conferencia divisao
    usg ts efg per pir fg ppg rpg apg
    lakers celtics warriors nuggets bucks heat knicks nets sixers 76ers spurs mavericks
    mavs suns clippers thunder timberwolves wolves grizzlies pelicans kings jazz
    rockets blazers trailblazers hawks hornets bulls cavaliers cavs pistons pacers
    magic raptors wizards
    """.split()
)

# Sinais fortes de outro dominio: reforcam a recusa quando nao ha termo de NBA.
OFF_DOMAIN_TERMS: frozenset[str] = frozenset(
    """
    receita receitas cozinhar restaurante restaurantes comida bebida vinho
    clima tempo temperatura previsao chuva
    capital capitais pais paises cidade cidades turismo viagem hotel voo
    presidente eleicao politica guerra economia inflacao bolsa acoes bitcoin
    remedio sintoma doenca medico diagnostico
    codigo programacao python javascript sql bug software
    futebol volei tenis formula1 f1 mma ufc beisebol hoquei
    namorada casamento signo horoscopo piada poema musica filme serie
    """.split()
)

# Follow-ups curtos ("e ele?", "e na temporada passada?") herdam o escopo do
# turno anterior; exigir vocabulario neles quebraria a conversa.
_FOLLOWUP_MAX_WORDS = 8
_PRONOUNS = frozenset(
    "ele ela eles elas dele dela deles delas isso isto esse essa aquele aquela "
    "mesmo mesma outro outra ambos".split()
)

# Palavras comuns que jamais devem ser lidas como sobrenome de jogador.
_COMMON_WORDS = frozenset(
    """
    copa mundo voce você costa bola jogo campo terra norte grande melhor pior
    quem qual quais quando onde como porque para pela pelo sobre entre depois
    antes agora hoje ontem amanha muito pouco todos todas alguns alguma outro
    outra mesmo ainda desde apenas tambem talvez favor obrigado receita clima
    tempo capital cidade pais signo codigo lista futebol copa final
    """.split()
)


@dataclass(frozen=True)
class ScopeVerdict:
    in_scope: bool
    reason: str

    def refusal_message(self) -> str:
        return (
            "Nao consigo ajudar com isso: este agente responde apenas sobre a NBA "
            "(jogadores, temporadas, estatisticas, forma recente e comparacao de "
            "estilo), e sempre a partir de consultas as tools de dados oficiais.\n\n"
            "Nao respondo por conhecimento proprio, porque nao teria como verificar "
            "o que estaria dizendo -- que e justamente o que este sistema se propoe "
            "a evitar.\n\n"
            "Se quiser, pergunte algo como \"como foi a temporada do Victor "
            "Wembanyama?\" ou \"quem joga num estilo parecido com o Jokic?\"."
        )


def _normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    return stripped.lower()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalize(text))


def _candidate_names(question: str) -> set[str]:
    """
    Tokens que podem ser nome proprio.

    A base estatica da NBA tem ~5000 jogadores, varios historicos e obscuros, e
    alguns sobrenomes colidem com palavras comuns do portugues -- ha um "Tom
    Copa" e um "Gary Voce" no indice. Aceitar qualquer token como possivel
    sobrenome fazia "Copa do Mundo de futebol" entrar no escopo. Por isso so
    tokens escritos com inicial maiuscula contam; se a pergunta foi digitada
    toda em minusculas, cai para tokens longos que nao sejam palavra comum.
    """
    capitalized = {
        _normalize(tok)
        for tok in re.findall(r"\b[A-ZÀ-Ý][\w'-]+", question or "")
    }
    capitalized -= _COMMON_WORDS
    if capitalized:
        return capitalized
    return {tok for tok in _tokens(question) if len(tok) >= 5} - _COMMON_WORDS


def _mentions_known_player(question: str) -> bool:
    """
    Nome de jogador da NBA na pergunta.

    Casamento ESTRITO de proposito. O resolve_player do nba_data e fuzzy, o que
    e otimo para responder mas perigoso aqui: qualquer palavra viraria jogador e
    furaria o guardrail.
    """
    try:
        from nba_api.stats.static import players as static_players
    except Exception:  # pragma: no cover - ambiente sem nba_api
        return False

    candidates = _candidate_names(question)
    if not candidates:
        return False

    for player in static_players.get_players():
        parts = _tokens(player.get("full_name", ""))
        if not parts:
            continue
        if len(parts[-1]) >= 4 and parts[-1] in candidates:
            return True
        if len(parts) >= 2 and parts[0] in candidates and parts[-1] in candidates:
            return True
    return False


def classify(question: str, has_history: bool = False) -> ScopeVerdict:
    """Decide se vale gastar uma chamada de API com esta pergunta."""
    text = (question or "").strip()
    if not text:
        return ScopeVerdict(False, "pergunta vazia")

    tokens = _tokens(text)
    # Plural simples ("armadores" -> "armador") sem trazer um stemmer inteiro.
    token_set = set(tokens)
    for tok in tokens:
        if tok.endswith("es") and len(tok) > 4:
            token_set.add(tok[:-2])
        if tok.endswith("s") and len(tok) > 3:
            token_set.add(tok[:-1])

    domain_hits = token_set & DOMAIN_TERMS
    if domain_hits:
        return ScopeVerdict(True, f"termo de dominio: {sorted(domain_hits)[0]}")

    # Temporada no formato da NBA ("2024-25") tambem e sinal de dominio.
    if re.search(r"\b(?:19|20)\d{2}-\d{2}\b", text):
        return ScopeVerdict(True, "temporada citada")

    if has_history and len(tokens) <= _FOLLOWUP_MAX_WORDS:
        return ScopeVerdict(True, "follow-up curto do turno anterior")

    if has_history and token_set & _PRONOUNS:
        return ScopeVerdict(True, "follow-up com pronome do turno anterior")

    # Sinal explicito de outro dominio vem ANTES do palpite de nome proprio:
    # o indice de jogadores tem homonimos de palavras comuns, entao "Copa do
    # Mundo de futebol" nao pode entrar por causa de um "Tom Copa" de 1989.
    off_hits = token_set & OFF_DOMAIN_TERMS
    if off_hits:
        return ScopeVerdict(False, f"dominio alheio: {sorted(off_hits)[0]}")

    if _mentions_known_player(text):
        return ScopeVerdict(True, "nome de jogador da NBA")

    return ScopeVerdict(False, "sem qualquer sinal de basquete na pergunta")


def is_in_scope(question: str, has_history: bool = False) -> bool:
    return classify(question, has_history).in_scope
