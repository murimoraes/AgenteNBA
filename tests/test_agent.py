"""
Testes do loop do agente.

Nenhuma chamada real de API: um client falso devolve respostas no formato da
OpenAI. Isso permite testar exatamente os caminhos que sao dificeis de
reproduzir com a API de verdade -- tool inexistente, erro do provider, resposta
sem `choices`, estouro de iteracoes e o ciclo de correcao do fact checker.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import agent
import config
from validation import facts


# ---------------------------------------------------------------------------
# Client falso no formato OpenAI
# ---------------------------------------------------------------------------
def _msg(content="", tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls or [])


def _tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def _response(message, usage=(100, 50)):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(
            prompt_tokens=usage[0], completion_tokens=usage[1],
            total_tokens=sum(usage),
        ),
    )


class FakeClient:
    """Devolve as respostas na ordem dada e registra o que recebeu."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        # O agente reaproveita e muta a mesma lista de mensagens entre rodadas,
        # entao o registro precisa ser um retrato do momento da chamada.
        self.requests.append({**kwargs, "messages": list(kwargs.get("messages", []))})
        if not self._responses:
            raise AssertionError("o agente pediu mais respostas do que o teste previu")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


@pytest.fixture
def fake_client(monkeypatch):
    def install(responses):
        client = FakeClient(responses)
        monkeypatch.setattr(config, "get_client", lambda: client)
        monkeypatch.setattr(config, "get_model", lambda: "gpt-4o-mini")
        return client

    return install


@pytest.fixture(autouse=True)
def sem_download_de_imagem(monkeypatch):
    """_ensure_images sairia para a rede; aqui a foto nunca importa."""
    monkeypatch.setattr(agent, "_ensure_images", lambda records: [])


# ---------------------------------------------------------------------------
# Escopo: recusa antes de gastar API
# ---------------------------------------------------------------------------
def test_pergunta_fora_de_escopo_nao_chama_a_api(fake_client):
    client = fake_client([])
    turn = agent.run_agent("Qual a capital da Franca?")

    assert turn.refused_scope
    assert client.requests == []          # zero chamadas de API
    assert turn.usage == {}
    assert "NBA" in turn.answer
    assert turn.error is None


def test_pergunta_de_nba_segue_o_fluxo_normal(fake_client):
    fake_client([_response(_msg("Resposta sem numeros."))])
    turn = agent.run_agent("Como foi a temporada do Jokic?")

    assert not turn.refused_scope
    assert turn.answer == "Resposta sem numeros."


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
def test_tool_desconhecida_vira_erro_estruturado(fake_client, monkeypatch):
    client = fake_client([
        _response(_msg(tool_calls=[_tool_call("c1", "get_salary", {"player_name": "LeBron"})])),
        _response(_msg("Nao tenho esse dado.")),
    ])
    turn = agent.run_agent("Como foi a temporada do Jokic?")

    assert turn.tool_calls[0].result["error"] == "unknown_tool"
    # O modelo precisa receber o erro para poder relatar em vez de inventar.
    tool_msg = [m for m in client.requests[-1]["messages"] if m.get("role") == "tool"][0]
    assert "unknown_tool" in tool_msg["content"]


def test_argumento_invalido_e_barrado_antes_da_tool_rodar(fake_client, monkeypatch):
    chamou = []
    monkeypatch.setitem(
        agent.tool_registry.TOOL_FUNCTIONS,
        "get_player_season_stats",
        lambda **kw: chamou.append(kw) or {"player": "x"},
    )
    fake_client([
        _response(_msg(tool_calls=[
            _tool_call("c1", "get_player_season_stats", {"season": "2024-25"})  # sem player_name
        ])),
        _response(_msg("Preciso do nome do jogador.")),
    ])
    turn = agent.run_agent("Como foi a temporada dele?", history=[{"role": "user", "content": "x"}])

    assert turn.tool_calls[0].result["error"] == "invalid_arguments"
    assert chamou == []  # a funcao nao chegou a rodar


def test_excecao_na_tool_nao_derruba_o_turno(fake_client, monkeypatch):
    def explode(**kwargs):
        raise RuntimeError("API da NBA fora do ar")

    monkeypatch.setitem(agent.tool_registry.TOOL_FUNCTIONS, "get_player_bio", explode)
    fake_client([
        _response(_msg(tool_calls=[_tool_call("c1", "get_player_bio", {"player_name": "Jokic"})])),
        _response(_msg("A consulta falhou.")),
    ])
    turn = agent.run_agent("Qual a posicao do Jokic?")

    assert turn.tool_calls[0].result["error"] == "tool_failed"
    assert "RuntimeError" in turn.tool_calls[0].result["detail"]
    assert turn.error is None


def test_violacao_de_contrato_e_registrada(fake_client, monkeypatch):
    monkeypatch.setitem(
        agent.tool_registry.TOOL_FUNCTIONS,
        "get_player_season_stats",
        lambda **kw: {
            "player": "Jokic", "player_id": 203999, "season": "2024-25",
            "games_played": 70, "per_game": {"points": 29.6},
            "shooting": {"fg_pct": 57.6},  # deveria ser fracao
        },
    )
    fake_client([
        _response(_msg(tool_calls=[
            _tool_call("c1", "get_player_season_stats", {"player_name": "Jokic"})
        ])),
        _response(_msg("Media de 29.6 pontos.")),
    ])
    turn = agent.run_agent("Quantos pontos o Jokic fez?")

    assert any("fracao entre 0 e 1" in issue for issue in turn.contract_issues)


def test_json_de_argumentos_quebrado_nao_estoura(fake_client):
    call = SimpleNamespace(
        id="c1",
        function=SimpleNamespace(name="get_player_bio", arguments="{nao e json"),
    )
    fake_client([
        _response(_msg(tool_calls=[call])),
        _response(_msg("Nao consegui.")),
    ])
    turn = agent.run_agent("Qual a posicao do Jokic?")
    assert turn.tool_calls[0].result["error"] == "invalid_arguments"


# ---------------------------------------------------------------------------
# Verificacao factual dentro do loop
# ---------------------------------------------------------------------------
def _stats_tool(monkeypatch, payload):
    monkeypatch.setitem(
        agent.tool_registry.TOOL_FUNCTIONS, "get_player_season_stats", lambda **kw: payload
    )


def test_numero_inventado_dispara_pedido_de_correcao(fake_client, monkeypatch, season_stats_payload):
    _stats_tool(monkeypatch, season_stats_payload)
    client = fake_client([
        _response(_msg(tool_calls=[
            _tool_call("c1", "get_player_season_stats", {"player_name": "Jokic"})
        ])),
        _response(_msg("Jokic fez 33.1 pontos por jogo.")),   # inventado
        _response(_msg("Jokic fez 29.6 pontos por jogo.")),   # corrigido
    ])
    turn = agent.run_agent("Quantos pontos o Jokic fez em 2024-25?")

    assert turn.corrections == 1
    assert turn.answer == "Jokic fez 29.6 pontos por jogo."
    assert turn.fact_check.ok
    assert turn.verified

    # A mensagem de correcao precisa apontar o numero exato que reprovou.
    correcao = client.requests[-1]["messages"][-1]
    assert correcao["role"] == "user"
    assert "33.1" in correcao["content"]


def test_correcao_nao_e_infinita(fake_client, monkeypatch, season_stats_payload):
    _stats_tool(monkeypatch, season_stats_payload)
    fake_client([
        _response(_msg(tool_calls=[
            _tool_call("c1", "get_player_season_stats", {"player_name": "Jokic"})
        ])),
        _response(_msg("Jokic fez 33.1 pontos.")),
        _response(_msg("Jokic fez 33.1 pontos mesmo.")),
    ])
    turn = agent.run_agent("Quantos pontos o Jokic fez?", max_corrections=1)

    assert turn.corrections == 1
    assert not turn.fact_check.ok       # entrega assumindo a pendencia
    assert not turn.verified            # e a UI avisa o usuario
    assert turn.answer                  # sem apagar o texto do modelo


def test_verificacao_pode_ser_desligada(fake_client, monkeypatch, season_stats_payload):
    _stats_tool(monkeypatch, season_stats_payload)
    fake_client([
        _response(_msg(tool_calls=[
            _tool_call("c1", "get_player_season_stats", {"player_name": "Jokic"})
        ])),
        _response(_msg("Jokic fez 33.1 pontos.")),
    ])
    turn = agent.run_agent("Quantos pontos o Jokic fez?", verify=False)

    assert turn.fact_check is None
    assert turn.corrections == 0


def test_resposta_correta_nao_gasta_chamada_extra(fake_client, monkeypatch, season_stats_payload):
    _stats_tool(monkeypatch, season_stats_payload)
    client = fake_client([
        _response(_msg(tool_calls=[
            _tool_call("c1", "get_player_season_stats", {"player_name": "Jokic"})
        ])),
        _response(_msg("Em 2024-25, Jokic fez 29.6 pontos e 12.7 rebotes.")),
    ])
    turn = agent.run_agent("Quantos pontos o Jokic fez em 2024-25?")

    assert turn.corrections == 0
    assert len(client.requests) == 2
    assert turn.verified


# ---------------------------------------------------------------------------
# Erros de provider
# ---------------------------------------------------------------------------
def test_resposta_sem_choices_vira_erro_legivel(fake_client):
    resposta = SimpleNamespace(choices=None, usage=None)
    resposta.model_dump = lambda: {
        "error": {"message": "Rate limit exceeded", "code": 429,
                  "metadata": {"provider_name": "OpenRouter"}}
    }
    fake_client([resposta])
    turn = agent.run_agent("Como foi a temporada do Jokic?")

    assert turn.error
    assert "Rate limit exceeded" in turn.error


def test_excecao_do_provider_vira_erro_legivel(fake_client):
    fake_client([ConnectionError("conexao caiu")])
    turn = agent.run_agent("Como foi a temporada do Jokic?")

    assert turn.error
    assert "conexao caiu" in turn.error
    assert turn.answer == ""


def test_sem_api_key_nao_quebra(monkeypatch):
    monkeypatch.setattr(
        config, "get_client",
        lambda: (_ for _ in ()).throw(config.ConfigError("OPENAI_API_KEY nao encontrada")),
    )
    turn = agent.run_agent("Como foi a temporada do Jokic?")
    assert "OPENAI_API_KEY" in turn.error


def test_estouro_de_iteracoes(fake_client, monkeypatch, season_stats_payload):
    _stats_tool(monkeypatch, season_stats_payload)
    sempre_tool = _response(_msg(tool_calls=[
        _tool_call("c1", "get_player_season_stats", {"player_name": "Jokic"})
    ]))
    fake_client([sempre_tool] * agent.MAX_ITERATIONS)
    turn = agent.run_agent("Como foi a temporada do Jokic?")

    assert turn.error
    assert f"{agent.MAX_ITERATIONS} rodadas" in turn.error


# ---------------------------------------------------------------------------
# Historico, uso e metricas
# ---------------------------------------------------------------------------
def test_historico_anterior_e_preservado_na_ordem(fake_client):
    client = fake_client([_response(_msg("ok"))])
    history = [
        {"role": "user", "content": "quem e o Jokic?"},
        {"role": "assistant", "content": "um pivo"},
    ]
    agent.run_agent("e a temporada dele?", history=history)

    enviadas = client.requests[0]["messages"]
    assert enviadas[0]["role"] == "system"
    assert enviadas[1:3] == history
    assert enviadas[-1] == {"role": "user", "content": "e a temporada dele?"}


def test_uso_de_tokens_e_somado_entre_as_rodadas(fake_client, monkeypatch, season_stats_payload):
    _stats_tool(monkeypatch, season_stats_payload)
    fake_client([
        _response(_msg(tool_calls=[
            _tool_call("c1", "get_player_season_stats", {"player_name": "Jokic"})
        ]), usage=(100, 20)),
        _response(_msg("Em 2024-25 foram 29.6 pontos."), usage=(300, 80)),
    ])
    turn = agent.run_agent("Quantos pontos em 2024-25?")

    assert turn.usage["prompt_tokens"] == 400
    assert turn.usage["completion_tokens"] == 100
    assert turn.usage["calls"] == 2


def test_metricas_do_turno_saem_completas(fake_client, monkeypatch, season_stats_payload):
    _stats_tool(monkeypatch, season_stats_payload)
    fake_client([
        _response(_msg(tool_calls=[
            _tool_call("c1", "get_player_season_stats", {"player_name": "Jokic"})
        ])),
        _response(_msg("Em 2024-25, 29.6 pontos por jogo.")),
    ])
    turn = agent.run_agent("Quantos pontos em 2024-25?")
    m = turn.metrics()

    assert m["tool_calls"] == ["get_player_season_stats"]
    assert m["api_calls"] == 2
    assert m["verified"] is True
    assert m["cost_usd"] is not None and m["cost_usd"] > 0
    assert m["latency_s"] >= 0
    assert m["iterations"] == 2


def test_custo_de_modelo_desconhecido_e_none(fake_client, monkeypatch):
    fake_client([_response(_msg("ok"))])
    turn = agent.run_agent("Como foi a temporada do Jokic?", model="modelo-inexistente")
    assert turn.cost_usd is None
