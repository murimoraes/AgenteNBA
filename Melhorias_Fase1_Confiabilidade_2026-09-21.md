# Fase 1 — Confiabilidade: o que mudou

**Data:** 2026-09-21
**Versão:** `v1.0-auditoria` → `v2.0-confiabilidade`
**Escopo:** Fase 1 do roadmap de [AgenteNBA_Auditoria_Melhorias.md](AgenteNBA_Auditoria_Melhorias.md) (seções 3.1, 3.2, 3.3 e 16), com as falhas de runtime documentadas em [Relatorio_Testes_AgenteNBA_2026-09-21.md](Relatorio_Testes_AgenteNBA_2026-09-21.md).

---

## 1. Resumo

O objetivo da Fase 1 era transformar o que já existia em algo **verificável**. A frase central do projeto — "o LLM nunca inventa número" — era uma instrução de system prompt, ou seja, um comportamento provável. Agora é uma etapa do pipeline: cada número da resposta é conferido contra o JSON que as tools devolveram, e o que não tem lastro volta para o modelo corrigir antes de chegar ao usuário.

As três falhas críticas do relatório de testes foram corrigidas e estão fixadas contra regressão: o salário inventado do LeBron, o jogo de abril narrado como "ontem" e a pergunta sobre a capital da França respondida como se fosse um assistente genérico.

**Resultado medido:** 214 testes automatizados (offline, sem custo) e 26 casos de avaliação end-to-end contra a API real, com **100% de correção numérica** — nenhum número sem lastro em nenhuma execução.

**Claudescore: 53 → 85** (mesma régua da avaliação anterior; detalhamento na seção 5).

---

## 2. O que foi implementado

### 2.1 Fact checker numérico determinístico — `validation/facts.py`

Resolve o item **3.2** da auditoria e a melhoria **C1** do relatório de testes.

Depois que o modelo escreve, o módulo:

1. **Monta a evidência** — percorre recursivamente o JSON de todas as tools do turno, inclusive números dentro de strings (`"14/23"`, `"APR 10, 2026"`). Percentuais guardados como fração (`0.576`) entram também como `57.6`, que é como o texto os cita. Entram os números da própria pergunta do usuário.
2. **Aceita derivação legítima** — se a tool deu 10.5 convertidos e 18.2 tentados, escrever "57.7%" é aritmética sobre dado real, não invenção.
3. **Extrai os claims** — ignorando marcadores de lista e lendo separador decimal tanto en quanto pt-BR.
4. **Confronta** — cada número precisa casar com alguma evidência dentro da tolerância da própria precisão com que foi escrito (`29.6` casa com `29.6428`).
5. **Aplica o contrato de dados** — métricas que nenhuma tool fornece (salário, contrato, prêmios, títulos, classificação, lesões) são barradas mesmo que o número coincida por acaso.

O julgamento do contrato é **frase a frase**, com detecção de recusa. Dizer "este sistema não tem dados sobre salários" é o comportamento desejado e não pode contar como violação — punir isso ensinaria o agente a esconder a limitação em vez de declará-la. Uma afirmação real continua sendo pega, inclusive quando aparece na mesma resposta que uma recusa.

### 2.2 Ciclo de correção no agente — `agent.py`

A auditoria desenhou o fluxo `válido? → exibe / regenera`. Implementado:

- reprovou → o modelo recebe **a lista exata** do que ficou sem lastro e reescreve a resposta inteira;
- o número de tentativas é configurável (`FACT_CHECK_RETRIES`, padrão 1) porque **cada tentativa custa uma chamada de API**;
- persistindo a pendência, o texto **não é apagado**: é entregue com aviso visível. Esconder o que não passou devolveria o problema a quem menos tem como checar.

### 2.3 Guardrail de escopo — `validation/scope.py`

Melhoria **A2**. Roda **antes da primeira chamada de API**, então pergunta fora do domínio custa zero token.

O critério é deliberadamente assimétrico: recusar pergunta válida é pior que deixar passar uma duvidosa, porque o usuário perde a resposta. Na dúvida, deixa passar.

Detalhe encontrado na prática: a base estática da NBA tem ~5.000 jogadores, incluindo um "Tom Copa" e um "Gary Voce" — sem cuidado, *"Copa do Mundo de futebol"* entrava no escopo por causa de um jogador de 1989. A heurística de nome próprio exige inicial maiúscula e ignora palavras comuns, e sinal explícito de outro domínio tem precedência.

### 2.4 Grounding temporal — `validation/temporal.py` + `tools.py`

Melhoria **A1**. A causa raiz era simples: as tools devolviam o último jogo do log sem dizer **quando** ele foi em relação a hoje, e o modelo não tem relógio.

- `get_recent_games` passa a carregar `data_freshness`: data de hoje, data do último jogo, distância em dias e um aviso explícito quando o dado é velho;
- o validador cobra a data real quando a resposta usa vocabulário de "agora" ou quando o usuário pergunta em termos de dia.

### 2.5 Contrato de dados — `validation/schemas.py`

Itens **12** e **13.1** da auditoria, nos dois sentidos:

- **entrada**: argumentos gerados pelo LLM são validados contra o schema publicado (tipo, enum, faixa, formato de temporada, parâmetro inventado) **antes** da função Python rodar. `num_games="7"` é convertido; `num_games=500` é ajustado para 25; `season="2024"` é rejeitada com mensagem que o modelo consegue corrigir;
- **saída**: cada payload é conferido contra invariantes do domínio (percentual entre 0 e 1, contagem não negativa, `player_id` coerente, campos obrigatórios). Violação não derruba a resposta — fica registrada no turno e aparece na interface.

### 2.6 Transparência — `tools.py` + `ui.py`

- **`name_match`** (melhoria B1): quando "Lebron Jams" é resolvido como LeBron James, o payload carrega o aviso e o prompt manda declarar a interpretação. Antes a troca era silenciosa.
- **`not_provided`** no perfil: o modelo vê, no próprio payload, que salário e prêmios não existem ali.
- **Selo de verificação** na interface: "VERIFICADO — 7/7 números conferidos contra as tools" (verde) ou a lista do que não pôde ser confirmado (laranja). Perguntas fora de escopo mostram "nenhuma chamada de API foi feita".
- **Comparação ambígua** (M1) e **pronome ambíguo** (M2) tratados no system prompt: "compare X e Y" agora chama produção *e* estilo; pronome ambíguo exige declarar de quem se trata.

### 2.7 Observabilidade mínima — `agent.py` + `config.py`

O critério de conclusão da Fase 1 exige latência e custo. Cada turno carrega `latency_s`, `iterations`, `api_calls`, tokens e `cost_usd` (tabela de preços em `config.py`). Modelo fora da tabela devolve `None` — a mesma regra que o projeto aplica ao agente: não estimar o que não se sabe.

### 2.8 Suíte de testes — `tests/` (item 3.3)

**214 testes, offline, ~6 segundos, custo zero.** Nada sai para a rede: nem a API do LLM, nem a da NBA.

| Arquivo | Testes | Cobre |
|---|---|---|
| `test_scope.py` | 26 | guardrail de escopo, falsos positivos e negativos |
| `test_similarity.py` | 25 | invariantes da escala, pesos, features, veredito |
| `test_schemas.py` | 24 | contrato de entrada e saída das tools |
| `test_facts.py` | 24 | fact checker, derivações, contrato de dados |
| `test_eval.py` | 24 | a própria suíte de avaliação |
| `test_nba_data.py` | 21 | resolução de nome, eras, temporadas, troca de time |
| `test_config.py` | 21 | provider, modelo, custo, vazamento de chave |
| `test_agent.py` | 19 | loop, erros de provider, ciclo de correção |
| `test_tools.py` | 16 | erros estruturados, limites, metadados |
| `test_temporal.py` | 14 | parsing de data, frescor, detecção |

Os testes do agente usam um client falso no formato OpenAI, o que permite cobrir o que é difícil de reproduzir com a API real: tool inexistente, resposta sem `choices`, rate limit, estouro de iterações e o ciclo de correção completo.

### 2.9 Suíte de avaliação — `eval/` (item 3.1)

37 casos cobrindo as 10 categorias que a auditoria exige, mais memória de conversa. Casos multi-turno suportam `history`.

O runner tem **teto rígido de orçamento**: para antes de estourar, não depois, e informa o que ficou de fora. `--dry-run` valida o dataset sem gastar nada; casos de escopo custam zero por natureza.

Métricas produzidas: taxa de sucesso, correção numérica, taxa de alucinação, respostas fora do contrato, respostas reescritas, violações de contrato, latência (média/p50/p95) e custo.

---

## 3. Evidência

### Testes
```
214 passed in 6.05s
```

### Avaliação contra a API real
26 de 37 casos executados (os 11 restantes ficaram de fora por orçamento, não por falha). Registro completo em [eval/resultados_2026-09-21.md](eval/resultados_2026-09-21.md).

| Métrica | Resultado |
|---|---|
| Taxa de sucesso | 26/26 (100%) na rodada final de cada caso |
| **Correção numérica** | **100%** — nenhum número sem lastro, em nenhuma rodada |
| Respostas fora do contrato de dados | 0 |
| Violações de contrato nas tools | 0 |
| Erros do agente | 0 |
| Latência média | ~6s (p95 ~17s, puxado por cross-era) |
| Custo médio | ~US$ 0,0006 por pergunta |

### As falhas do relatório anterior, agora

| Caso original | Antes | Agora |
|---|---|---|
| #9 salário do LeBron | inventou "$44.5 milhões" | "este sistema não tem dados sobre salários, contratos ou valores de mercado" |
| #4 capital da França | respondeu normalmente | recusada antes da API, custo zero |
| #8 "jogou ontem?" | chamou abril de "ontem" | "jogou no dia 10 de abril de 2026" |
| #11 melhor jogador | opinou e errou a contagem de temporadas | recusa, sem citar prêmios |
| #3 pronome ambíguo | escolheu em silêncio | "me informe o nome do jogador" |
| #2 "compare X e Y" | só estilo | produção + estilo |
| #5 nome errado | corrigiu em silêncio | declara a interpretação |
| #6 temporada inexistente | já correto | fixado contra regressão |
| #7 jogador inexistente | já correto | fixado contra regressão |

### Verificação na interface
Confirmado no navegador: o selo verde ("7/7 números conferidos") e a recusa de escopo renderizam corretamente. A verificação no navegador pegou um bug que os testes não pegariam — o servidor estava servindo `ui.py` em cache e quebrava com `AttributeError`; resolvido com reinício.

---

## 4. A avaliação encontrou defeitos nos próprios verificadores

Vale registrar, porque é o argumento a favor de ter evals: a primeira rodada deu **74%**, e a investigação mostrou que **nenhuma das 6 reprovações era erro do agente**. Eram dois defeitos meus:

1. **Falso positivo do contrato**: a resposta "não tenho dados sobre salários" era marcada como violação só por conter a palavra. Corrigido com julgamento frase a frase.
2. **Escopo recusando pergunta válida**: "Como ele está jogando?" caía como off-topic porque o vocabulário não tinha as formas verbais de "jogar".

Mais duas expectativas do dataset eram rígidas demais — cobravam frase exata onde o modelo varia a formulação — e viraram detectores reutilizáveis (`acknowledges_missing_data`, `asks_clarification`).

Sem a suíte, os três primeiros seriam invisíveis e o quarto viraria "o agente está errado".

---

## 5. Claudescore: 53 → 85

Mesma régua da avaliação anterior, para a comparação ser honesta. Os pesos não mudaram.

| Dimensão | Peso | Antes | Agora | Por quê |
|---|---|---|---|---|
| Precisão factual / anti-alucinação | 30 | 14 | **26** | 100% de correção numérica em 26 casos; a armadilha do salário e as 4 métricas fora de contrato agora são recusadas. Não é 30 porque a checagem é *post-hoc*, não um bloqueio duro: se a correção falhar, o texto é entregue com aviso. |
| Tratamento de erros e casos de borda | 20 | 18 | **19** | Somou validação de argumento e contrato de saída aos erros estruturados que já eram bons. |
| Guardrail de escopo | 15 | 4 | **12** | 4/4 casos recusados antes da API. Não é 15 porque é heurística de vocabulário: exige manutenção e uma pergunta off-topic com uma palavra de basquete passa. |
| Grounding temporal | 15 | 5 | **12** | Verificado: cita "10 de abril de 2026" em vez de "ontem". Não é 15 porque só `get_recent_games` carrega frescor. |
| Memória / contexto de conversa | 10 | 7 | **8** | Casos multi-turno passam e o prompt exige declarar a suposição — mas continua sem garantia determinística. |
| Comunicação de ambiguidade/incerteza | 10 | 5 | **8** | Pede esclarecimento, declara correção de nome e o selo expõe a incerteza. |
| **Total** | **100** | **53** | **85** | |

### O que o score não mede

A régua avalia **comportamento do agente**, não maturidade de engenharia — e foi mantida assim de propósito, para o 53 → 85 ser comparável. Se medisse verificabilidade, os 214 testes e a suíte de evals seriam a maior mudança desta fase: são o que permite afirmar qualquer um dos números acima.

### Por que não é mais alto

Sendo direto sobre os limites:

- **O fact checker é uma rede, não uma parede.** Aceitar derivações e converter frações em percentual amplia o conjunto aceito. Um número inventado que por acaso caia perto de uma evidência passa.
- **O contrato de dados é uma lista curada à mão.** Métrica fora da lista (ex.: "quantos triplos-duplos ele tem") não seria barrada por ele — só pela checagem numérica.
- **O escopo é vocabulário.** Funciona bem nos casos testados e vai precisar de manutenção.
- **11 dos 37 casos não foram executados**, por orçamento de API.

---

## 6. Status da Fase 1

| Item do roadmap | Status |
|---|---|
| Criar `tests/` | Concluído — 214 testes |
| Criar `eval/` | Concluído — runner, métricas, README |
| Dataset de 30–50 perguntas | Concluído — 37 casos, 11 categorias |
| Implementar numeric fact checker | Concluído |
| Validar tool selection | Concluído — `tools_any` / `tools_all` / `tools_forbidden` |
| Testes de similaridade | Concluído — 25 testes |
| Testes de erro | Concluído |
| **Critério:** taxa de sucesso, alucinação, correção numérica, latência e custo reproduzíveis | Concluído |

---

## 7. Próximos passos

1. **Fechar a régua**: rodar os 11 casos restantes (~30 chamadas, ~US$ 0,02) para o número de sucesso cobrir o dataset inteiro.
2. **Marcar `v2.0-confiabilidade`** e comparar com `v1.0-auditoria` no GitHub — o diff entre as duas tags é a evidência de evolução para portfólio.
3. **CI**: rodar `pytest tests/` a cada push. A suíte é offline, então não custa nada em CI.
4. **Fase 2 — Modularização**: dividir `nba_data.py` e `tools.py`, que continuam concentrando responsabilidades.
5. **Estender o contrato de dados** para métricas derivadas (triplos-duplos, sequências), hoje fora da lista curada.
