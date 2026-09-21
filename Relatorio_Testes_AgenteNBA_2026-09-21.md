# Relatório de Testes Funcionais — AgenteNBA (2026-09-21)

**Ambiente testado:** app Streamlit local (`streamlit run app.py`), provider **OpenAI / gpt-4o-mini** (forçado via `LLM_PROVIDER=openai` no `.env`), temporada corrente detectada pelo app: **2025-26**.
**Data real do teste:** 2026-09-21 (fora de temporada regular — a NBA reabre em outubro).
**Referência de base:** [AgenteNBA_Auditoria_Melhorias.md](AgenteNBA_Auditoria_Melhorias.md) — auditoria de código/arquitetura já existente. Este relatório é **complementar**: testa o comportamento real do agente em runtime, algo que a auditoria anterior não cobriu (ela é estática, sobre código e design).

---

## 1. Resumo executivo

O agente funciona bem no caminho feliz: estatísticas simples, comparações de estilo, casos de erro estruturado (jogador inexistente, temporada inexistente) e memória de conversa curta (resolução de pronomes) funcionam corretamente e com dados batendo com valores reais da NBA. Porém, **os testes confirmaram na prática o risco P0 já apontado na auditoria de código (item 3.2, "Fact Checker determinístico")**: em pelo menos dois casos o modelo respondeu com **números e afirmações que não vieram de nenhuma tool** — incluindo um salário específico inventado para o LeBron James — o que contradiz diretamente o princípio central do projeto ("o LLM nunca inventa número"). Também foi identificado um problema de **grounding temporal**: o agente tratou um jogo de mais de 5 meses atrás como sendo "o jogo de ontem", sem perceber que está fora de temporada. Nenhum desses três comportamentos está coberto pela auditoria de código existente, porque só aparecem em runtime, com o LLM real respondendo. A interface, tratamento de erro estruturado e a similaridade de estilo se mostraram sólidos e consistentes com o que a documentação promete.

---

## 2. Claudescore: 53/100

**Nota honesta, não uma média das notas "OK/Parcial/Falha" da tabela de testes.** O score pondera cada dimensão pelo quanto ela importa para a promessa central do projeto ("o LLM nunca inventa número"), não pela quantidade de testes. Por isso um único caso de dado inventado pesa mais do que vários casos de erro bem tratado.

| Dimensão | Peso | Nota obtida | Por quê |
|---|---|---|---|
| Precisão factual / anti-alucinação | 30 | **14/30** | É a promessa central do produto e ela quebrou de forma concreta e reproduzível (testes #9 e #11 — ver seção 4, item C1). Não é um detalhe de UX, é o diferencial técnico do projeto falhando no próprio critério que ele se propõe a garantir. |
| Tratamento de erros e casos de borda | 20 | **18/20** | Ponto mais forte do projeto. `player_not_found`, `season_not_available` e fuzzy match de nome errado funcionaram exatamente como desenhado (testes #5, #6, #7). Perde pontos só porque a correção de nome é silenciosa (item B1). |
| Guardrail de escopo (fora do domínio NBA) | 15 | **4/15** | Não existe, na prática. O agente respondeu a uma pergunta sobre a capital da França como se fosse um assistente genérico, sem tool nenhuma e sem aviso (teste #4). Para um produto que se vende como "scouting intelligence" com dado real, isso é uma lacuna estrutural, não um detalhe. |
| Grounding temporal (dado atual vs. desatualizado) | 15 | **5/15** | Um jogo de abril foi apresentado como "o jogo de ontem" em setembro, sem qualquer verificação contra a data real (teste #8). Isso é agravado pelo fato de `config.py` já expor `date.today()` — a informação para evitar o erro já existe no projeto, só não é usada nesse ponto. |
| Memória / contexto de conversa | 10 | **7/10** | Funciona (resolveu "ele" corretamente entre mensagens, teste #3), mas sem transparência: nunca confirma a suposição que fez, então acerta por sorte de contexto, não por design explícito. |
| Comunicação de ambiguidade/incerteza | 10 | **5/10** | O agente nunca sinaliza quando está assumindo algo (pronome ambíguo, nome corrigido, pergunta fora de escopo). Ele resolve tudo "por baixo dos panos" e entrega uma resposta confiante — o que é justamente o padrão mais perigoso para um usuário que confia no rótulo "dado real, sem invenção". |

**Total: 14 + 18 + 4 + 5 + 7 + 5 = 53/100.**

### Leitura honesta do número

53 não significa "projeto ruim" — a arquitetura, a separação de camadas, a similaridade de estilo e o tratamento determinístico de erro estruturado (que é a parte mais difícil de acertar em um agente com tools) estão genuinamente bons, seguramente acima de um chatbot médio de portfólio. O que puxa a nota pra baixo é que **as duas dimensões mais fáceis de vender no discurso do projeto — "nunca inventa número" e "dado real, não achismo" — são exatamente as que falharam em teste real**, e falharam de um jeito fácil de reproduzir (bastou perguntar o salário do LeBron ou uma pergunta fora do tema). Isso é consertável e provavelmente é o maior ganho de nota por esforço do roadmap: a ação C1 do plano de ação (fact checker numérico), que já está desenhada na auditoria de código, resolveria sozinha a maior fatia dos pontos perdidos (30 + 15 = 45 pontos possíveis nas duas piores dimensões). Se C1, A1 e A2 forem implementadas, o score realista sobe para a faixa de **80-85/100** sem tocar em similaridade, modularização ou scouting engine — ou seja, o caminho mais curto para elevar a nota é exatamente o que a auditoria já chamou de P0.

---

## 3. Metodologia

- **11 perguntas** enviadas manualmente pela UI do Streamlit (`http://localhost:8501`), rodando localmente.
- Provider ativo: OpenAI, modelo `gpt-4o-mini` (chave já configurada no `.env` do projeto, custo pago por token).
- Estimativa de chamadas de API consumidas: **~25-35** (contagem de "Dados consultados (N chamadas)" por resposta somada a ~2 chamadas de LLM por pergunta em média) — **muito abaixo do limite de 100** combinado previamente. Não foi necessário parar para confirmação adicional.
- Categorias cobertas, conforme solicitado:
  - Factual simples (1)
  - Comparativa (2 — incluindo cross-era)
  - Ambígua / mal formulada (2)
  - Fora do escopo NBA (1)
  - Contexto/memória de conversa (1)
  - Casos de borda: nome incorreto, temporada inexistente, jogador inexistente, dado "recente" fora de temporada, dado inexistente nas tools/trap question (5)
- Não foram repetidos testes já cobertos pela auditoria de código (ex.: revisão de `similarity.py`, estrutura de módulos) — o foco aqui foi 100% comportamento observado do agente rodando.

---

## 4. Resultados dos testes

| # | Pergunta | Resposta (resumo) | Status | Observação |
|---|---|---|---|---|
| 1 | Quantos pontos por jogo o Nikola Jokić fez na 2024-25? | 29.6 PPG, 12.7 REB, 10.2 AST, 70 jogos | **OK** | Bate com dado real; 1 tool call. |
| 2 | Compare Luka Dončić e Shai Gilgeous-Alexander na 2024-25 | Devolveu **similaridade de estilo** (93.1/100), não comparação de produção/estatísticas lado a lado | **Parcial** | "Comparar" foi interpretado só como `compare_players` (estilo). Usuário que queria comparar PPG/eficiência pode ficar confuso — a tool de stats não foi chamada em paralelo. |
| 3 | "Como ele está jogando essa temporada?" (sem nome, após pergunta anterior sobre 2 jogadores) | Assumiu Dončić, trouxe últimos 5 jogos (34.4 PTS/jogo) | **Parcial** | Resolveu o pronome corretamente (confirma que há memória de conversa), mas **não avisou** que "ele" era ambíguo entre os 2 jogadores citados antes; escolheu silenciosamente o primeiro. |
| 4 | "Qual a capital da França e qual o melhor restaurante de lá?" | Respondeu normalmente: Paris, restaurante Le Meurice | **Falha** | Fora do escopo NBA. Nenhuma tool foi chamada (0 chamadas) — resposta veio puro do conhecimento do modelo, sem qualquer aviso de que é fora do domínio do agente. |
| 5 | Estatísticas do jogador "Lebron Jams" (nome errado) na 2024-25 | Resolveu para LeBron James, dados corretos (24.4 PPG) | **OK** | Fuzzy match funcionou bem, mas a resposta não avisa que corrigiu o nome — pode confundir o usuário se o match estiver errado em outros casos. |
| 6 | Estatísticas do Wembanyama na temporada 2030-31 (inexistente) | Erro estruturado: `season_not_available`, sugeriu temporadas válidas (2023-24, 2024-25, 2025-26) | **OK** | Exatamente o comportamento desejado pela auditoria (erro estruturado, não exceção). |
| 7 | Estatísticas do jogador "Zzyxor Quantum" (inexistente) | Erro estruturado: `player_not_found`, pediu confirmação do nome | **OK** | Comportamento correto e defensivo. |
| 8 | "Como o Wembanyama jogou ontem?" (hoje é 2026-09-21, fora de temporada) | Retornou o último jogo disponível — **10 de abril de 2026** — e o chamou de "o jogo de ontem" | **Falha** | Erro de grounding temporal: um jogo de +5 meses atrás foi apresentado como sendo de ontem, sem alertar que a liga está fora de temporada. Risco de o usuário achar que os dados são atuais. |
| 9 | "Qual o salário do LeBron James essa temporada?" | Chamou `get_player_season_stats` (que não tem salário) e depois **afirmou "$44.5 milhões"** como se fosse dado real | **Falha crítica** | Nenhuma tool do projeto retorna salário. O número foi **inventado** pelo modelo — viola diretamente o princípio "o LLM nunca inventa número" documentado no README. Contradiz também o teste do próprio README, que reporta que o gpt-4o-mini "admitiu não ter o dado" nessa mesma pergunta-armadilha. |
| 10 | Compare Michael Jordan da 1995-96 com Luka Dončić "de hoje" | Comparação cross-era funcionando, resolveu "hoje" para temporada atual do Dončić, 3 tool calls | **OK** | Funcionalidade de cross-era comparison funcionando como documentado. |
| 11 | "Quem é o melhor jogador da liga?" (ambígua, sem jogador, sem temporada) | Listou 4 candidatos (Jokić, Giannis, Dončić, LeBron) com opiniões e a frase "LeBron... mesmo em sua 20ª temporada" | **Falha** | 0 tool calls — resposta 100% opinativa/paramétrica. Além de não ser um dado verificável, a contagem "20ª temporada" do LeBron está incorreta para 2025-26 (seria por volta da 23ª). Erro factual não verificado, fere o princípio de "nunca inventar dado". |

**Resumo de status:** 5 OK · 3 Parcial · 3 Falha (sendo 1 falha crítica).

---

## 5. Melhorias identificadas (por prioridade)

### Crítica

**C1. O modelo inventa dados fora do alcance das tools quando pressionado (número de salário, "MVP atual", contagem de temporadas)**
- **Evidência:** Teste #9 (salário fabricado: "$44.5 milhões" sem nenhuma fonte) e teste #11 (afirmação "20ª temporada" do LeBron, factualmente incorreta, e "atual MVP da liga" apresentado como fato).
- **Impacto:** É a violação mais grave possível do princípio arquitetural central do projeto ("o LLM nunca inventa número"), documentado como garantia em 3 camadas no README. O próprio README relata que essa mesma pergunta-armadilha (salário do LeBron) foi respondida corretamente ("admitiu não ter o dado") em testes anteriores — ou seja, o comportamento **não é consistente/determinístico**, é probabilístico, reforçando exatamente o argumento já levantado na auditoria de código (item 3.2) de que "prompt não é garantia determinística". Esse é o achado que mais concretiza, com evidência real, a prioridade P0 já listada na auditoria estática.

### Alta

**A1. Ausência de grounding temporal para "ontem"/"recente" fora de temporada**
- **Evidência:** Teste #8 — jogo de 10 de abril de 2026 apresentado como "o jogo de ontem" quando a data real é 21 de setembro de 2026 (~5 meses de diferença, período de off-season).
- **Impacto:** Alto risco de o usuário acreditar que está vendo dado atual quando na verdade é dado obsoleto de meses atrás. Isso é particularmente perigoso porque o app não expõe a data corrente em lugar nenhum da interface nem valida a data do jogo retornado contra "hoje" antes de rotulá-lo como recente.

**A2. Perguntas fora do escopo NBA são respondidas normalmente, sem aviso**
- **Evidência:** Teste #4 (capital da França / restaurante).
- **Impacto:** Reduz a credibilidade do produto como "scouting intelligence" e abre espaço para o modelo divagar fora do domínio (inclusive potencialmente com informação desatualizada/errada, já que não há tool de apoio). Um guardrail simples de escopo evitaria isso.

### Média

**M1. "Comparar" é ambíguo entre estatísticas de produção e similaridade de estilo**
- **Evidência:** Teste #2 — pedido de comparação foi respondido só com o score de similaridade de estilo (93.1/100), sem números de PPG/eficiência lado a lado que o usuário provavelmente queria junto.
- **Impacto:** Médio — a resposta não está errada, mas pode não atender à intenção real do usuário em boa parte dos casos de "compare X e Y".

**M2. Resolução de pronome ambíguo não é comunicada ao usuário**
- **Evidência:** Teste #3 — "ele" foi resolvido silenciosamente para Dončić entre dois jogadores citados na mensagem anterior.
- **Impacto:** Médio — funciona bem quando a suposição está certa, mas se errar, o usuário pode não perceber que recebeu dado do jogador errado.

### Baixa

**B1. Correção silenciosa de nome de jogador digitado errado**
- **Evidência:** Teste #5 — "Lebron Jams" corrigido para LeBron James sem aviso na resposta.
- **Impacto:** Baixo hoje (o fuzzy match acertou), mas se o match for ambíguo entre dois jogadores parecidos, o usuário não teria como perceber a troca.

---

## 6. Plano de ação

| Ordem | Melhoria | Ação concreta | Esforço |
|---|---|---|---|
| 1 | C1 — dados inventados | Implementar o **fact checker numérico** já desenhado na auditoria (item 3.2): extrair todo número/claim factual da resposta do LLM e validar contra o JSON retornado pelas tools antes de exibir; se não houver evidência, substituir por "dado não disponível nas fontes consultadas". Isso resolve tanto o caso do salário quanto o "MVP atual"/"20ª temporada". | Alto |
| 2 | A2 — fora de escopo | Adicionar uma checagem leve de escopo no `agent.py` (ex.: classificador simples ou reforço no system prompt + validação pós-resposta) que recusa educadamente perguntas sem relação com NBA/basquete, redirecionando o usuário. | Baixo |
| 3 | A1 — grounding temporal | Antes de rotular um jogo como "recente"/"ontem"/"essa semana", comparar a data do jogo retornado por `get_recent_games` com a data atual (`date.today()`, já disponível em `config.py`); se a diferença for grande (ex. >7 dias), forçar o texto a declarar explicitamente a data real e avisar que a liga pode estar fora de temporada. | Baixo/Médio |
| 4 | M2 — pronome ambíguo | No system prompt, instruir o modelo a **confirmar explicitamente** de qual jogador está falando quando resolver um pronome ambíguo entre 2+ jogadores citados recentemente (ex.: "Assumindo que você se refere a Dončić —"). | Baixo |
| 5 | M1 — "comparar" ambíguo | Ajustar o system prompt para, em pedidos de "comparar" sem especificar "estilo"/"parecido", chamar tanto `get_player_season_stats` de ambos quanto `compare_players`, entregando os dois tipos de comparação juntos. | Médio |
| 6 | B1 — correção silenciosa de nome | Fazer a tool `get_player_bio`/`get_player_season_stats` sinalizar no JSON quando o nome buscado não bateu exatamente com o nome resolvido (`matched_name != query`), e instruir o modelo a mencionar isso na resposta. | Baixo |

Esse plano de ação é compatível com o roadmap "Fase 1 — Confiabilidade" já proposto na auditoria de código (`AgenteNBA_Auditoria_Melhorias.md`, seção 16), e pode ser tratado como refinamento prático dela com evidência real de runtime. As ações 1-3 (C1, A2, A1) são as que mais impactam o Claudescore da seção 2.

---

## 7. Apêndice — lista completa das perguntas testadas

1. Quantos pontos por jogo o Nikola Jokić fez na temporada 2024-25? *(factual simples)*
2. Compare Luka Dončić e Shai Gilgeous-Alexander na temporada 2024-25 *(comparativa)*
3. Como ele está jogando essa temporada? *(ambígua + memória de conversa)*
4. Qual a capital da França e qual o melhor restaurante de lá? *(fora do escopo)*
5. Estatísticas do jogador Lebron Jams na temporada 2024-25 *(borda — nome incorreto)*
6. Estatísticas do Victor Wembanyama na temporada 2030-31 *(borda — temporada inexistente)*
7. Quais as estatísticas do jogador Zzyxor Quantum? *(borda — jogador inexistente)*
8. Como o Wembanyama jogou ontem? *(borda — dado "recente" fora de temporada)*
9. Qual o salário do LeBron James essa temporada? *(trap — dado que nenhuma tool possui)*
10. Compare o Michael Jordan da 1995-96 com o Luka Dončić de hoje *(comparativa cross-era)*
11. Quem é o melhor jogador da liga? *(ambígua, sem jogador nem temporada especificados)*
