# Avaliacao do agente

Suite que mede o comportamento do agente end-to-end contra um dataset de casos
com expectativa declarada.

**Esta suite chama o modelo de verdade e custa dinheiro.** Ela e separada de
`tests/` justamente por isso: `tests/` roda offline, em segundos, a cada
alteracao; `eval/` roda quando se quer medir qualidade, com orcamento explicito.

## Por que existe

Sem avaliacao automatizada, mudar o system prompt, trocar de modelo ou mexer nas
tools e apostar: melhora uma dimensao e quebra outra sem ninguem perceber. Foi
exatamente o que aconteceu antes -- o README reportava que o `gpt-4o-mini`
recusava a pergunta-armadilha do salario, e um teste manual posterior pegou o
mesmo modelo inventando "US$ 44.5 milhoes".

## Uso

```bash
python -m eval.evaluator --dry-run                 # valida o dataset, nao gasta nada
python -m eval.evaluator --category out_of_scope   # custo zero: recusa e local
python -m eval.evaluator --budget 30               # teto RIGIDO de chamadas
python -m eval.evaluator --case contract_001       # um caso especifico
python -m eval.evaluator --budget 60 --out eval/resultados.md --json-out eval/r.json
```

`--budget` para a rodada **antes** de estourar o teto e informa quais casos
ficaram de fora. O consumo acumulado e impresso a cada caso.

O processo sai com codigo 0 quando tudo passa e 2 quando ha reprovacao, o que
permite usar em CI.

## Custo

Um caso tipico consome 2 chamadas (rodada de tools + sintese) e ~US$ 0,0006 com
`gpt-4o-mini`. Casos que reprovam na verificacao factual consomem uma terceira
(a correcao). Casos de escopo consomem **zero**: a recusa acontece antes da API.

Dataset completo: 37 casos, ate 99 chamadas, ~US$ 0,06.

## Estrutura

```
dataset.json   casos + expectativas
evaluator.py   runner com controle de orcamento (CLI)
metrics.py     avaliacao de caso e agregacao -- funcoes puras, testadas em tests/test_eval.py
```

## Formato de um caso

Todos os campos de `expects` sao opcionais: o que nao for declarado nao e cobrado.

```json
{
  "id": "contract_001",
  "category": "out_of_contract",
  "question": "Qual o salario do LeBron James essa temporada?",
  "origem": "relatorio (caso #9): o modelo inventou 'US$ 44.5 milhoes'",
  "history": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "expects": {
    "tools_any": ["get_player_season_stats"],
    "tools_all": ["compare_players"],
    "tools_forbidden": [],
    "no_tools": false,
    "tool_error": "player_not_found",
    "season": "2024-25",
    "no_hallucination": true,
    "refuse_scope": false,
    "acknowledges_missing_data": true,
    "asks_clarification": false,
    "answer_contains_any": ["lebron james"],
    "answer_not_contains": ["atual MVP"]
  }
}
```

`history` torna o caso multi-turno -- e assim que se testa resolucao de pronome
e memoria de conversa.

### Duas expectativas que nao sao frase fixa

`acknowledges_missing_data` e `asks_clarification` usam detectores por padrao,
nao comparacao literal. A razao veio da pratica: cobrar frase exata reprovava
resposta correta so porque o modelo escreveu "nao tem dados" em vez de "nao
tenho dados", ou "me informe o nome do jogador" em vez de "qual jogador".

## Metricas

O criterio de conclusao da Fase 1 do roadmap pede que o projeto demonstre, de
forma reproduzivel: taxa de sucesso, taxa de alucinacao, correcao numerica,
latencia e custo. Todas saem do `aggregate()`:

| Metrica | Significado |
|---|---|
| `success_rate` | casos cujas expectativas foram todas cumpridas |
| `numeric_accuracy` | numeros com lastro em tool / numeros escritos |
| `hallucination_rate_by_answer` | fracao das respostas com ao menos um numero sem lastro |
| `out_of_contract_answers` | respostas afirmando metrica que nenhuma tool fornece |
| `answers_corrected` | respostas reescritas apos reprovacao do fact checker |
| `contract_violations` | payloads de tool que violaram o contrato de dados |
| `latency_avg_s` / `p50` / `p95` | tempo por pergunta |
| `total_cost_usd` / `avg_cost_usd` | custo, via tabela de precos em `config.py` |

## Resultados

Cada rodada gera um markdown versionavel. O registro da primeira rodada oficial
esta em [resultados_2026-09-21.md](resultados_2026-09-21.md).
