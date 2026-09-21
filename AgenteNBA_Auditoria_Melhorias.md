# Auditoria Técnica e Plano de Evolução — AgenteNBA

**Repositório:** `murimoraes/AgenteNBA`  
**Branch auditada:** `main`  
**Escopo:** arquitetura, engenharia de software, agente/LLM, camada de dados, algoritmo de similaridade, testes, avaliação e posicionamento como projeto de portfólio para AI Engineer/Data/ML.

---

## 1. Objetivo da auditoria

Este documento consolida as falhas, riscos e melhorias propostas durante a revisão do projeto **AgenteNBA**.

O objetivo não é aumentar a quantidade de funcionalidades indiscriminadamente, mas elevar o sistema de um chatbot com tools para uma plataforma de **scouting intelligence**, com:

- comportamento agentic mais robusto;
- dados determinísticos e rastreáveis;
- validação de respostas do LLM;
- testes automatizados;
- avaliação quantitativa do agente;
- arquitetura modular e sustentável;
- metodologia mais defensável para similaridade entre jogadores.

---

# 2. Diagnóstico executivo

O projeto já apresenta uma base técnica acima do padrão de um chatbot simples. Há separação entre interface, agente, tools, acesso aos dados e algoritmo de similaridade; a camada estatística é predominantemente determinística; há normalização por temporada; existe tratamento de diferentes eras da NBA; e a documentação explica diversas decisões técnicas.

Os maiores gargalos atuais não estão na falta de funcionalidades, mas em **validação, testes, robustez agentic e modularização**.

### Principais prioridades

| Prioridade | Frente | Situação atual | Ação recomendada |
|---|---|---|---|
| P0 | Evals de IA | Ausente/incipiente | Criar suíte de avaliação automatizada |
| P0 | Fact checking numérico | Protegido principalmente por prompt | Validar claims da resposta antes de exibir |
| P0 | Testes | Não há estrutura de testes robusta | Criar testes unitários e de integração |
| P1 | Agent Planner | Fluxo ainda depende muito do LLM | Criar planejamento explícito de tarefas/tools |
| P1 | Modularização | `nba_data.py` e `tools.py` concentram responsabilidades | Dividir por domínio/responsabilidade |
| P1 | Similaridade | Algoritmo próprio, mas pesos manuais | Criar validação humana/empírica dos pesos |
| P1 | Scouting Engine | Dados ricos, mas pouca abstração de domínio | Criar arquétipos e conceitos táticos derivados |
| P2 | Cross-era | Boa normalização por liga | Evoluir para ajuste de era mais explícito |
| P2 | Observabilidade | Básica | Adicionar logs, métricas, latência e custo |
| P2 | Produção/deploy | Estrutura ainda simples | Pipeline de deploy e configuração mais robustos |

---

# 3. P0 — Melhorias críticas

## 3.1 Criar uma suíte de Evals do agente

### Problema

O projeto possui benchmarking manual de modelos no README, mas não possui uma estrutura sistemática de avaliação do comportamento do agente.

### Risco

Sem evals automatizados, alterações em prompt, tools ou modelo podem melhorar uma dimensão e quebrar outra sem serem detectadas.

### Implementação proposta

Criar:

```text
eval/
├── dataset.json
├── evaluator.py
├── metrics.py
└── README.md
```

### Dataset mínimo

Cada caso pode conter:

```json
{
  "id": "stats_001",
  "question": "Como foi a temporada do Victor Wembanyama?",
  "expected_tools": ["get_player_season_stats", "get_player_image"],
  "must_not_hallucinate": true,
  "expected_season": "2025-26"
}
```

### Métricas recomendadas

- **tool selection accuracy**;
- **tool argument accuracy**;
- **numeric factual accuracy**;
- **hallucination rate**;
- **season correctness**;
- **answer completeness**;
- **latência**;
- **tokens por pergunta**;
- **custo por pergunta**;
- **taxa de erro por provider/modelo**.

### Casos que devem existir

1. Estatísticas de um jogador.
2. Jogos recentes.
3. Comparação entre dois jogadores.
4. Busca por jogadores semelhantes.
5. Comparação entre épocas.
6. Jogador inexistente.
7. Temporada inexistente para o jogador.
8. Pergunta ambígua.
9. Pergunta que contém uma estatística que nenhuma tool possui.
10. Pergunta que exige múltiplas tools.

---

## 3.2 Criar um Fact Checker determinístico para números

### Problema

O sistema afirma que o LLM não pode inventar números, mas a proteção principal é baseada no `SYSTEM_PROMPT`.

Isso reduz o risco, porém **prompt não é garantia determinística**.

### Risco

O modelo pode gerar um número que não apareceu em nenhuma tool, mesmo obedecendo corretamente em grande parte das interações.

### Arquitetura proposta

```text
Tool outputs
    ↓
LLM gera resposta
    ↓
Extrator de claims numéricos
    ↓
Validador contra tool outputs
    ↓
┌───────────────┐
│ válido?       │
└──────┬────────┘
   sim │ não
       │
       ↓
    Exibe       Regenera/corrige
```

### Regras do validador

Para cada número detectado:

- verificar se o valor existe nos resultados das tools;
- aceitar pequenas diferenças apenas quando explicitamente configuradas para arredondamento;
- associar o número ao jogador e à temporada corretos;
- rejeitar números sem evidência no contexto estruturado;
- rejeitar datas/estatísticas que não foram consultadas quando a política exigir consulta prévia.

### Resultado esperado

A política “não inventar números” deixa de ser apenas um comportamento esperado do LLM e passa a ser uma propriedade verificável do pipeline.

---

## 3.3 Criar testes automatizados

### Problema

Não há uma estrutura dedicada de testes abrangendo as principais áreas determinísticas do projeto.

### Estrutura proposta

```text
tests/
├── test_similarity.py
├── test_nba_data.py
├── test_tools.py
├── test_agent.py
└── test_config.py
```

### Testes essenciais

#### Similaridade

```python

def test_resemblance_is_symmetric():
    ...
```

Garantir que `A × B` e `B × A` produzam resultado equivalente.

#### Faixa do score

```python

def test_similarity_range():
    assert 0 <= score <= 100
```

#### Jogador inexistente

```python

def test_unknown_player():
    result = get_player_season_stats("Jogador Inexistente")
    assert result["error"] == "player_not_found"
```

#### Temporada inexistente

Verificar retorno estruturado e sugestões em vez de exceção não tratada.

#### Tools

- argumentos inválidos;
- retorno de erro;
- player resolution;
- limites de `num_games`;
- schemas.

#### Agente

- execução sem API key;
- provider inválido;
- tool desconhecida;
- erro da API;
- excesso de iterações;
- ausência de `choices`;
- preservação correta do histórico.

---

# 4. P1 — Evolução arquitetural do agente

## 4.1 Criar um Scout Planner explícito

### Problema

O fluxo atual é essencialmente:

```text
Usuário
  ↓
LLM
  ↓
Tool calling
  ↓
Python/API
  ↓
LLM
  ↓
Resposta
```

O modelo funciona como roteador e redator, mas ainda não existe uma camada explícita de planejamento de scouting.

### Limitação

Perguntas táticas mais complexas dependerão excessivamente da habilidade do modelo em decidir sozinho:

- quais métricas buscar;
- quais tools chamar;
- em qual ordem;
- como interpretar o contexto.

### Arquitetura recomendada

```text
Usuário
   ↓
Intent / Task Classification
   ↓
Scout Planner
   ↓
Seleciona métricas e tools
   ↓
Execução das tools
   ↓
Validação dos dados
   ↓
Analytics / Scouting Engine
   ↓
Fact Checker
   ↓
LLM Narrative
   ↓
Relatório
```

### Tipos de intenção sugeridos

- `player_stats`;
- `recent_form`;
- `player_comparison`;
- `style_similarity`;
- `cross_era_comparison`;
- `scouting_report`;
- `matchup_analysis`;
- `unknown/clarification`.

---

# 5. P1 — Evolução do motor de scouting

## 5.1 Criar uma camada de domínio de scouting

Atualmente o sistema já possui muitas métricas, mas trabalha majoritariamente no nível de números individuais.

A próxima camada deveria traduzir essas métricas para conceitos de basquete.

### Estrutura proposta

```text
Scouting Engine
├── Scoring Archetype
├── Creation Archetype
├── Playmaking Archetype
├── Defensive Archetype
├── Rebounding Profile
├── Offensive Role
└── Physical Profile
```

### Exemplo de objeto derivado

```json
{
  "scoring_archetype": "3-level creator",
  "creation_archetype": "primary pick-and-roll",
  "playmaking": "advantage creator",
  "defensive_role": "help rim protector"
}
```

Essas categorias devem ser derivadas de regras estatísticas claras ou de modelos treinados/validados, e não inventadas livremente pelo LLM.

---

## 5.2 Tornar o agente capaz de responder perguntas táticas

Exemplo de pergunta-alvo:

> “Compare Wembanyama e Gobert defensivamente e diga como cada um se encaixa contra um time que usa muito pick-and-roll.”

Para isso, o sistema deve identificar automaticamente as métricas relevantes, em vez de apenas retornar um conjunto genérico de estatísticas.

### Fluxo ideal

```text
Pergunta tática
   ↓
Identificação do problema
   ↓
Features relevantes
   ↓
Dados defensivos
   ↓
Comparação
   ↓
Contextualização tática
   ↓
Relatório
```

---

# 6. P1 — Melhorias na similaridade

## 6.1 Validar empiricamente os pesos

O algoritmo atual usa pesos manuais por grupo, por exemplo:

```python
GROUP_WEIGHTS = {
    "shot_profile": 2.0,
    "creation": 1.3,
    "playmaking": 1.3,
    "defense": 1.1,
    "rebounding": 0.9,
    "role": 0.9,
    "physique": 0.8,
    "volume": 0.35,
}
```

A lógica é tecnicamente defensável como hipótese de domínio, porém os pesos não estão validados empiricamente.

### Evolução proposta

Criar um dataset de pares anotados por humanos:

```text
Player A | Player B | Similaridade humana
Curry    | Trae     | 0.90
Curry    | Gobert   | 0.05
Jokic    | Sengun   | 0.85
```

Depois:

```text
Pesos manuais
      ↓
Dataset anotado
      ↓
Otimização dos pesos
      ↓
Pesos aprendidos
      ↓
Validação
```

### Ganho

O projeto passa de “algoritmo baseado em hipóteses de domínio” para “algoritmo empiricamente validado”.

---

## 6.2 Avaliar estabilidade da similaridade

Adicionar testes para medir:

- sensibilidade a pequenas alterações nos dados;
- efeito da remoção de uma feature;
- estabilidade do ranking de semelhantes;
- impacto dos pesos;
- impacto de amostras pequenas;
- consistência entre temporadas.

### Pergunta importante

Se a alteração de uma métrica pouco relevante muda drasticamente o ranking dos semelhantes, o espaço de estilo precisa ser revisado.

---

# 7. P1 — Melhorias de cross-era

## Problema atual

A normalização por z-score da própria temporada é uma boa base para comparação entre épocas, porém não representa sozinha todas as mudanças estruturais do basquete.

### Evolução recomendada

Construir um pipeline mais explícito:

```text
Raw statistics
      ↓
Era normalization
      ↓
League-relative statistics
      ↓
Role normalization
      ↓
Style vector
```

### Métricas relativas que podem ajudar

Exemplos:

- frequência de 3PT relativa à liga;
- volume de criação relativo à função;
- eficiência relativa à média da liga;
- perfil de shot selection relativo à época;
- posse/ritmo relativo ao contexto da temporada.

### Objetivo

Distinguir:

> “estatisticamente parecido na distribuição daquele ano”

de:

> “taticamente comparável em uma era diferente”.

---

# 8. P1 — Modularização do código

## 8.1 Dividir `nba_data.py`

### Problema

`nba_data.py` concentra diversas responsabilidades:

- resolução de jogadores;
- acesso à API;
- cache;
- gestão de temporadas;
- composição de datasets;
- imagens;
- TLS;
- lógica relacionada a eras.

### Estrutura recomendada

```text
data/
├── nba_client.py
├── player_repository.py
├── stats_repository.py
├── image_repository.py
├── cache.py
└── era.py
```

---

## 8.2 Dividir `tools.py`

### Problema

`tools.py` começa a assumir características de um módulo “god object”, concentrando implementação das tools e schemas.

### Estrutura recomendada

```text
tools/
├── __init__.py
├── player_tools.py
├── stats_tools.py
├── comparison_tools.py
├── scouting_tools.py
└── schemas.py
```

O registro central poderia continuar em `tools/__init__.py`.

---

# 9. P2 — Observabilidade

O projeto já mostra tokens e alguns estados na UI, mas pode evoluir para observabilidade real.

## Métricas recomendadas

Por pergunta:

- modelo;
- provider;
- duração total;
- duração por tool;
- número de tool calls;
- tokens de entrada;
- tokens de saída;
- custo estimado;
- falhas;
- retries;
- resultado da validação factual;
- número de iterações do agente.

### Estrutura sugerida

```text
observability/
├── logger.py
├── metrics.py
└── tracing.py
```

### Evolução futura

Usar tracing por execução:

```text
request
 ├── llm_call_1
 ├── tool_call_1
 ├── tool_call_2
 ├── llm_call_2
 └── final_validation
```

---

# 10. P2 — Melhorias de arquitetura de produção

## Configuração

A separação por provider já é uma boa decisão. A próxima etapa é tornar configuração, secrets e ambientes mais robustos.

### Recomendações

- separar `dev`, `test` e `prod`;
- validar ambiente na inicialização;
- evitar defaults ambíguos em produção;
- centralizar configuração em um objeto tipado;
- documentar configuração de deploy;
- garantir que chaves nunca apareçam em logs.

---

## Cache

O cache em disco é útil, mas deve ter política explícita para:

- invalidação;
- versão do dataset;
- tratamento de dados incompletos;
- concorrência;
- ambiente de deploy.

### Evolução possível

```text
Local development → disk cache
Production → Redis / managed cache
```

Não é obrigatório migrar agora; é uma evolução de produção, não uma prioridade inicial.

---

# 11. P2 — Melhorias de UI/UX

A interface atual possui uma identidade visual própria e separação razoável entre dados e texto.

As evoluções mais úteis seriam funcionais, não apenas estéticas.

## Recomendações

### Relatório estruturado

```text
Player Overview
Key Numbers
Style Profile
Strengths
Weaknesses
Closest Archetypes
Tactical Interpretation
Data Sources
```

### Transparência

Exibir:

- temporada;
- número de jogos;
- features usadas;
- tools consultadas;
- indicador de amostra pequena;
- fonte dos dados.

### Comparações

Criar uma visualização que destaque:

- principais semelhanças;
- principais diferenças;
- impacto por grupo de features.

---

# 12. Segurança e robustez

## Pontos positivos atuais

- uso de `.env`;
- `.env.example`;
- ausência de chave diretamente no código;
- tratamento de erros da API;
- cuidado com TLS sem desabilitar verificação.

## Melhorias

### Não confiar em input do LLM sem validação

Toda chamada de tool deve validar:

- schema;
- tipos;
- faixas;
- nomes de temporada;
- tamanho de listas;
- valores inesperados.

### Limitar loops do agente

O `MAX_ITERATIONS` já é uma salvaguarda útil.

Evoluir para limites por:

- número de chamadas;
- tokens;
- tempo;
- custo.

---

# 13. Melhorias de qualidade dos dados

## 13.1 Data contracts

Cada dataset retornado pelas tools deve ter contrato explícito.

Exemplo:

```json
{
  "player": "Victor Wembanyama",
  "player_id": 1641705,
  "season": "2025-26",
  "games_played": 78,
  "per_game": {},
  "shooting": {},
  "source": "NBA Stats"
}
```

### Validações

- valores não negativos onde aplicável;
- percentuais dentro de faixa válida;
- temporada válida;
- `player_id` coerente;
- ausência de campos obrigatórios;
- detecção de datasets vazios.

---

## 13.2 Versionar metodologia

A lógica da similaridade deve carregar uma versão:

```text
similarity_method = "v2"
```

Isso permite comparar resultados após mudanças no algoritmo.

Exemplo:

```json
{
  "similarity_method": "style-v2",
  "features": 28,
  "season": "2025-26"
}
```

---

# 14. Melhorias de documentação

A documentação existente já é uma das partes fortes do projeto.

As próximas adições recomendadas são:

## Arquitetura

Adicionar um diagrama oficial do sistema.

## Dados

Documentar:

- endpoints utilizados;
- frequência de atualização;
- limites conhecidos;
- significado de cada camada;
- limitações históricas.

## Similaridade

Adicionar:

- fórmula da distância;
- motivação dos pesos;
- limitações;
- resultados de validação;
- exemplos de falso positivo/falso negativo.

## Evals

Documentar o benchmark oficial do projeto e preservar resultados por versão.

---

# 15. Estrutura de projeto alvo

Uma possível arquitetura futura:

```text
AgenteNBA/
│
├── app.py
├── README.md
├── requirements.txt
├── .env.example
│
├── agent/
│   ├── planner.py
│   ├── runner.py
│   ├── prompts.py
│   ├── validator.py
│   └── models.py
│
├── tools/
│   ├── __init__.py
│   ├── player_tools.py
│   ├── stats_tools.py
│   ├── comparison_tools.py
│   └── scouting_tools.py
│
├── data/
│   ├── nba_client.py
│   ├── player_repository.py
│   ├── stats_repository.py
│   ├── image_repository.py
│   ├── cache.py
│   └── era.py
│
├── scouting/
│   ├── archetypes.py
│   ├── features.py
│   ├── similarity.py
│   └── matchup.py
│
├── validation/
│   ├── facts.py
│   └── schemas.py
│
├── observability/
│   ├── logger.py
│   ├── metrics.py
│   └── tracing.py
│
├── tests/
│   ├── test_agent.py
│   ├── test_tools.py
│   ├── test_similarity.py
│   └── test_nba_data.py
│
├── eval/
│   ├── dataset.json
│   ├── evaluator.py
│   └── metrics.py
│
└── ui/
    ├── components.py
    └── styles.py
```

Essa estrutura é um alvo de evolução, não uma exigência para a próxima alteração.

---

# 16. Roadmap recomendado

## Fase 1 — Confiabilidade

**Objetivo:** garantir que o que já existe seja testável e confiável.

1. Criar `tests/`.
2. Criar `eval/`.
3. Criar dataset inicial de 30–50 perguntas.
4. Implementar numeric fact checker.
5. Validar tool selection.
6. Adicionar testes de similaridade.
7. Adicionar testes de erro.

### Critério de conclusão

O projeto deve conseguir demonstrar, de forma reproduzível:

- taxa de sucesso;
- taxa de alucinação;
- correção numérica;
- latência;
- custo.

---

## Fase 2 — Modularização

1. Dividir `nba_data.py`.
2. Dividir `tools.py`.
3. Separar modelos/contratos.
4. Centralizar validação.
5. Criar camada de domínio de scouting.

### Critério de conclusão

Nenhum módulo deve concentrar responsabilidades não relacionadas sem justificativa.

---

## Fase 3 — Agentic upgrade

1. Criar intent classifier.
2. Criar Scout Planner.
3. Implementar planos multi-step.
4. Adicionar validação pós-execução.
5. Adicionar fallback/retry orientado por erro.

### Critério de conclusão

O agente deve escolher as ferramentas necessárias de acordo com a natureza da pergunta, e não apenas reagir aos prompts com tool calling genérico.

---

## Fase 4 — Scouting Engine

1. Criar arquétipos.
2. Criar matchup analysis.
3. Criar relatórios estruturados.
4. Criar interpretação tática baseada em features.
5. Adicionar contexto de função/papel.

---

## Fase 5 — Similaridade científica

1. Criar dataset de pares.
2. Obter anotações humanas.
3. Aprender/otimizar pesos.
4. Validar estabilidade.
5. Versionar metodologia.
6. Publicar resultados.

---

## Fase 6 — Produção

1. Observabilidade.
2. Tracing.
3. Cache de produção.
4. Deploy automatizado.
5. CI/CD.
6. Health checks.
7. Limites de custo e uso.

---

# 17. Critérios para considerar o projeto “pronto para portfólio forte”

O projeto deve demonstrar, no mínimo:

### Engenharia

- arquitetura modular;
- tratamento de erros;
- testes automatizados;
- configuração segura;
- documentação de arquitetura.

### AI Engineering

- tool calling;
- planejamento;
- structured outputs;
- validação factual;
- avaliação automatizada;
- observabilidade;
- controle de custo.

### Data/ML

- feature engineering;
- normalização;
- similaridade;
- validação quantitativa;
- metodologia reprodutível.

### Produto

- interface utilizável;
- transparência sobre fonte e temporada;
- relatórios legíveis;
- tratamento de incerteza.

---

# 18. Priorização final

## P0 — Fazer primeiro

- [ ] Criar testes unitários.
- [ ] Criar suíte de evals.
- [ ] Criar numeric fact checker.
- [ ] Testar tool selection.
- [ ] Criar casos de erro e edge cases.

## P1 — Próxima etapa

- [ ] Criar Scout Planner.
- [ ] Modularizar `nba_data.py`.
- [ ] Modularizar `tools.py`.
- [ ] Criar camada de domínio de scouting.
- [ ] Criar arquétipos.
- [ ] Validar pesos da similaridade.
- [ ] Criar dataset de pares para similaridade.

## P2 — Evolução

- [ ] Melhorar cross-era.
- [ ] Adicionar observabilidade.
- [ ] Adicionar tracing.
- [ ] Melhorar cache de produção.
- [ ] CI/CD.
- [ ] Deploy mais robusto.
- [ ] Melhorias de UI focadas em explicabilidade.

---

# 19. Conclusão da auditoria

O ponto central desta auditoria é que o **AgenteNBA não precisa principalmente de mais features**. Ele precisa transformar a boa base atual em um sistema verificável, modular e empiricamente avaliado.

A evolução mais importante é:

```text
Chatbot com tools
       ↓
Agente com planejamento
       ↓
Scouting Engine
       ↓
Fact-checked Agent
       ↓
Sistema avaliado e observável
```

O diferencial técnico mais promissor do projeto é a combinação de:

- dados reais da NBA;
- tools determinísticas;
- algoritmo próprio de similaridade;
- normalização por temporada/era;
- LLM utilizado como camada de interpretação.

A prioridade deve ser preservar essa base e adicionar **confiabilidade, mensuração e profundidade de domínio**, em vez de simplesmente aumentar o número de funcionalidades.

---

## 20. Referência do código auditado

Repositório: https://github.com/murimoraes/AgenteNBA

Arquivos principais considerados na análise:

- `agent.py`
- `app.py`
- `config.py`
- `nba_data.py`
- `tools.py`
- `similarity.py`
- `ui.py`
- `certs.py`
- `requirements.txt`
- `README.md`

**Observação:** este documento registra recomendações técnicas da auditoria realizada nesta sessão. Ele não substitui testes de carga, auditoria de segurança formal ou validação estatística externa do algoritmo de similaridade.
