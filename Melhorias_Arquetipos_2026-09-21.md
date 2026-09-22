# Camada de arquétipos — o que mudou

**Data:** 2026-09-21
**Versão:** `v2.0-confiabilidade` → `v3.0-arquetipos`
**Origem:** item 5.1 da [auditoria](AgenteNBA_Auditoria_Melhorias.md) ("Criar uma camada de domínio de scouting"), que estava em P1, e o diagnóstico de que as comparações ficavam "vastas" demais.

---

## 1. Resumo

A comparação já dizia **quanto** dois jogadores se parecem (score 0–100) e **quais** features mais os separam. Faltava o passo que um olheiro humano dá automaticamente: olhar o perfil e dizer *"esse é um armador de pick-and-roll", "aquele é um protetor de aro"*. Sem isso, "Rebote defensivo %: 0.2 × 0.11" é uma linha de planilha, não uma frase de scouting.

Agora existem **44 arquétipos em 7 categorias**, derivados por regra determinística dos mesmos z-scores que a similaridade já calculava — nenhum dado novo, nenhuma chamada ao modelo. Cada jogador recebe um arquétipo **primário** por categoria e, quando o segundo colocado está perto, também um **secundário**.

**Resultado medido:** 247 testes offline, 42/42 casos de avaliação passando, 100% de correção numérica, e 11 de 13 respostas de comparação passando a usar os rótulos de arquétipo (26 rótulos distintos).

**Claudescore: 73 → 85** na régua nova (detalhes e a re-base honesta na seção 5).

---

## 2. O que foi implementado

### 2.1 `archetypes.py` — o catálogo e o classificador

Módulo puro: não importa `similarity`, trabalha só sobre um dicionário `{feature: z-score}`. Por isso roda offline e é testável sem rede.

Dois tipos de sinal, porque um só não dava conta:

| Tipo | Regra | Para que serve |
|---|---|---|
| `signals` | quanto maior (ou menor, se peso negativo) o z, melhor | arquétipos de **extremo**: "Protetor de Aro" quer tocos alto |
| `bands` | quanto mais perto de um alvo, melhor | arquétipos de **meio**, que sinal linear nunca elegeria: "Coadjuvante de Luxo" é uso *acima* da média mas longe de protagonista |

O encaixe de cada sinal vira uma satisfação em [-1, 1] e o score é a média ponderada — o que torna arquétipos com números diferentes de sinais comparáveis entre si.

**Categorias e contagem:** perfil de arremesso (7), criação (7), organização (6), defesa (7), rebote (5), papel na equipe (6), perfil físico (6).

O rebote tem só 5 porque a camada de dados oferece apenas `OREB_PCT` e `DREB_PCT` — preferi 5 arquétipos sustentados a 7 com dois inventados.

### 2.2 Três decisões que evitam rótulo vazio

1. **Piso de confiança.** Abaixo de 0.30 nenhum rótulo é atribuído: a resposta é *"perfil equilibrado nesta categoria"*. Entregar o menos ruim seria pior que admitir que não há destaque.
2. **Secundário só quando está perto.** Margem de 0.15. Forçar sempre um segundo rótulo transformaria ruído em afirmação.
3. **Corte de cobertura por era.** Um arquétipo só concorre se 60% do seu peso estiver disponível na temporada. "Criador Pull-Up" sem a feature de pull-up (pré-2013-14) não é uma classificação fraca — é uma classificação sem sentido, então ele sai da disputa.

### 2.3 Integração

- **`similarity.compare()`** passa a devolver `archetypes_a`, `archetypes_b` e `archetype_comparison` (o que os dois compartilham e onde divergem).
- **`most_similar()`** anexa o arquétipo de cada vizinho e as categorias em comum com o alvo — a lista deixa de ser nome + número.
- **`get_player_archetypes`** (tool nova): expõe o mesmo cálculo para um jogador isolado. Criada porque a avaliação mostrou a lacuna — ver seção 4.
- **Interface:** tabela categoria a categoria com primário e "também:" secundário, e a linha destacada em verde onde os dois caem no mesmo arquétipo. Painel avulso com chips para a tool individual.
- **System prompt:** instruído a começar a resposta pelo arquétipo e usar os rótulos exatamente como vierem — arquétipo é rótulo de regra determinística, não opinião do modelo.

---

## 3. Evidência

### Testes
```
247 passed in 9.38s
```
Sendo 30 novos em `tests/test_archetypes.py`, divididos em dois grupos:
- **invariantes** — escala do score, catálogo coerente, secundário nunca acima do primário, jogador médio não recebe rótulo forçado;
- **reconhecimento** — perfis sintéticos de z-score construídos para representar estilos conhecidos (armador arremessador, pivô protetor, 3&D, pivô passador). É o que impede os pesos de virarem números arbitrários: mexer neles quebra o reconhecimento e o teste acusa.

### Validação contra a liga real (2024-25)

| Dupla | Semelhança | O que os arquétipos revelaram |
|---|---|---|
| Jokić × Gobert | 3,9 (opostos) | coincidem **só** no físico (Estrutura de Pivô Clássico); divergem em arremesso, criação, defesa, rebote e papel |
| Curry × Trae Young | 84,3 | coincidem em criação, organização, papel e físico; divergem **só** no perfil de arremesso — Curry é Arremessador de Elite, Trae é Mestre do Lance-Livre |

A segunda linha é o tipo de leitura que não existia antes: dois armadores altamente parecidos, e a diferença real está em *como* pontuam (bola de três × linha de lance livre). Os vizinhos do Wembanyama saíram Porziņģis, Davis e Towns, cada um com as categorias em comum declaradas.

### Avaliação end-to-end
42/42 casos passando. Registro completo em [eval/resultados_2026-09-21_arquetipos.md](eval/resultados_2026-09-21_arquetipos.md).

---

## 4. A avaliação encontrou uma regressão da Fase 1

Vale registrar, porque é o segundo ciclo em que a suíte se paga:

**`bio_002` — "Em que ano o Jokić foi draftado?"** → o agente respondeu *"este sistema não tem dados sobre o ano do draft"*, **sem chamar tool nenhuma**. Mas `get_player_bio` fornece ano, rodada e número do draft.

O guardrail de contrato de dados que implementei na Fase 1 ("não existe tool para salário, prêmios, títulos…") foi **generalizado pelo modelo** para dados que o sistema tem. É o efeito colateral clássico de anti-alucinação mal calibrada: o agente troca inventar por recusar, e a segunda falha é mais silenciosa que a primeira.

Esse caso nunca tinha sido executado — estava entre os 11 que ficaram de fora da rodada anterior por orçamento de API. **Rodar o dataset inteiro foi o que o revelou.**

Corrigido listando no prompt o que cada tool fornece, com a regra explícita: *dizer "não tenho esse dado" sobre algo que uma tool devolve é tão errado quanto inventar o dado*.

A segunda falha (`arch_001`) foi de projeto: arquétipo só era alcançável via `compare_players`, e "que tipo de jogador é o Gobert?" não aciona comparação — o modelo acertou o rótulo de memória, não pelo dado. Daí a tool dedicada.

---

## 5. Claudescore: 73 → 85

### A régua precisou mudar — e por quê

A régua anterior (6 dimensões) media **confiabilidade**: não inventar número, não sair do escopo, não errar a moldura temporal. Ela não tinha nenhuma dimensão para **profundidade de análise de domínio** — que é exatamente o que este trabalho entregou.

Medir esta entrega com a régua velha daria 85 → 86: quase nada, porque a régua não enxerga a mudança. Isso não significaria que o trabalho não valeu; significaria que a régua está incompleta.

Então adicionei a 7ª dimensão e **re-pontuei as três versões na mesma régua nova**, para a comparação continuar honesta:

| Dimensão | Peso | v1.0 auditoria | v2.0 confiabilidade | v3.0 arquétipos |
|---|---|---|---|---|
| Precisão factual / anti-alucinação | 25 | 12 | 22 | **23** |
| **Profundidade de análise de domínio** | 20 | 5 | 5 | **15** |
| Tratamento de erros e casos de borda | 15 | 13 | 14 | **14** |
| Guardrail de escopo | 12 | 3 | 10 | **10** |
| Grounding temporal | 12 | 4 | 10 | **10** |
| Memória / contexto de conversa | 8 | 6 | 6 | **6** |
| Comunicação de ambiguidade/incerteza | 8 | 4 | 6 | **7** |
| **Total** | **100** | **47** | **73** | **85** |

*(Na régua antiga de 6 dimensões, a trajetória foi 53 → 85 → 86. Os dois números medem coisas diferentes; o da tabela acima é o que passa a valer.)*

### O que mudou nesta versão

- **Profundidade de domínio 5 → 15.** De "score + deltas de z-score" para 44 arquétipos em 7 categorias, com primário/secundário, comparação de perfis e tool dedicada. Validado contra a liga real e adotado pelo modelo em 11 de 13 respostas.
- **Precisão factual 22 → 23.** Não pela máquina, que é a mesma, mas pela evidência: o dataset completo (42 casos) rodou com 100% de correção numérica, e a regressão de over-refusal foi encontrada e corrigida.
- **Ambiguidade 6 → 7.** O "perfil equilibrado nesta categoria" é uma admissão explícita de incerteza em um lugar novo.

### Por que profundidade de domínio é 15 e não 20

Sendo direto sobre o que falta:

- **Os pesos são hipóteses, não ciência.** Cada arquétipo tem pesos escolhidos por julgamento de domínio, no mesmo espírito dos `GROUP_WEIGHTS` — defensáveis e explícitos, mas **sem validação empírica contra anotação humana**. Isso é a Fase 5 do roadmap, e é o que separa "algoritmo com hipóteses" de "algoritmo validado".
- **O rebote é raso** — 5 arquétipos sobre 2 features, porque é só o que a camada de dados oferece.
- **Eras antigas perdem categorias inteiras.** Sem tracking, a defesa fica com um único arquétipo viável. O sistema é honesto sobre isso, mas continua sendo uma limitação.
- **Não há análise tática de confronto.** O item 5.2 da auditoria ("como cada um se encaixa contra um time que usa muito pick-and-roll") continua aberto — hoje o sistema descreve o jogador, não o duelo.
- **Não dá para buscar por arquétipo.** "Me mostre todos os protetores de aro da liga" ainda não é uma pergunta respondível.

---

## 6. Próximos passos

1. **Validar os pesos empiricamente** (Fase 5): montar dataset de pares anotados e otimizar contra ele. É o que transforma os 15 em algo perto de 20.
2. **Busca por arquétipo**: `find_players_by_archetype("Protetor de Aro")` — a estrutura já existe, falta a varredura sobre a população.
3. **Análise de confronto** (item 5.2 da auditoria): usar os arquétipos dos dois lados para responder perguntas de matchup.
4. **Enriquecer o rebote** puxando `BOX_OUTS` e `LOOSE_BALLS_RECOVERED`, que o `nba_data` já busca mas a similaridade não usa como feature.
5. **Marcar `v3.0-arquetipos`** e comparar com `v2.0-confiabilidade` no GitHub.
