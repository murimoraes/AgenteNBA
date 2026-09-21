"""
Camada de apresentacao: CSS e componentes HTML do app.

Diretrizes do design:
  - Paleta: dois acentos (laranja de quadra, verde-petroleo) sobre neutros quentes.
    Nada de gradiente roxo/azul, nada de glassmorphism.
  - Tipografia: serifa editorial (Newsreader) para titulos, Inter para dados e
    texto corrido, com escala de tamanho/peso explicita.
  - Espacamento em grid de 8px, aplicado via tokens --space-*.
  - Sem emoji: hierarquia feita com regra, peso e escala.
"""

from __future__ import annotations

import html

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400&display=swap');

:root {
  /* Neutros quentes */
  --paper:      #FBFAF8;
  --paper-2:    #F4F1EC;
  --ink:        #14131A;
  --ink-soft:   #3D3A42;
  --muted:      #6F6B63;
  --rule:       #E3DFD8;

  /* Acentos: apenas dois */
  --clay:       #BF4417;   /* laranja de quadra */
  --clay-tint:  #F6E7DF;
  --pine:       #17383A;   /* verde-petroleo */
  --pine-tint:  #E2ECEA;

  /* Grid de 8px */
  --space-1: 4px;  --space-2: 8px;  --space-3: 16px;
  --space-4: 24px; --space-5: 32px; --space-6: 48px;

  --radius: 3px;
}

html, body, [class*="st-"], .stMarkdown, p, li, div { font-family: 'Inter', system-ui, sans-serif; }

/* O seletor acima e amplo de proposito, mas nao pode alcancar os icones do
   Streamlit: eles sao ligaduras de fonte e, sem a familia certa, o nome do icone
   aparece como texto ("keyboard_double_arrow_left"). */
[data-testid="stIconMaterial"],
.material-symbols-rounded,
[class*="material-symbols"],
span[translate="no"] {
  font-family: 'Material Symbols Rounded', 'Material Symbols Outlined' !important;
}

.stApp { background: var(--paper); }
.block-container { padding-top: var(--space-5) !important; max-width: 1080px; }
#MainMenu, footer, header [data-testid="stStatusWidget"] { visibility: hidden; }

/* ---------------- Tipografia ---------------- */
.masthead {
  display: flex; align-items: flex-end; justify-content: space-between;
  gap: var(--space-4);
  border-bottom: 2px solid var(--ink);
  padding-bottom: var(--space-3); margin-bottom: var(--space-2);
}
.masthead h1 {
  font-family: 'Newsreader', Georgia, serif;
  font-size: 40px; font-weight: 400; line-height: 1.05;
  letter-spacing: -0.015em; color: var(--ink); margin: 0;
}
.masthead .sub {
  font-size: 13px; font-weight: 400; color: var(--muted);
  margin-top: var(--space-2); max-width: 46ch; line-height: 1.5;
}
.masthead .model-chip {
  font-size: 11px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--pine); background: var(--pine-tint);
  border: 1px solid #CFDDDA; border-radius: var(--radius);
  padding: 5px 10px; white-space: nowrap;
}
.strapline {
  font-size: 11px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--muted); margin-bottom: var(--space-5);
}
.eyebrow {
  font-size: 11px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--muted); margin: 0 0 var(--space-2) 0;
}

/* ---------------- Cartao do jogador ---------------- */
.player-card {
  display: grid; grid-template-columns: 164px 1fr; gap: var(--space-4);
  border: 1px solid var(--rule); border-left: 3px solid var(--clay);
  background: #FFFFFF; padding: var(--space-4); margin-bottom: var(--space-4);
}
.player-shot {
  /* A origem e sempre 1040x760 (mesma para todos); o recorte 4:5 aproxima o
     rosto sem introduzir variacao entre jogadores. */
  width: 164px; aspect-ratio: 4 / 5;
  object-fit: cover; object-position: center 8%;
  background: var(--paper-2); border: 1px solid var(--rule); border-radius: var(--radius);
  display: block;
}
.player-shot--mono {
  display: flex; align-items: center; justify-content: center;
  font-family: 'Newsreader', Georgia, serif; font-size: 44px; font-weight: 500;
  color: var(--clay); background: var(--clay-tint); border-color: #EBD6C9;
}
.player-name {
  font-family: 'Newsreader', Georgia, serif;
  font-size: 30px; font-weight: 500; line-height: 1.1; color: var(--ink);
  margin: 0 0 var(--space-2) 0;
}
.player-meta { font-size: 13px; color: var(--muted); line-height: 1.6; margin-bottom: var(--space-3); }
.player-meta strong { color: var(--ink-soft); font-weight: 600; }
.no-photo-note {
  font-size: 11px; color: var(--muted); margin-top: var(--space-2);
  padding-left: 2px; letter-spacing: 0.02em;
}

/* ---------------- Grade de estatisticas ---------------- */
.stat-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(84px, 1fr));
  gap: var(--space-1) var(--space-3);
  border-top: 1px solid var(--rule); padding-top: var(--space-3);
}
.stat { padding: var(--space-1) 0; }
.stat .v {
  font-size: 26px; font-weight: 600; line-height: 1.15; color: var(--ink);
  font-variant-numeric: tabular-nums; letter-spacing: -0.02em;
}
.stat .k {
  font-size: 10px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--muted); margin-top: 2px;
}

/* ---------------- Similaridade ---------------- */
.sim-panel {
  border: 1px solid var(--rule); border-left: 3px solid var(--pine);
  background: #FFFFFF; padding: var(--space-4); margin-bottom: var(--space-4);
}
.sim-head { display: flex; align-items: baseline; gap: var(--space-3); margin-bottom: var(--space-3); }
.sim-score {
  font-size: 46px; font-weight: 700; line-height: 1; color: var(--pine);
  font-variant-numeric: tabular-nums; letter-spacing: -0.03em;
}
.sim-score .unit { font-size: 16px; font-weight: 600; color: var(--muted); margin-left: 2px; }
.sim-label { font-size: 13px; color: var(--muted); line-height: 1.5; }
.sim-label b { color: var(--ink); font-weight: 600; }

.sim-row {
  display: grid; grid-template-columns: 190px 1fr 62px;
  align-items: center; gap: var(--space-3);
  padding: 7px 0; border-top: 1px solid var(--paper-2);
}
.sim-row .name { font-size: 13px; font-weight: 500; color: var(--ink-soft); }
.sim-row .num  { font-size: 13px; font-weight: 600; color: var(--ink); text-align: right; font-variant-numeric: tabular-nums; }
.bar-track { height: 6px; background: var(--paper-2); border-radius: 999px; overflow: hidden; }
.bar-fill  { height: 100%; background: var(--pine); border-radius: 999px; }
.bar-fill--clay { background: var(--clay); }

/* barra divergente para comparar dois jogadores numa feature */
.cmp-row {
  display: grid; grid-template-columns: 180px 1fr; gap: var(--space-3);
  align-items: center; padding: 9px 0; border-top: 1px solid var(--paper-2);
}
.cmp-label { font-size: 12px; color: var(--ink-soft); font-weight: 500; }
.cmp-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 2px; }
.cmp-side { display: flex; align-items: center; gap: var(--space-2); }
.cmp-side.left  { flex-direction: row-reverse; }
.cmp-side .v { font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; min-width: 52px; }
.cmp-side.left .v  { text-align: left;  color: var(--clay); }
.cmp-side.right .v { text-align: right; color: var(--pine); }
.cmp-bar { height: 5px; border-radius: 999px; flex: 1; }
.cmp-bar.left  { background: var(--clay); }
.cmp-bar.right { background: var(--pine); }
.cmp-rail { flex: 1; height: 5px; background: var(--paper-2); border-radius: 999px; }

.legend { display: flex; gap: var(--space-4); font-size: 11px; color: var(--muted); margin-bottom: var(--space-2); }
.legend span { display: flex; align-items: center; gap: 6px; }
.dot { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
.dot.clay { background: var(--clay); } .dot.pine { background: var(--pine); }

/* ---------------- Mensagens ---------------- */
.msg-user {
  border-left: 3px solid var(--ink); padding: var(--space-1) 0 var(--space-1) var(--space-3);
  margin: var(--space-5) 0 var(--space-4) 0;
}
.msg-user .q {
  font-family: 'Newsreader', Georgia, serif; font-size: 21px; font-weight: 400;
  line-height: 1.35; color: var(--ink);
}
/* O texto do modelo e renderizado pelo markdown do Streamlit; a classe abaixo
   viaja junto no mesmo bloco e estiliza os irmaos dentro do container. */
.answer-scope { display: none; }
.stMarkdown:has(.answer-scope) p,
.stMarkdown:has(.answer-scope) li {
  font-size: 15px; line-height: 1.7; color: var(--ink-soft);
}
.stMarkdown:has(.answer-scope) p { margin-bottom: var(--space-3); }
.stMarkdown:has(.answer-scope) strong { color: var(--ink); font-weight: 600; }
.stMarkdown:has(.answer-scope) h2,
.stMarkdown:has(.answer-scope) h3 {
  font-family: 'Newsreader', Georgia, serif; font-weight: 500; color: var(--ink);
  font-size: 20px; margin: var(--space-4) 0 var(--space-2) 0;
}
.stMarkdown:has(.answer-scope) ul { margin: 0 0 var(--space-3) 0; padding-left: 20px; }
.stMarkdown:has(.answer-scope) li { margin-bottom: var(--space-1); }

/* ---------------- Tabela ---------------- */
.log-table { width: 100%; border-collapse: collapse; margin-bottom: var(--space-4); }
.log-table th {
  font-size: 10px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--muted); text-align: right; padding: 0 var(--space-2) var(--space-2) var(--space-2);
  border-bottom: 1px solid var(--ink);
}
.log-table th:first-child, .log-table td:first-child { text-align: left; padding-left: 0; }
.log-table td {
  font-size: 13px; color: var(--ink-soft); text-align: right;
  padding: 9px var(--space-2); border-bottom: 1px solid var(--rule);
  font-variant-numeric: tabular-nums;
}
.log-table td.pts { font-weight: 600; color: var(--ink); }
.wl { font-size: 10px; font-weight: 700; letter-spacing: 0.04em; }
.wl.w { color: var(--pine); } .wl.l { color: var(--muted); }

/* ---------------- Sidebar ---------------- */
[data-testid="stSidebar"] { background: var(--paper-2); border-right: 1px solid var(--rule); }
[data-testid="stSidebar"] .block-container { padding-top: var(--space-4); }
.side-title {
  font-family: 'Newsreader', Georgia, serif; font-size: 19px; font-weight: 500;
  color: var(--ink); margin-bottom: var(--space-1);
}
.side-note { font-size: 12px; color: var(--muted); line-height: 1.55; }
.side-kv {
  display: flex; justify-content: space-between; gap: var(--space-2);
  font-size: 12px; padding: 7px 0; border-bottom: 1px solid var(--rule);
}
.side-kv .k { color: var(--muted); }
.side-kv .v { color: var(--ink); font-weight: 600; text-align: right; word-break: break-all; }

/* ---------------- Avisos ---------------- */
.notice {
  border: 1px solid var(--rule); border-left: 3px solid var(--clay);
  background: #FFFFFF; padding: var(--space-3) var(--space-4);
  font-size: 13px; line-height: 1.6; color: var(--ink-soft); margin-bottom: var(--space-4);
}
.notice b { color: var(--ink); }
.notice code {
  background: var(--paper-2); padding: 1px 5px; border-radius: var(--radius);
  font-size: 12px; color: var(--clay);
}

.stChatInput textarea { font-size: 15px !important; }
.source-note {
  font-size: 11px; color: var(--muted); letter-spacing: 0.02em;
  border-top: 1px solid var(--rule); padding-top: var(--space-2); margin-top: var(--space-2);
}
</style>
"""


def esc(v) -> str:
    return html.escape(str(v)) if v is not None else ""


def _fmt(v, digits: int = 1, dash: str = "--") -> str:
    if v is None:
        return dash
    try:
        f = float(v)
    except (TypeError, ValueError):
        return esc(v)
    return f"{f:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{f:.0f}"


def _z_width(z: float) -> float:
    """z-score (-4 a +4) -> largura percentual da barra. Media da liga = 50%."""
    try:
        z = float(z)
    except (TypeError, ValueError):
        z = 0.0
    return max(2.0, min(100.0, (z + 4.0) / 8.0 * 100.0))


def _pct(v) -> str:
    if v is None:
        return "--"
    try:
        return f"{float(v) * 100:.1f}%"
    except (TypeError, ValueError):
        return "--"


# ---------------------------------------------------------------------------
# Componentes
# ---------------------------------------------------------------------------
def masthead(model: str) -> str:
    return f"""
<div class="masthead">
  <div>
    <h1>Scouting Report</h1>
    <div class="sub">Analise de jogadores da NBA a partir de dados oficiais.
    Todo numero exibido vem de uma consulta real; o modelo apenas interpreta.</div>
  </div>
  <div class="model-chip">{esc(model)}</div>
</div>
<div class="strapline">Temporada regular &middot; dados NBA Stats</div>
"""


def player_card(image: dict | None, bio: dict | None, stats: dict | None) -> str:
    """Foto padronizada + identificacao + estatisticas-chave da temporada."""
    name = (
        (stats or {}).get("player")
        or (bio or {}).get("player")
        or (image or {}).get("player")
        or "Jogador"
    )

    if image and image.get("has_official_photo"):
        shot = f'<img class="player-shot" src="{esc(image["image_url"])}" alt="{esc(name)}">'
        note = ""
    else:
        initials = (image or {}).get("fallback", {}).get("initials") or "".join(
            p[0] for p in str(name).split()[:2]
        ).upper()
        shot = f'<div class="player-shot player-shot--mono">{esc(initials)}</div>'
        note = '<div class="no-photo-note">Sem foto oficial no CDN da NBA</div>'

    meta_bits = []
    if bio:
        if bio.get("position"):
            meta_bits.append(f"<strong>{esc(bio['position'])}</strong>")
        phys = " / ".join(
            x for x in [bio.get("height"), f"{bio['weight_lbs']} lb" if bio.get("weight_lbs") else None] if x
        )
        if phys:
            meta_bits.append(esc(phys))
        if bio.get("team"):
            meta_bits.append(esc(bio["team"]))
        if (bio.get("draft") or {}).get("year") and bio["draft"]["year"] != "Undrafted":
            d = bio["draft"]
            meta_bits.append(f"Draft {esc(d['year'])}, pick {esc(d.get('number'))}")
        if bio.get("country"):
            meta_bits.append(esc(bio["country"]))
    elif stats and stats.get("team"):
        meta_bits.append(esc(stats["team"]))

    grid = ""
    if stats and not stats.get("error"):
        pg, sh = stats.get("per_game", {}), stats.get("shooting", {})
        cells = [
            (_fmt(pg.get("points")), "PTS"),
            (_fmt(pg.get("rebounds")), "REB"),
            (_fmt(pg.get("assists")), "AST"),
            (_fmt(pg.get("minutes")), "MIN"),
            (_pct(sh.get("fg_pct")), "FG%"),
            (_pct(sh.get("fg3_pct")), "3P%"),
            (_pct(sh.get("true_shooting_pct")), "TS%"),
            (str(stats.get("games_played", "--")), "JOGOS"),
        ]
        grid = (
            '<div class="stat-grid">'
            + "".join(f'<div class="stat"><div class="v">{v}</div><div class="k">{k}</div></div>' for v, k in cells)
            + "</div>"
            + f'<div class="source-note">Temporada {esc(stats.get("season"))} &middot; medias calculadas a partir dos totais oficiais</div>'
        )

    return f"""
<div class="player-card">
  <div>{shot}{note}</div>
  <div>
    <div class="player-name">{esc(name)}</div>
    <div class="player-meta">{" &middot; ".join(meta_bits) if meta_bits else ""}</div>
    {grid}
  </div>
</div>
"""


def similar_panel(payload: dict) -> str:
    """mode='similar': ranking dos estilos mais proximos."""
    rows = payload.get("most_similar") or []
    if not rows:
        return ""
    aviso = ""
    if payload.get("isolated"):
        aviso = (" <b>Sem analogo proximo:</b> ate o mais parecido esta longe; "
                 "leia a lista como &quot;os menos diferentes&quot;.")
    worst = max((r["distance"] for r in rows), default=1.0) * 1.15
    body = ""
    for r in rows:
        width = max(6.0, 100.0 * (1 - (r["distance"] / worst))) if worst else 6.0
        team = f' <span style="color:var(--muted)">{esc(r["team"])}</span>' if r.get("team") else ""
        body += f"""
<div class="sim-row">
  <div class="name">{esc(r["name"])}{team}</div>
  <div class="bar-track"><div class="bar-fill" style="width:{width:.1f}%"></div></div>
  <div class="num">{r["resemblance"]:.1f}</div>
</div>"""
    return f"""
<div class="sim-panel">
  <div class="eyebrow">Estilo mais proximo &middot; {esc(payload.get("season"))}</div>
  <div class="sim-head">
    <div class="sim-label">Vizinhos de <b>{esc(payload.get("player"))}</b> no espaco de estilo.
    Semelhanca 0-100 = percentual dos pares da liga mais distantes que esta dupla;
    50 equivale a dois jogadores quaisquer.{aviso}</div>
  </div>
  {body}
  <div class="source-note">{esc(payload.get("method"))}</div>
</div>
"""


def pair_panel(payload: dict) -> str:
    """mode='pair': score + barras divergentes das features mais/menos distantes."""
    players = payload.get("players", {})
    a, b = players.get("a", {}), players.get("b", {})
    feats = (payload.get("biggest_differences") or [])[:3] + (payload.get("closest_features") or [])[:3]

    rows = ""
    for f in feats:
        za, zb = f.get("z_a") or 0.0, f.get("z_b") or 0.0
        # z em [-4, 4] -> largura em [2, 100]%. Barra maior = faz mais daquilo.
        # (Usar |z| deixaria "muito abaixo da media" com barra longa, o que engana.)
        wa, wb = _z_width(za), _z_width(zb)
        rows += f"""
<div class="cmp-row">
  <div class="cmp-label">{esc(f["label"])}</div>
  <div class="cmp-pair">
    <div class="cmp-side left"><div class="cmp-rail"><div class="cmp-bar left" style="width:{wa:.0f}%;margin-left:auto"></div></div><div class="v">{_fmt(f.get("a"), 2)}</div></div>
    <div class="cmp-side right"><div class="cmp-rail"><div class="cmp-bar right" style="width:{wb:.0f}%"></div></div><div class="v">{_fmt(f.get("b"), 2)}</div></div>
  </div>
</div>"""

    return f"""
<div class="sim-panel">
  <div class="eyebrow">Similaridade de estilo &middot; {esc(payload.get("season"))}</div>
  <div class="sim-head">
    <div class="sim-score">{payload.get("resemblance", 0):.1f}<span class="unit">/100</span></div>
    <div class="sim-label"><b>{esc(a.get("name"))}</b> ({esc(a.get("season"))}) x <b>{esc(b.get("name"))}</b> ({esc(b.get("season"))})<br>
    Cosseno {payload.get("cosine_similarity", 0):.3f} &middot; distancia {payload.get("distance", 0):.2f} &middot; {payload.get("features_used", 0)} de {payload.get("features_total", 0)} indicadores.
    50 = tao parecidos quanto dois jogadores quaisquer da liga.</div>
  </div>
  <div class="legend">
    <span><i class="dot clay"></i>{esc(a.get("name"))}</span>
    <span><i class="dot pine"></i>{esc(b.get("name"))}</span>
    <span>Barra pela metade = media da liga &middot; barra maior = faz mais daquilo</span>
  </div>
  {rows}
  <div class="source-note">{esc(payload.get("method"))}</div>
</div>
"""


def games_table(payload: dict) -> str:
    games = payload.get("games") or []
    if not games:
        return ""
    avg = payload.get("averages_over_span", {})
    rec = payload.get("record_over_span", {})
    body = ""
    for g in games:
        wl = str(g.get("result") or "").lower()
        body += f"""
<tr>
  <td>{esc(g["date"])}</td>
  <td style="text-align:left">{esc(g["matchup"])}</td>
  <td><span class="wl {wl}">{esc(g.get("result"))}</span></td>
  <td>{_fmt(g.get("minutes"), 0)}</td>
  <td class="pts">{esc(g["points"])}</td>
  <td>{esc(g["rebounds"])}</td>
  <td>{esc(g["assists"])}</td>
  <td>{esc(g["fg"])}</td>
  <td>{esc(g["fg3"])}</td>
</tr>"""
    return f"""
<div class="eyebrow">Ultimos {len(games)} jogos &middot; {esc(payload.get("player"))} &middot; {esc(payload.get("season"))}</div>
<table class="log-table">
  <thead><tr>
    <th>Data</th><th style="text-align:left">Confronto</th><th>R</th>
    <th>MIN</th><th>PTS</th><th>REB</th><th>AST</th><th>FG</th><th>3P</th>
  </tr></thead>
  <tbody>{body}</tbody>
</table>
<div class="source-note">Media do recorte: {_fmt(avg.get("points"))} pts &middot; {_fmt(avg.get("rebounds"))} reb &middot; {_fmt(avg.get("assists"))} ast &middot; campanha {rec.get("wins", 0)}-{rec.get("losses", 0)}</div>
"""


def user_message(text: str) -> str:
    return f'<div class="msg-user"><div class="q">{esc(text)}</div></div>'


def notice(html_text: str) -> str:
    return f'<div class="notice">{html_text}</div>'
