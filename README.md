# CyberGuard

Plataforma acadêmica de monitoramento e investigação de eventos de cibersegurança para a V3 de Banco de Dados NoSQL da UNIFOR. O objetivo é comparar Apache Cassandra e PostgreSQL usando o mesmo conjunto lógico de eventos, consultas equivalentes e experimentos reproduzíveis.

As Tasks 01 e 02 entregam infraestrutura local, API de saúde, interface de conectividade, modelo de eventos, esquemas SQL/CQL e CRUD equivalente com consultas Q1/Q2/Q3, além de uma amostra sintética de 24 eventos. A Task 03 acrescenta massa volumosa determinística (até 1 milhão de eventos lógicos), carga retomável via API e validação integral nos dois bancos ([docs/bulk-load.md](docs/bulk-load.md)). Indicadores definitivos e benchmarks comparativos ainda não foram implementados.

## Stack e organização

| Área | Tecnologia / responsabilidade |
| --- | --- |
| `frontend/` | Svelte 5, TypeScript e Vite, sem SvelteKit |
| `backend/` | Rust, Axum e Tokio; monólito modular |
| `database/cassandra/` | Apache Cassandra 5.0.9; registro canônico por ID e projeções por consulta |
| `database/postgresql/` | PostgreSQL 17.11; eventos tipados, dispositivos, reserva de IDs e índices |
| `scripts/` | Python: preparação, futura geração, carga e validação |
| `benchmarks/` | Protocolos e resultados reais, separados das consultas de negócio |
| `data/` | Amostras pequenas versionáveis e massa gerada ignorada |
| `docs/` | Arquitetura, requisitos, entregas e verificação |

Fluxo inicial: navegador → proxy Vite `/api` → Axum → consultas reais em PostgreSQL/Cassandra. O frontend nunca recebe credenciais nem acessa os bancos diretamente.

## Pré-requisitos no Windows

- Git, Python 3.11+ e Node.js 22.17+ com npm. Este bootstrap usa Vite 6 para funcionar com o Node 22.17.1 encontrado, sem atualização global.
- Rust estável atual, Cargo e ferramentas de compilação C++ do Visual Studio (toolchain MSVC no Windows). Depois de instalar, abra outro terminal e confirme `rustc --version` e `cargo --version`.
- Docker Desktop em modo de contêineres Linux, com backend WSL 2 em funcionamento.
- Portas locais 3000, 5173, 9042 e 5432 disponíveis.
- Máquina de referência: Windows, 16 GB de RAM. Os limites dos bancos somam 7 GiB, além do overhead do Docker/WSL, SO, compilador e navegador. Não são reservas de RAM nem garantia de desempenho.

Os resultados efetivamente executados estão nos relatórios [Task 01](docs/verification-task01.md), [Task 02](docs/verification-task02.md) e [Task 03](docs/verification-task03.md). Não confundir instruções reproduzíveis abaixo com verificações já executadas.

## Inicialização (PowerShell, a partir da raiz)

1. Prepare o ambiente local sem imprimir a senha:

   ```powershell
   python scripts/setup_env.py
   ```

   O script gera `.env` com senha aleatória, preservando um `.env` existente. Nunca coloque segredos em variáveis `VITE_*`. `.env.example` contém apenas valores públicos e um marcador de senha.

2. Com Docker Desktop iniciado:

   ```powershell
   docker compose config --quiet
   docker compose up -d --wait --wait-timeout 720
   docker compose ps
   ```

   Cassandra pode demorar vários minutos no primeiro boot. Use `docker compose logs --tail 80 cassandra` para diagnóstico local. `config --quiet` valida sem imprimir as credenciais interpoladas; evite compartilhar a saída de `docker compose config` sem essa opção.

3. Aplique os esquemas aditivos aos bancos já saudáveis:

   ```powershell
   python scripts/apply_schema.py
   ```

   O script executa `database/postgresql/001_events.sql` e `database/cassandra/001_events.cql`. Pode ser repetido; preserva tabelas, dados e volumes. `IF NOT EXISTS` não é um migrador de alterações futuras: novas versões exigem migrações explícitas, nunca remoção de tabelas para corrigir divergências. Se o executor não puder ler o perfil Docker, use `python scripts/apply_schema.py --docker-config tmp/docker` com um diretório de configuração local existente.

4. Em um terminal na raiz, inicie a API:

   ```powershell
   cargo run --manifest-path backend/Cargo.toml
   ```

   Também é possível executar `cargo run` dentro de `backend/`: dotenvy procura `.env` no diretório corrente e em seus pais. Variáveis já definidas no processo têm precedência. A API usa `127.0.0.1:3000`; ela pode iniciar com bancos desligados. A ausência de configuração válida impede a inicialização com uma mensagem sem segredos.

5. Em outro terminal:

   ```powershell
   Set-Location frontend
   npm.cmd ci
   npm.cmd run dev
   ```

   Abra `http://localhost:5173`. `npm.cmd` evita o bloqueio de `npm.ps1` por ExecutionPolicy, sem mudar o sistema. Vite encaminha `/api` para `127.0.0.1:3000`. A navegação mostra áreas preparadas e o botão **Verificar conexões** consulta os serviços novamente. A porta é estrita: Vite falha se 5173 estiver ocupada, em vez de mudar silenciosamente.

## Verificação

```powershell
git status --short
git check-ignore -v -- *.pdf .env data/generated/example.csv
docker compose config --quiet
docker compose ps
cargo fmt --manifest-path backend/Cargo.toml --check
cargo test --manifest-path backend/Cargo.toml
cargo build --manifest-path backend/Cargo.toml
npm.cmd --prefix frontend run build
python scripts/validation/check_foundation.py
python scripts/validation/check_api.py
python scripts/validation/test_integration.py
python scripts/validation/test_recovery.py
python scripts/validation/check_sample.py
```

`backend/Cargo.lock` e `frontend/package-lock.json` fixam as dependências efetivamente resolvidas. Use `cargo build --locked` / `cargo test --locked` e `npm.cmd ci` para reproduzir as mesmas versões.

### Alternativa sem Rust instalado no Windows

Com Docker ativo, execute da raiz. O contêiner é temporário; dependências ficam em `tmp/cargo/`, artefatos em `backend/target/` e o código é montado a partir deste projeto. Não instala toolchain no Windows.

```powershell
$projectPath = (Get-Location).Path
docker run --rm --name cyberguard-rust-check --mount "type=bind,source=$projectPath,target=/workspace" --workdir /workspace/backend --env CARGO_HOME=/workspace/tmp/cargo rust:1.99.1-slim-bookworm sh -c 'rustup component add rustfmt && cargo fmt --check && cargo test --locked && cargo build --locked'
```

Depois da compilação, para executar a API (mantenha esse terminal aberto):

```powershell
docker run --rm --name cyberguard-api-local --network cyberguard_storage --publish 127.0.0.1:3000:3000 --mount "type=bind,source=$projectPath,target=/workspace,readonly" --workdir /workspace --env-file .env --env API_BIND=0.0.0.0:3000 --env POSTGRES_HOST=postgresql --env CASSANDRA_CONTACT_POINT=cassandra:9042 rust:1.99.1-slim-bookworm /workspace/backend/target/debug/cyberguard-api
```

Não execute simultaneamente a API nativa e essa alternativa na mesma porta. Para encerrar por outro terminal: `docker stop --signal SIGINT cyberguard-api-local`. Os bancos continuam gerenciados pelo Compose e seus volumes não são removidos. Artefatos Linux não são executáveis Windows; use `cargo build` nativo para gerar o binário Windows.

| Endpoint | Contrato |
| --- | --- |
| `GET /api/health` | HTTP 200, `status: ok`, serviço e versão; prova somente que a API responde |
| `GET /api/health/storage` | HTTP 200 se ambos respondem; HTTP 503 se algum falha; resultados individuais `cassandra` e `postgresql` |

Cada banco retorna `status` (`up`/`down`), `duration_ms` e `error` (código ou `null`). A resposta recebe `Cache-Control: no-store`. As sondagens são concorrentes, com timeout independente de 5 segundos (configurável entre 100 e 10000 ms). A duração inclui estabelecimento e encerramento da conexão: **não é um benchmark de consultas**. Falhas de conexão/consulta não são sucesso e não vazam a mensagem bruta do driver.

`check_api.py` retorna código 1 se a API não responder ou alguma fonte falhar. Os testes Rust cobrem health, timeout, CORS, validação do domínio e limites das consultas. `test_integration.py` exige API e schemas ativos e cria/exclui somente seus próprios UUIDs sintéticos; usa a janela reservada `2001-11-06` a `2001-11-09` e recusa dados preexistentes de alerta nessa janela. UUIDs excluídos permanecem reservados. `test_recovery.py` injeta estados interrompidos em um único UUID novo e verifica repair, sem afetar os demais eventos. Os dois scripts que consultam Docker aceitam `--docker-config tmp/docker`. `check_sample.py` exige a amostra carregada e sem alterações.

## Amostra e uso do CRUD

Com os esquemas preparados e a API ativa:

```powershell
python scripts/generation/generate_sample.py
python scripts/loading/load_sample.py
python scripts/validation/check_sample.py
```

O gerador produz exatamente 24 eventos determinísticos e seu manifesto em `data/samples/`; não é gerador de massa volumosa. A carga usa os mesmos objetos nos dois bancos. Repetir a carga retorna os eventos idênticos sem duplicação. Se a amostra tiver sido atualizada/excluída, o carregador falha em vez de sobrescrever ou ressuscitar UUIDs.

| Operação | Endpoint | Resultado |
| --- | --- | --- |
| CREATE | `POST /api/{source}/events` | 201 novo; 200 repetição idêntica; 409 conflito |
| READ | `GET /api/{source}/events/{id}` | 200 envelope `data` + `revision`; 404 ausente/excluído |
| UPDATE | `PUT /api/{source}/events/{id}` | 200; exige revisão e apenas campos mutáveis |
| DELETE | `DELETE /api/{source}/events/{id}?expected_revision=N` | 204; revisão antiga 409; UUID desconhecido 404 |
| Recuperação | `POST /api/{source}/events/{id}/repair` | 200 estado active/deleted; conclui pendências Cassandra |
| Q1 | `GET /api/{source}/queries/device` | `device_id`, `from`, `to`, `page_size`, `cursor` |
| Q2 | `GET /api/{source}/queries/ip` | `source_ip`, `from`, `to`, `page_size`, `cursor` |
| Q3 | `GET /api/{source}/queries/alerts` | `severity` exata, `from`, `to`, `page_size`, `cursor` |

`source` é `postgresql` ou `cassandra`; cada chamada opera em somente um banco. Datas UTC, janela `[from,to)`, no máximo sete datas, páginas de 1..100 eventos. IDs são UUID v4. Mensagem, resultado e metadados são mutáveis; demais campos são imutáveis. Consulte [contrato/modelos](docs/data-model.md), [SQL/CQL e paginação](docs/query-patterns.md) e [consistência/recuperação](docs/consistency.md).

Exemplo PowerShell de CRUD com um evento **novo**, sem modificar a amostra versionada:

```powershell
$api = 'http://127.0.0.1:3000'
$source = 'postgresql' # repita com cassandra usando o mesmo corpo/UUID para comparar
$event = @{
  event_id = [guid]::NewGuid().ToString()
  occurred_at = '2026-11-09T10:00:00.000Z'
  event_date = '2026-11-09'
  device_id = 'manual-sensor-01'
  source_ip = '192.0.2.50'
  category = 'authentication'
  event_type = 'login'
  severity = 2
  outcome = 'failure'
  message = 'Synthetic login for CRUD validation'
  metadata = @{ synthetic = $true; source = 'manual-example' }
}
$json = $event | ConvertTo-Json -Depth 10 -Compress
$created = Invoke-RestMethod -Method Post -Uri "$api/api/$source/events" -ContentType 'application/json' -Body $json
$id = $created.data.event_id
Invoke-RestMethod -Uri "$api/api/$source/events/$id"
$update = @{ expected_revision = 1; outcome = 'failure'; message = 'Reviewed synthetic login'; metadata = @{ synthetic = $true; reviewed = $true } } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Put -Uri "$api/api/$source/events/$id" -ContentType 'application/json' -Body $update
Invoke-RestMethod -Method Delete -Uri "$api/api/$source/events/${id}?expected_revision=2"
```

Depois do DELETE, READ retorna 404 e o UUID não pode ser reutilizado. O PowerShell lança erro para respostas HTTP 400/404/409/503; esses códigos fazem parte do contrato. Falha/timeout de escrita pode ter resultado incerto: consultar o mesmo ID ou executar repair antes de repetir; nunca trocar UUID silenciosamente.

Consulta sobre a amostra:

```powershell
Invoke-RestMethod 'http://127.0.0.1:3000/api/cassandra/queries/alerts?severity=4&from=2026-11-06T00:00:00Z&to=2026-11-09T00:00:00Z&page_size=2'
```

Use o `next_cursor` retornado e preserve os outros parâmetros para continuar. O frontend permanece na interface de conectividade da Task 01: não apresenta um dashboard definitivo nem métricas inventadas.

## Ambiente local e persistência

- Portas dos bancos publicadas somente em `127.0.0.1`, em rede Docker bridge dedicada. Não se usa `internal: true`: a verificação no Engine 29 mostrou que essa opção impedia publicar as portas no host. A rede separa os serviços do projeto das outras redes Docker, mas permite tráfego de saída. API e Vite no host também usam loopback por padrão; a API em contêiner precisa escutar em `0.0.0.0` internamente, sempre com publicação somente em `127.0.0.1`.
- Cassandra utiliza `AllowAllAuthenticator`/`AllowAllAuthorizer` padrão da imagem: **sem autenticação, exclusivamente neste laboratório local**. PostgreSQL usa senha aleatória e SCRAM para conexões de host; o usuário de bootstrap é administrador local. TLS está desativado nas conexões locais. Nada disso é configuração de produção.
- CORS aceita uma única origem local explícita de `FRONTEND_ORIGIN`, sem wildcard. Se acessar a API diretamente a partir de `http://127.0.0.1:5173`, ajuste essa variável. No fluxo normal, o proxy Vite mantém a mesma origem do navegador.
- Cassandra: limite 5 GiB e heap 2 GiB via `MAX_HEAP_SIZE`, sem `HEAP_NEWSIZE` com G1. PostgreSQL: limite 2 GiB, `shared_buffers=512MB` e memória compartilhada de 512 MiB.
- Credenciais de inicialização do PostgreSQL só se aplicam a um volume novo. Trocar `.env` não altera automaticamente a senha de um banco já inicializado.
- Os volumes nomeados persistem dados. Para parar sem removê-los:

  ```powershell
  docker compose stop
  ```

  Use Ctrl+C nos terminais da API e do frontend. Para voltar: `docker compose start`. `docker compose down` também preserva os volumes por padrão, mas **não use `down -v`, `volume rm` nem `prune`**.

## Próximas entregas

Leia [requisitos](docs/requirements.md), [arquitetura](docs/architecture.md) e [cronograma](docs/entregas/README.md). A massa volumosa da Task 03 está documentada em [bulk-load.md](docs/bulk-load.md) e verificada em [verification-task03.md](docs/verification-task03.md). A Task 04 deve definir o protocolo de benchmark comparativo (≥10 execuções por operação, aquecimento/cache, recursos e versões) sobre essa mesma massa, sem confundir tempos de carga com benchmark.

Referências técnicas verificadas: [imagens Cassandra](https://github.com/docker-library/official-images/blob/master/library/cassandra), [imagens PostgreSQL](https://github.com/docker-library/official-images/blob/master/library/postgres), [Scylla Rust Driver](https://rust-driver.docs.scylladb.com/stable/quickstart/example.html), [Axum](https://docs.rs/axum/0.8.6/axum/), [Svelte](https://svelte.dev/docs/svelte/overview). As tags são explícitas; antes de atualizar, revisar compatibilidade e repetir os checks.
