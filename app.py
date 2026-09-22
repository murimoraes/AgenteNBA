"""
Interface Streamlit do agente de scouting.

A UI nunca calcula estatistica: ela apenas desenha o que as tools devolveram.
Os cartoes sao montados a partir dos resultados de tool do turno, o que mantem
o texto do modelo e os numeros na tela sempre vindos da mesma fonte.
"""

from __future__ import annotations

import json

import streamlit as st

import agent
import config
import tools as tool_registry
import ui

st.set_page_config(
    page_title="Scouting Report - NBA",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(ui.CSS, unsafe_allow_html=True)

EXAMPLES = [
    "Como foi a temporada do Victor Wembanyama?",
    "Quem joga num estilo parecido com o Jokic?",
    "Compare o estilo do Anthony Edwards com o do Donovan Mitchell",
    "Como esta a forma recente do Giannis nos ultimos 7 jogos?",
]


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------
if "turns" not in st.session_state:
    st.session_state.turns = []      # turnos renderizados
if "history" not in st.session_state:
    st.session_state.history = []    # mensagens no formato OpenAI para o modelo
if "pending" not in st.session_state:
    st.session_state.pending = None


# ---------------------------------------------------------------------------
# Agrupamento dos resultados de tool para os componentes
# ---------------------------------------------------------------------------
def group_results(turn: agent.AgentTurn) -> dict:
    """Junta, por jogador, o que cada tool devolveu no turno."""
    by_player: dict[int, dict] = {}

    def slot(pid: int) -> dict:
        return by_player.setdefault(int(pid), {"image": None, "bio": None, "stats": None})

    for img in turn.images:
        slot(img["player_id"])["image"] = img

    for rec in turn.tool_calls:
        res = rec.result
        if not isinstance(res, dict) or res.get("error") or not res.get("player_id"):
            continue
        if rec.name == "get_player_bio":
            slot(res["player_id"])["bio"] = res
        elif rec.name == "get_player_season_stats":
            slot(res["player_id"])["stats"] = res

    comparisons = [
        rec.result for rec in turn.tool_calls
        if rec.name == "compare_players" and not rec.result.get("error")
    ]
    logs = [
        rec.result for rec in turn.tool_calls
        if rec.name == "get_recent_games" and not rec.result.get("error")
    ]
    perfis = [
        rec.result for rec in turn.tool_calls
        if rec.name == "get_player_archetypes" and not rec.result.get("error")
    ]
    errors = [
        (rec.name, rec.result) for rec in turn.tool_calls
        if isinstance(rec.result, dict) and rec.result.get("error")
    ]
    return {"players": by_player, "comparisons": comparisons, "logs": logs,
            "profiles": perfis, "errors": errors}


def render_turn(question: str, turn: agent.AgentTurn) -> None:
    st.markdown(ui.user_message(question), unsafe_allow_html=True)

    if turn.error:
        st.markdown(
            ui.notice(f"<b>Nao foi possivel completar a consulta.</b><br>{ui.esc(turn.error)}"),
            unsafe_allow_html=True,
        )
        return

    grouped = group_results(turn)

    # Jogadores mencionados: foto padronizada + identificacao + numeros
    for data in grouped["players"].values():
        if data["image"] or data["bio"] or data["stats"]:
            st.markdown(
                ui.player_card(data["image"], data["bio"], data["stats"]),
                unsafe_allow_html=True,
            )

    for comp in grouped["comparisons"]:
        block = ui.similar_panel(comp) if comp.get("mode") == "similar" else ui.pair_panel(comp)
        if block:
            st.markdown(block, unsafe_allow_html=True)
        if comp.get("mode") != "similar":
            arch = ui.archetype_panel(comp)
            if arch:
                st.markdown(arch, unsafe_allow_html=True)

    for perfil in grouped["profiles"]:
        bloco = ui.archetype_solo_panel(perfil)
        if bloco:
            st.markdown(bloco, unsafe_allow_html=True)

    for log in grouped["logs"]:
        st.markdown(ui.games_table(log), unsafe_allow_html=True)

    if turn.answer:
        # O texto do modelo e markdown: deixa o Streamlit renderizar e estiliza
        # via CSS global (.answer-scope), em vez de abrir/fechar div entre calls.
        st.markdown(f'<div class="answer-scope"></div>\n\n{turn.answer}', unsafe_allow_html=True)

    badge = ui.verification_badge(turn)
    if badge:
        st.markdown(badge, unsafe_allow_html=True)

    if grouped["errors"]:
        for name, res in grouped["errors"]:
            st.markdown(
                ui.notice(
                    f"<b>{ui.esc(name)}</b> retornou <code>{ui.esc(res.get('error'))}</code>. "
                    + ui.esc(res.get("message", ""))
                ),
                unsafe_allow_html=True,
            )

    if turn.tool_calls:
        with st.expander(f"Dados consultados ({len(turn.tool_calls)} chamadas)"):
            for rec in turn.tool_calls:
                st.markdown(f"**{rec.name}**  `{json.dumps(rec.arguments, ensure_ascii=False)}`")
                if rec.issues:
                    st.caption("Contrato de dados: " + " | ".join(rec.issues))
                st.json(rec.result, expanded=False)
            if turn.usage:
                custo = turn.cost_usd
                custo_txt = f" - US$ {custo:.5f}" if custo else ""
                st.caption(
                    f"{turn.model} - {turn.usage.get('total_tokens', 0)} tokens "
                    f"({turn.usage.get('prompt_tokens', 0)} entrada / "
                    f"{turn.usage.get('completion_tokens', 0)} saida) - "
                    f"{turn.usage.get('calls', 0)} chamadas de API - "
                    f"{turn.latency_s:.1f}s{custo_txt}"
                )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="side-title">Configuracao</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="side-note">Provider e modelo vem do arquivo <code>.env</code>. '
        "O provider ativo e o da chave preenchida; trocar nao exige mudanca de codigo.</div>",
        unsafe_allow_html=True,
    )

    cfg = config.describe()
    st.markdown(
        f"""
<div style="margin-top:16px">
  <div class="side-kv"><span class="k">Provider</span><span class="v">{ui.esc(cfg["provider"])}</span></div>
  <div class="side-kv"><span class="k">Modelo</span><span class="v">{ui.esc(cfg["model"])}</span></div>
  <div class="side-kv"><span class="k">{ui.esc(cfg["key_env"])}</span><span class="v">{ui.esc(cfg["key_status"])}</span></div>
  <div class="side-kv"><span class="k">Temporada</span><span class="v">{ui.esc(config.current_season())}</span></div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="side-title" style="margin-top:32px">Exemplos</div>', unsafe_allow_html=True
    )
    for i, ex in enumerate(EXAMPLES):
        if st.button(ex, key=f"ex_{i}", use_container_width=True):
            st.session_state.pending = ex
            st.rerun()

    st.markdown(
        '<div class="side-title" style="margin-top:32px">Tools</div>', unsafe_allow_html=True
    )
    st.markdown(
        '<div class="side-note">'
        + "<br>".join(f"{s['function']['name']}" for s in tool_registry.TOOL_SCHEMAS)
        + "</div>",
        unsafe_allow_html=True,
    )

    if st.session_state.turns and st.button("Limpar conversa", use_container_width=True):
        st.session_state.turns, st.session_state.history = [], []
        st.rerun()


# ---------------------------------------------------------------------------
# Corpo
# ---------------------------------------------------------------------------
st.markdown(ui.masthead(config.get_model()), unsafe_allow_html=True)

if not config.has_api_key():
    cfg = config.describe()
    st.markdown(
        ui.notice(
            f"<b>Falta a chave para o provider {ui.esc(cfg['provider'])}.</b><br>"
            f"Copie <code>.env.example</code> para <code>.env</code> e preencha "
            f"<code>{ui.esc(cfg['key_env'])}</code>. "
            "Chaves: <a href='https://openrouter.ai/keys' style='color:var(--clay)'>openrouter.ai/keys</a> "
            "ou <a href='https://platform.openai.com/api-keys' style='color:var(--clay)'>platform.openai.com/api-keys</a>."
        ),
        unsafe_allow_html=True,
    )

for past in st.session_state.turns:
    render_turn(past["question"], past["turn"])

question = st.chat_input("Pergunte sobre um jogador, uma temporada ou uma comparacao de estilo")
if st.session_state.pending:
    question, st.session_state.pending = st.session_state.pending, None

if question:
    st.markdown(ui.user_message(question), unsafe_allow_html=True)
    status = st.empty()

    def on_event(kind: str, payload: dict) -> None:
        if kind == "thinking":
            status.markdown(
                '<div class="side-note">Consultando o modelo...</div>', unsafe_allow_html=True
            )
        elif kind == "tool_start":
            status.markdown(
                f'<div class="side-note">Buscando dados: {ui.esc(payload["name"])}...</div>',
                unsafe_allow_html=True,
            )
        elif kind == "verifying":
            status.markdown(
                '<div class="side-note">Conferindo os numeros da resposta contra as '
                "tools...</div>",
                unsafe_allow_html=True,
            )
        elif kind == "correcting":
            status.markdown(
                f'<div class="side-note">Verificacao reprovou {len(payload.get("unverified", []))} '
                f"numero(s); pedindo correcao ao modelo...</div>",
                unsafe_allow_html=True,
            )

    turn = agent.run_agent(question, history=st.session_state.history, on_event=on_event)
    status.empty()

    if not turn.error:
        # Guarda apenas o par pergunta/resposta: reenviar as tools infla o contexto.
        st.session_state.history += [
            {"role": "user", "content": question},
            {"role": "assistant", "content": turn.answer},
        ]
    st.session_state.turns.append({"question": question, "turn": turn})
    st.rerun()
