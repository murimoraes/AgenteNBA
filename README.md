# NBA Scouting Report

Agente de scouting da NBA: responde perguntas sobre jogadores narrando **apenas
dados reais**, buscados por funções Python na API oficial da NBA.

## Princípio arquitetural

O LLM nunca inventa número. Ele não tem acesso a nenhuma estatística por
conhecimento próprio — só ao que as tools retornam. Toda média, aproveitamento e
score de similaridade é calculado em Python e entregue ao modelo como JSON; o
papel dele é interpretar e escrever a análise.

Isso é garantido em três camadas:

1. **System prompt** proíbe explicitamente estimar, arredondar de memória ou
   preencher lacunas.
2. **Tools** devolvem erro estruturado em vez de exceção, para o modelo relatar a
   falha em vez de improvisar.
3. **Interface** monta os cartões a partir dos mesmos resultados de tool, então o
   texto e os números na tela vêm da mesma fonte.

## Arquitetura

```
app.py          Interface Streamlit
ui.py           CSS e componentes HTML (design system do app)
agent.py        Loop de tool use contra o OpenRouter (formato OpenAI)
tools.py        As 5 tools + schemas no formato {"type":"function",...}
similarity.py   Vetor de estilo e similaridade (numpy puro, sem LLM)
nba_data.py     Acesso ao nba_api e ao CDN de imagens, com cache
config.py       Credenciais, modelo e temporada, via .env
certs.py        Compatibilidade TLS com antivírus/proxy que inspecionam HTTPS
```

Orquestração manual, sem LangChain ou similar.

## Provider

Tudo fala o formato OpenAI de ponta a ponta, então o provider é apenas um
`base_url` diferente. **OpenRouter e OpenAI são intercambiáveis sem tocar em
código** — o loop do agente, os schemas de tool e a interface são os mesmos.

O provider ativo é o da chave preenchida no `.env`, com a OpenAI tendo
precedência. Para voltar ao OpenRouter, basta comentar `OPENAI_API_KEY`.

```
# OpenAI
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-4o-mini

# OpenRouter
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=nex-agi/nex-n2.5-mini:free
```

Cada provider tem sua própria variável de modelo porque o formato do id difere:
no OpenRouter é namespaced (`openai/gpt-4o`), na OpenAI é direto (`gpt-4o-mini`).
Assim trocar de provider não exige ajustar também o nome do modelo.

Variáveis avançadas: `LLM_PROVIDER` força um provider quando as duas chaves estão
preenchidas; `LLM_BASE_URL` sobrepõe o endpoint (proxy, Azure OpenAI, gateway).

### Custo na OpenAI

Consumo **medido** em 4 perguntas reais com `gpt-4o-mini` (cada pergunta = 2
chamadas: rodada de tools e rodada de síntese):

| Pergunta | Entrada | Saída | US$ |
|---|---|---|---|
| `stats` | 2.327 | 599 | 0,00071 |
| `similar` | 2.454 | 353 | 0,00058 |
| `recentes` | 2.685 | 678 | 0,00081 |
| `trap` | 2.210 | 63 | 0,00037 |
| **Total** | **9.676** | **1.693** | **0,00247** |

Média de **US$ 0,00062 por pergunta** — US$ 5 dão ~8.000 perguntas. Extrapolando
o mesmo consumo para outros modelos:

| Modelo | US$/pergunta | Perguntas com US$ 5 |
|---|---|---|
| `gpt-4o-mini` | 0,00062 | ~8.100 |
| `gpt-5-mini` | 0,00145 | ~3.400 |
| `gpt-4o` | 0,01028 | ~490 |

Diferente do OpenRouter gratuito, a API da OpenAI não tem teto diário de
requisições — cobra por token.

### Escolha do modelo

Como o projeto proíbe o LLM de inventar número, a métrica que decide o modelo é
**fidelidade numérica**: cada número da resposta é extraído e conferido contra o
retorno das tools. Benchmark de 2026-09-21, pergunta `stats` ("Como foi a
temporada 2025-26 do Victor Wembanyama?"), sobre 20 modelos `:free` com suporte a
`tools` (16 responderam) mais o `gpt-4o-mini` como referência paga:

| Modelo | Fidelidade | Latência | Observação |
|---|---|---|---|
| `gpt-4o-mini` (pago) | 100% | 18s | mais confiável; escreve como dump de dados |
| `nex-agi/nex-n2.5-mini:free` | 100% | 11s | **melhor gratuito** — pt-BR e leitura tática |
| `poolside/laguna-s-2.1:free` | 100% | 22s | mais detalhado, 2× mais lento |
| `liquid/lfm-2.5-2.6b:free` | 100% | 7s | mais rápido, português fraco |
| `nvidia/nemotron-3-ultra-550b:free` | 87,5% | 123s | inventa dados; evitar |
| `cohere/north-mini-code:free` | 80% | 15s | pior fidelidade |

O `gpt-4o-mini` foi o único submetido às 4 perguntas do protocolo — os gratuitos
só à `stats`, porque a cota diária do OpenRouter acabou. Resultado nas 4: **100%
de fidelidade em todas**, zero emoji, e passou na pergunta-armadilha (o salário do
LeBron, que nenhuma tool fornece) admitindo não ter o dado em vez de inventar.

Duas diferenças de comportamento observadas entre os dois recomendados:

- O `gpt-4o-mini` **não chamou `get_player_image` em nenhuma das 4 perguntas**,
  apesar do system prompt pedir. A foto aparece assim mesmo, porque a garantia é
  determinística em `agent.py` (`_ensure_images`) e não depende do modelo — é
  justamente para isso que ela existe.
- Em estilo, o `gpt-4o-mini` lista os números de forma exaustiva e só depois
  analisa; o `nex-n2.5-mini` integra o número à leitura tática, que é mais
  próximo de um relatório de olheiro.

### Limite do tier gratuito

A conta sem créditos tem **50 requisições/dia** em modelos `:free`, com teto de
**20 requisições/minuto**. Cada pergunta consome 2–3 requisições (tool use é
multi-turno), ou seja **~15–25 perguntas por dia**. Ao estourar, a API devolve
`429 free-models-per-day`.

Comprar US$ 10 em créditos eleva o teto para **1000/dia**. Dois detalhes que
importam: os créditos **não são consumidos** por modelos `:free`, e o tier é
definido pelo **total comprado ao longo da vida da conta**, não pelo saldo atual —
ou seja, o limite maior permanece mesmo com saldo zerado.

Checar a cota:

```bash
curl -H "Authorization: Bearer $OPENROUTER_API_KEY" https://openrouter.ai/api/v1/key
```

## Tools

| Tool | O que faz |
|---|---|
| `get_player_season_stats` | Médias e totais de uma temporada, com TS% |
| `get_recent_games` | Box scores recentes + médias do recorte |
| `compare_players` | Similaridade de estilo (par ou ranking de semelhantes) |
| `get_player_bio` | Posição, físico, time, draft, origem |
| `get_player_image` | Headshot oficial padronizado em 1040×760 |

### Similaridade de estilo

**Estilo é forma, não tamanho.** Dois jogadores não são parecidos por marcarem
muito — são parecidos por marcarem do mesmo jeito, dos mesmos lugares, criando da
mesma maneira. Por isso o vetor é dominado por features de **composição** (frações
que somam 1, taxas por posse), e magnitude de produção entra com peso baixo.

**28 indicadores em 8 grupos**, com os pesos escolhidos para refletir isso:

| Grupo | Peso | Indicadores |
|---|---|---|
| Perfil de arremesso | **2,0** | % de tentativas por zona (garrafão restrito, garrafão, meia-distância, 3 do canto, 3 acima da linha), LL por arremesso |
| Criação | 1,3 | drives/36, % em pull-up, % em catch & shoot, toques de post/36 |
| Organização | 1,3 | AST%, AST/TOV, AST% por unidade de uso, passes/36 |
| Defesa | 1,1 | roubos/36, tocos/36, arremessos no aro defendidos/36, FG% do adversário no aro, deflexões/36, contestados/36 |
| Rebote | 0,9 | OREB%, DREB% |
| Papel | 0,9 | Usage% (opção primária × coadjuvante) |
| Físico | 0,8 | altura, peso |
| **Produção** | **0,35** | PTS/36, FGA/36, TS% — deliberadamente baixo |

Cada feature vira z-score contra a população da própria temporada (mín. 10 jogos e
10 min/jogo), e a comparação é distância euclidiana + cosseno.

**A escala 0–100 é calibrada pela distribuição real de pares da liga** (97.020
pares em 2025-26): o valor é a fração dos pares que estão *mais distantes* que a
dupla analisada. Então 50 significa "tão parecidos quanto dois jogadores
quaisquer", e acima de 85 significa mesmo arquétipo. Isso substitui o percentil
anterior, que sempre dava ~99 para o vizinho mais próximo mesmo quando ele estava
longe.

Exemplos verificados em 2025-26:

| Dupla | Semelhança |
|---|---|
| Curry × Donovan Mitchell | 99,4 |
| Gobert × Steven Adams | 93,5 |
| Westbrook × Derrick Rose (2010-11) | 89,8 |
| Jokić × Şengün | 77,0 |
| Curry × Trae Young | 67,1 |
| Jokić × Giannis | 51,6 |
| Curry × Gobert | 0,6 |

Nenhuma chamada ao modelo nessa etapa.

### Comparações históricas e entre temporadas

Os dados vão até **1996-97**, mas nem toda fonte existe em toda era:

| Camada | Desde | Conteúdo |
|---|---|---|
| `core` | 1996-97 | box score, advanced, zonas de arremesso, físico |
| `tracking` | 2013-14 | drives, defesa no aro, pull-up, catch & shoot, post, passes |
| `hustle` | 2015-16 | deflexões, contestados, box-outs |

`compare_players` aceita `season_a` e `season_b` distintos, para comparar auges de
eras diferentes. Cada jogador é normalizado contra a liga do **próprio ano**, então
o resultado já sai ajustado por era; a comparação usa a **interseção** das camadas
e declara quantos indicadores entraram. `cross_era=True` no modo `similar` busca
análogos em temporadas históricas.

Quando o jogador não atuou na temporada pedida, a tool cai para a mais recente dele
e avisa — em vez de sumir do resultado silenciosamente.

### Imagem do jogador

Endpoint verificado por teste real, não assumido:

```
https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png
```

Todos os jogadores retornam 1040×760 — mesma resolução e proporção. **Detalhe que
exige cuidado:** um `player_id` inexistente devolve **HTTP 200**, não 404, com um
corpo byte-a-byte idêntico ao `fallback.png` do próprio CDN. Por isso a detecção
de "sem foto" é feita por hash SHA-256 do conteúdo; quando bate com o fallback, a
interface desenha um monograma em vez da silhueta genérica.

## Instalação

```bash
pip install -r requirements.txt
cp .env.example .env    # e preencha OPENROUTER_API_KEY
streamlit run app.py
```

A chave sai de [openrouter.ai/keys](https://openrouter.ai/keys).

### Rede com inspeção TLS

Antivírus (Norton, Kaspersky, ESET) e proxies corporativos substituem o
certificado dos sites por um emitido por uma CA própria, instalada no Windows. O
`requests` não lê esse store e falha com `CERTIFICATE_VERIFY_FAILED`. O
`certs.py` resolve montando um bundle `certifi` + raízes do Windows — **sem
desligar a verificação**. Em Linux/macOS a função detecta que o padrão já
funciona e não faz nada.

Se precisar apontar um bundle próprio: `NBA_CA_BUNDLE=C:\caminho\ca-bundle.pem`.

## Interface

Paleta de dois acentos (laranja de quadra `#BF4417`, verde-petroleo `#17383A`)
sobre neutros quentes. Títulos em Newsreader, dados em Inter com numerais
tabulares. Espaçamento em grid de 8px. Sem emoji e sem glassmorphism.
