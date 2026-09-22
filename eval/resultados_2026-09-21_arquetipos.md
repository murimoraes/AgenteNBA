# Avaliacao do agente - arquetipos (2026-09-21)

Primeira rodada com o **dataset completo** e com a camada de arquetipos ativa.

- **Modelo:** `gpt-4o-mini` (OpenAI)
- **Dataset:** `eval/dataset.json` - 42 casos, 13 categorias
- **Casos executados:** 42 de 42 (rodada completa, sem corte por orcamento)
- **Chamadas de API:** 73 na rodada completa + 27 na reexecucao pos-correcao

## Resultado

| Metrica | Rodada A (completa) | Rodada B (pos-correcao) |
|---|---|---|
| Casos | 42 | 13 (os afetados) |
| Taxa de sucesso | 95% (40/42) | **100% (13/13)** |
| Correcao numerica | 99,8% | **100%** |
| Respostas usando arquetipo | -- | 11/13 (26 rotulos distintos) |
| Respostas fora do contrato | 0 | 0 |
| Violacoes de contrato nas tools | 0 | 0 |
| Erros do agente | 0 | 0 |
| Latencia p50 | ~6s | 6,2s |
| Custo | US$ 0,049 | US$ 0,023 |

Estado final: **42/42 casos passando** na ultima execucao de cada um.

## As duas falhas da rodada completa

Como na rodada anterior, a avaliacao encontrou defeitos reais -- e desta vez um
deles era uma **regressao introduzida pela propria Fase 1**.

### 1. `bio_002` -- recusa indevida (regressao da Fase 1)

Pergunta: *"Em que ano o Jokic foi draftado e por qual time?"*
Resposta: *"Este sistema nao tem dados sobre o ano do draft..."* -- **sem chamar
tool nenhuma**.

Mas `get_player_bio` **fornece** ano, rodada e numero do draft. O guardrail de
contrato de dados da Fase 1 ("nao existe tool para salario, premios, titulos...")
foi generalizado pelo modelo para dados que o sistema tem.

Esse caso nunca tinha sido executado: estava entre os 11 que ficaram de fora da
rodada anterior por orcamento. O over-refusal e o efeito colateral classico de
anti-alucinacao mal calibrada -- e so aparece quando se roda o dataset inteiro.

**Correcao:** o system prompt passou a listar explicitamente o que cada tool
fornece, com a regra "dizer 'nao tenho esse dado' sobre algo que uma tool
devolve e tao errado quanto inventar o dado".
**Depois:** *"Nikola Jokic foi draftado no ano de 2014, na segunda rodada, como a
41a escolha geral, pelo time do Denver Nuggets"* -- via `get_player_bio`.

### 2. `arch_001` -- arquetipo inalcancavel sem comparacao

Pergunta: *"Que tipo de jogador e o Rudy Gobert?"*
O modelo chamou bio + stats + imagem, **nao** `compare_players`, e respondeu
"Protetor de Aro" de memoria. O rotulo estava certo por sorte, nao por dado.

Causa: os arquetipos so existiam dentro de `compare_players`, e nao ha com quem
comparar numa pergunta sobre um jogador so.

**Correcao:** nova tool `get_player_archetypes`, que expoe o mesmo calculo
deterministico para um jogador isolado.
**Depois:** 1 chamada a `get_player_archetypes`, resposta estruturada pelas 7
categorias, sem numero inventado.

Como efeito colateral util, a resposta passou a nao ter numero algum a
verificar -- ela narra rotulos e leitura tatica, que e exatamente o registro de
um relatorio de olheiro.

## Validacao dos arquetipos contra dados reais

Fora do fluxo do LLM (custo zero de API), o classificador foi conferido contra a
liga real de 2024-25:

| Dupla | Semelhanca | Leitura dos arquetipos |
|---|---|---|
| Jokic x Gobert | 3,9 (opostos) | coincidem **so** em perfil fisico (Estrutura de Pivo Classico); divergem em arremesso, criacao, defesa, rebote e papel |
| Curry x Trae Young | 84,3 (bastante parecidos) | coincidem em criacao (Pick-and-Roll), organizacao (Combo Guard), papel (Protagonista) e fisico (Armador Compacto); divergem so no perfil de arremesso -- Curry e Arremessador de Elite, Trae e Mestre do Lance-Livre |

Os vizinhos de estilo do Wembanyama sairam como Porzingis, Anthony Davis e
Karl-Anthony Towns, cada um com as categorias em comum declaradas.

Essa ultima linha e o ganho concreto do trabalho: antes a resposta era
"semelhanca 84,3" e uma lista de deltas de z-score; agora ela diz **em que** os
dois se parecem e **onde** divergem.

## Reproduzir

```bash
python -m eval.evaluator --dry-run                    # valida, custo zero
python -m eval.evaluator --category archetypes        # so os arquetipos
python -m eval.evaluator --budget 130                 # dataset completo
```
