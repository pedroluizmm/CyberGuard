# Task 05: testes completos, redesign do frontend e apresentação final em PDF

Data: 17/11/2026. O fluxo seguiu READ → PLAN → APPLY → VERIFY.

- **Preservado:** não houve commit nem push. PDFs originais, `.env`, volumes, a massa de 1 M e os resultados de `benchmarks/results/` ficaram intactos.
- **Benchmarks:** nenhum foi reexecutado. Os resultados existentes foram verificados a partir dos arquivos brutos.

## 1. Sistema antes do redesign

| Comando ou cenário | Resultado real |
| --- | --- |
| `docker version`, `docker compose ps`, `docker compose config --quiet` | Engine 29.4.3; Cassandra e PostgreSQL *healthy*; portas só em 127.0.0.1; Compose válido |
| `docker volume inspect` | Os dois volumes com `CreatedAt` de 2026-11-09T05:06:41Z (não recriados) |
| `python scripts/run_api.py start` | API 0.1.0 release (binário mais novo que todo o código-fonte do backend) |
| `cargo fmt --check`, `cargo test --locked`, `cargo build --locked` (contêiner `rust:1.99.1-slim-bookworm`) | OK; **10/10** testes; build sem erros |
| `check_api.py` | API e os dois bancos responderam a consultas reais; CORS restrito |
| `check_foundation.py` | **44/44** |
| `test_integration.py` | **10/10** (CRUD, Q1–Q3, paginação, limites, painel equivalente, rollup seguindo o CRUD, instrumentação) |
| `test_recovery.py`, `check_sample.py`, `test_bulk_generator.py` | OK; amostra de 24 eventos e Q1 = 15, Q2 = 12, Q3 = 6 iguais; 5/5 |
| `reconcile_rollup.py` (simulação) | 0 diferenças; PostgreSQL = verdade do Cassandra = contadores (1 000 024 eventos, 9 978 células) |
| `check_bulk.py --target 1000000` | **22/22** (`data/bulk/reports/validate-1000000-20261117T032233Z.json`) |
| Teste ponta a ponta próprio, pela API (fora do repositório) | 61 verificações (ver abaixo) |

O teste ponta a ponta próprio cobriu:

- **Paginação:** 5 páginas de 100 eventos para Q1 (2 dispositivos), Q2 e Q3, iguais e ordenadas nos dois bancos.
- **Painel:** idêntico em 6 combinações de filtro; total da janela 05/10–01/11 = 1 000 000 nos dois bancos.
- **Erros:** 404/400 nos casos inválidos.
- **CRUD completo nos dois bancos,** com UUID novo na janela isolada 2001-05-15: 201 → retry 200 → conflito 409 → READ → UPDATE rev 2 → revisão velha 409 → campo imutável 400 → DELETE 204 → READ 404 → reuso do UUID 409. O painel da janela voltou a 0.
- **Correção no próprio teste:** a primeira execução falhou porque o corpo usava um `event_type` inválido (400 da API, nada gravado).

### Benchmarks (integridade verificada sem reexecução)

Recalculei a partir de `raw.csv` e `raw_writes.csv` as contagens, os status, as medianas, os vencedores, as razões e a equivalência por par, e comparei com `run.json` e `summary.json`.

- **`…053008Z-main` (E1–E5):** 30 medições + 5 aquecimentos por operação e banco, todos 200; 9/9 operações com resposta idêntica.
- **E4, painel de 7 dias:** PG 71,936 × CS 3,284 ms = **21,9×**. A metodologia, o README e os slides o descrevem como rollup pré-agregado × agregação na leitura, e não como superioridade geral do Cassandra.
- **E5:** view materializada 1,145 ms; REFRESH 281,988 ms; agregação na leitura 73,725 ms (psql).
- **`…052908Z-n1`:** confere.
- **`…202129Z-writes` e `…202202Z-durability` (E6):** 0 status inesperados; limpeza 0/0. CREATE PG 13,182 × CS 10,816 ms (padrão) e 5,829 × 9,466 ms (confirmação antes do fsync).

Conclusão: **tudo consistente.**

## 2. Redesign do frontend

| Arquivo | Mudança |
| --- | --- |
| `frontend/src/app.css` | Tokens da nova paleta (fundo `#101217`, sidebar `#15181E`, cards `#1D2129`, bordas `#303640`, azul-acinzentado `#7188AD`, turquesa `#08A6B9`), componentes globais (botões, chips, segmented, badges, tabelas, skeleton) e `prefers-reduced-motion` |
| `frontend/src/App.svelte` | Shell com sidebar (grupos Monitoramento/Análise, serviços, nota dos dados), topo com trilha, título e seletor de fonte, barra de filtros comum, navegação por hash (`#visao-geral`, `#investigacao`, `#comparacao`, `#benchmarks`), link "pular para o conteúdo" e foco no título ao trocar de seção. Layout de tablet e celular |
| `frontend/src/lib/OverviewView.svelte` (novo) | Consulta do painel extraída do `App`: KPIs (destaque, alertas, críticos, tempo com atalho ↗ para a comparação), série horária, volume diário (ou por hora em 1 dia), severidade, categorias e atividade (pico, média/h, dia mais ativo, pico ÷ média), todos derivados da resposta real |
| `frontend/src/lib/VolumeBars.svelte`, `Icon.svelte` (novos) | Barras com destaque no maior valor e tooltip; conjunto mínimo de ícones de linha, sem biblioteca |
| `EventExplorer.svelte` | Painel de detalhes do evento (todos os campos e metadados) e READ por UUID que compara o conteúdo com o item da página |
| `LiveCompare.svelte` | Seção própria: cartões lado a lado, veredito com razão e equivalência, marcas por execução e tabela por par |
| `BenchmarkPanel.svelte`, `BenchmarkChart.svelte` | Destaques calculados do `summary.json`, protocolo, gráfico log com forma por banco, tabelas E5/N+1/E6 e limitações |
| `TimelineChart`, `SeverityBars`, `CategoryShare`, `api.ts`, `format.ts`, `index.html`, `favicon.svg` | Novo estilo; `getEvent`, `canonicalJson`, `SOURCE_ICON`; formatação de período; arredondamento de ms pelo valor binário |

A API não foi alterada.

### Cores validadas com o validador de paletas (sobre `#1D2129`)

- **Azul-acinzentado × turquesa reprovou** como par de dados: croma 0,06 e ΔE 9,8 em visão normal. O azul-acinzentado ficou só na interface.
- **Bancos:** PostgreSQL violeta `#9085e9` × Cassandra turquesa `#08a6b9`. ΔE 16,4 em visão normal; 7,8 em deuteranopia, faixa de aviso. Por isso há codificação secundária: rótulo de texto e forma (círculo × losango).
- **Categorias:** slots documentados (todos os pares passam).
- **Severidade:** rampa ordinal de um matiz (`#6d504a` a `#ff9079`), luminosidade monotônica, extremo claro com 2,23:1.
- **Texto e selos:** texto secundário 6,96:1 e "muted" 5,21:1. Selos de severidade com texto claro (1–2) ou escuro (3–5), todos ≥ 4,5:1.

## 3. Testes depois do redesign

| Comando ou cenário | Resultado real |
| --- | --- |
| `npm.cmd --prefix frontend run build` (svelte-check + tsc + Vite) | **0 erros, 0 avisos** (206 arquivos); build OK |
| `check_api.py`, `test_integration.py`, `check_sample.py` (após paradas e retomadas) | OK; **10/10**; OK |
| Navegador (Chrome, Vite dev) · Visão geral | Dados reais nas duas fontes; troca de fonte; filtros Alerta + sev. 5 = 1 842 nos dois bancos; severidades fora do filtro esmaecidas; 1 dia → "Volume por hora" |
| Navegador · Investigação | Q2 `2001:db8:bad:4::6`: páginas 1 → 2 → 1 e troca para PostgreSQL com os mesmos eventos; detalhe do evento; READ por ID "idêntico ao item da página" |
| Navegador · Comparação | Painel agregado, 10 repetições: **Cassandra 11,7×** e 11,1× (iframe de 390 px), resultado idêntico |
| Navegador · Benchmarks | Destaques, protocolo, gráfico, tabelas, E5/N+1/E6 com os números do `summary.json` |
| API parada | API "indisponível", bancos "não verificado" (neutro), "A API local não está acessível" na visão geral e na investigação, "Comparação interrompida", "Resultados indisponíveis" |
| `docker compose stop postgresql` → `start` | Banner e sidebar com PostgreSQL indisponível, `storage_unavailable` sem dados; Cassandra seguiu conectado. Na volta, o pool reconectou sem reiniciar a API; 1ª consulta do painel no PG com cache frio: 3,1 s, depois 81 ms |
| Responsividade (iframes de mesma origem, 820 e 390 px) | Sem rolagem horizontal; navegação, KPIs, gráficos, comparação e benchmarks reorganizados |
| Teclado | Foco visível (contorno turquesa) em navegação, chips e controles; gráfico horário navegável por setas |
| Console | Sem erros nem avisos do app |

### Falhas encontradas e corrigidas

- O atalho "Comparar nos dois bancos" sobrepunha o título do card de tempo e virou um botão circular ↗.
- O gráfico de volume deixava um vazio e teve a altura ajustada.
- A barra de filtros fixa cobria a tabela ao rolar e deixou de ser fixa.
- A fonte Cascadia Mono ficava pesada em 12 px; Consolas passou a vir antes.
- A razão "4×" aparecia sem casa decimal e agora é exibida como "4,0×".
- No celular, o item "Benchmarks" ficava cortado na navegação.
- No protocolo dos benchmarks, sobrava uma célula vazia em 820 px.
- O texto "Tempo limite excedido" era truncado na sidebar.
- **Erro de mensagem pré-existente:** a investigação culpava o banco ("Cassandra indisponível") quando quem estava fora do ar era a API. Agora os dois casos são distintos.
- **Arredondamento:** a mediana 3,735 ms aparecia como 3,74 (o `Intl` arredonda o empate para cima) e a metodologia registra 3,73. O formatador passou a usar `toFixed`, que arredonda pelo valor binário, como o Python.

### Limitações desta verificação

- A janela do Chrome não pôde ser redimensionada (maximizada pelo SO). Tablet e celular foram testados em iframes de 820 e 390 px, que aplicam as media queries, mas não emulam toque nem densidade de pixels.
- O estado "não verificado" foi observado com a API parada. O caso em que a API responde mas a sonda de armazenamento falha não foi provocado.

## 4. Apresentação em PDF

| Item | Resultado |
| --- | --- |
| Arquivo | `docs/apresentacao/CyberGuard_Apresentacao_Final.pdf`, gerado por `python docs/apresentacao/build_pdf.py` (Chrome headless) a partir de `slides.html` |
| Páginas e formato | **16 páginas, 960 × 540 pt (16:9)**, verificado com pypdf; fontes incorporadas (Bahnschrift, Segoe UI, Consolas) |
| Texto cortado | Verificação no DOM a 1280 × 720 dos 16 slides: nada fora do slide, nada cortado, nada encostado no rodapé |
| Números | **38 valores** do PDF (texto extraído) conferidos com `summary.json`, o manifesto e os relatórios de carga e validação: todos presentes |
| Inspeção visual | Páginas renderizadas com PyMuPDF e revisadas |
| Identidade | Fundo branco, turquesa `#08a6b9`/`#087f8f`, texto grafite `#2b3036`, títulos condensados em caixa alta, aba de seção numerada |
| Contraste | Branco sobre `#087f8f` = 4,73:1; par violeta × turquesa aprovado no validador sobre branco |
| Imagem | `docs/apresentacao/img/dashboard-visao-geral.png`, captura real da nova interface (Chrome headless contra a API em execução) |

Correções feitas após a inspeção:

- O caminho de escrita do slide 5 sugeria "SSTables → flush → compactação" e virou uma sequência numerada correta.
- As setas ganharam ponta.
- No diagrama da arquitetura, os scripts passaram a apontar para a API.
- O título longo do slide 10 foi encurtado.
- O gráfico do slide 12 foi alinhado ao cabeçalho.
- Os bancos foram nomeados em "5,8 ms × 9,5 ms".

Os roteiros foram atualizados: `roteiro-apresentacao.md` traz falas por slide e sugestão de divisão entre os integrantes; `roteiro-demo.md` segue a nova navegação.

## Pendências reais

- Validação formal do SGBD pelo professor (exigida no PDF): sem evidência no repositório.
- O nome do professor não aparece nos documentos e não foi colocado na capa.
- 5 M de eventos, múltiplos nós e cache frio continuam fora do escopo, como já documentado.
