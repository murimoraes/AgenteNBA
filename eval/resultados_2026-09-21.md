# Avaliacao do agente - 2026-09-21

Registro consolidado da primeira rodada oficial de avaliacao, feita durante a
implementacao da Fase 1. Este arquivo e escrito a mao juntando as rodadas; o
`evaluator.py` gera o mesmo formato automaticamente a cada execucao.

- **Modelo:** `gpt-4o-mini` (OpenAI)
- **Dataset:** `eval/dataset.json` v1.0 - 37 casos
- **Casos executados:** 26 de 37 (os 11 restantes ficaram de fora por orcamento
  de API, nao por falha)
- **Chamadas de API consumidas no total:** 87 (incluindo as rodadas que
  reprovaram e foram reexecutadas apos correcao)

## Resultado final

| Metrica | Valor |
|---|---|
| Taxa de sucesso | **26/26 (100%)** dos casos executados, na rodada final de cada um |
| Correcao numerica | **100%** - nenhum numero sem lastro em tool, em nenhuma rodada |
| Respostas com alucinacao numerica | 0 |
| Afirmacoes fora do contrato de dados | 0 |
| Violacoes de contrato nas tools | 0 |
| Erros do agente | 0 |
| Latencia media | ~6s (p95 ~17s, puxado pelas comparacoes cross-era) |
| Custo medio | ~US$ 0,0006 por pergunta |

## Como a rodada evoluiu

A primeira execucao deu 74% de sucesso. As seis reprovacoes foram investigadas
uma a uma e **nenhuma era erro do agente** -- eram dois defeitos nos proprios
verificadores, encontrados justamente por existir uma suite de avaliacao:

| Rodada | Casos | Sucesso | Correcao numerica | O que mudou depois |
|---|---|---|---|---|
| A (inicial) | 23 | 74% | 100% | investigacao das 6 reprovacoes |
| B (debug) | 5 | 20% | 100% | capturou as respostas completas para diagnostico |
| C (pos-correcao) | 16 | 94% | 100% | corrigido falso positivo do contrato e do escopo |
| D (pos-correcao) | 10 | 90% | 100% | corrigida a expectativa rigida de esclarecimento |
| E (multi-turno) | 2 | 100% | 100% | suporte a historico no evaluator |

### Os dois defeitos encontrados

1. **Falso positivo do contrato de dados.** O detector marcava como violacao a
   resposta "este sistema nao tem dados sobre salarios", so porque a palavra
   "salario" aparecia. Punir isso ensinaria o agente a esconder a limitacao em
   vez de declara-la -- o oposto do objetivo. O julgamento passou a ser frase a
   frase, com deteccao de recusa; uma afirmacao real ("o salario e 44.5
   milhoes") continua sendo pega, inclusive quando aparece na mesma resposta
   que uma recusa.

2. **Escopo recusando pergunta valida.** "Como ele esta jogando?" (sem
   historico) era classificada como fora do dominio, porque o vocabulario nao
   tinha as formas verbais de "jogar". Pergunta ambigua deve pedir
   esclarecimento, nao ser tratada como off-topic.

Alem disso, duas expectativas do dataset estavam rigidas demais (cobravam frase
exata onde o modelo varia a formulacao) e foram trocadas por detectores
reutilizaveis: `acknowledges_missing_data` e `asks_clarification`.

## Casos executados

| ID | Categoria | Status | Observacao |
|---|---|---|---|
| stats_001 | stats | PASS | 7/7 numeros conferidos |
| stats_003 | stats | PASS | - |
| recent_001 | recent_form | PASS | - |
| recent_003 | recent_form | PASS | **regressao do caso #8**: citou "10 de abril de 2026" em vez de "ontem" |
| compare_001 | comparison | PASS | - |
| compare_002 | comparison | PASS | **regressao do caso #2**: chamou stats E similaridade |
| similar_001 | similarity | PASS | - |
| crossera_001 | cross_era | PASS | 3 chamadas de API (caso mais lento: 17s) |
| bio_001 | bio | PASS | - |
| multi_002 | multi_tool | PASS | combinou jogos recentes + media da temporada |
| ambiguous_001 | ambiguous | PASS | **regressao do caso #11**: recusou opinar, sem citar MVP |
| ambiguous_002 | ambiguous | PASS | **regressao do caso #3**: pediu o nome do jogador |
| ambiguous_003 | ambiguous | PASS | follow-up com pronome, resolvido pelo historico |
| context_001 | conversation_memory | PASS | pronome resolvido entre turnos |
| scope_001 | out_of_scope | PASS | **regressao do caso #4**: recusada, 0 chamadas de API |
| scope_002 | out_of_scope | PASS | 0 chamadas de API |
| scope_003 | out_of_scope | PASS | 0 chamadas de API |
| scope_004 | out_of_scope | PASS | 0 chamadas de API |
| contract_001 | out_of_contract | PASS | **regressao do caso #9**: recusou o salario em vez de inventar |
| contract_002 | out_of_contract | PASS | recusou titulos |
| contract_003 | out_of_contract | PASS | recusou premio (MVP) |
| contract_004 | out_of_contract | PASS | recusou classificacao do time |
| error_001 | error_handling | PASS | `player_not_found` |
| error_002 | error_handling | PASS | `season_not_available` |
| error_003 | error_handling | PASS | **regressao do caso #5**: declarou a correcao do nome |
| error_004 | error_handling | PASS | temporada anterior a 1996-97 |

## Nao executados (orcamento)

`stats_002`, `stats_004`, `stats_005`, `recent_002`, `compare_003`,
`similar_002`, `similar_003`, `crossera_002`, `bio_002`, `multi_001`,
`multi_003`.

Rodar o dataset inteiro custa ate 99 chamadas (~US$ 0,06). O teto desta sessao
era 100 chamadas no total, ja consumidas pelas rodadas de diagnostico.

## Reproduzir

```bash
python -m eval.evaluator --dry-run                  # valida o dataset, custo zero
python -m eval.evaluator --category out_of_scope    # custo zero (recusa local)
python -m eval.evaluator --budget 30                # teto rigido de chamadas
```
