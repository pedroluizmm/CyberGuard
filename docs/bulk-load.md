# Massa volumosa: geração, carga e validação (Task 03)

Este documento descreve **como** a massa é produzida, carregada e conferida. Os resultados efetivamente medidos (tempos, contagens, tamanhos, recursos) estão em [verification-task03.md](verification/verification-task03.md) e nos relatórios JSON de `data/bulk/reports/`.

## Registro lógico e linha física

- **Evento lógico**: um UUID com o contrato da [Task 02](data-model.md). É a unidade contada como "1 milhão de eventos".
- **PostgreSQL**: 1 linha em `events` + 1 reserva em `event_registry` por evento; `devices` contém identidades (393 na massa de 1 M), não eventos.
- **Cassandra**: `3N + A` linhas vivas: `events_by_id` (N), `events_by_device_day` (N), `events_by_ip_day` (N) e `alerts_by_severity_day` (A alertas). Para 1 M: 3 082 443 linhas. Estados internos (`system.paxos` das LWT, batchlog, tombstones) não são eventos.
- Os 24 eventos da amostra e os marcadores excluídos dos testes continuam nos bancos e são contados à parte pelo validador.

## Gerador (`scripts/generation/bulk_events.py`)

| Item | Decisão |
| --- | --- |
| Dataset / versão / seed | `cyberguard-bulk-v1`, gerador `1.0.0`, seed `20261109` |
| Função | `event(i)` é pura em (dataset, seed, i); não depende de relógio, ordem ou estado anterior |
| Aleatoriedade | SHA-256 em modo contador por evento; escolhas por módulo e pesos **inteiros**. Não usa `random` nem pesos float, logo não depende da versão do Python nem da libm |
| UUID | 16 primeiros bytes de `SHA256("cyberguard-bulk-v1|seed|id|i")` com bits de versão 4/variante RFC 4122; unicidade verificada no manifesto |
| Perfis | prefixos `[0, N)`: 10 mil ⊂ 100 mil ⊂ 1 milhão; aumentar o volume só acrescenta índices novos |
| Janela | 28 dias UTC, `2026-10-05` a `2026-11-02` (exclusivo); disjunta da amostra (06–08/11) e dos testes (2001) |
| Streaming | eventos gerados em chunks de 1000; nenhum arquivo de eventos é gravado |

Mistura de cenários (partes por 10 000): login bem-sucedido 3400, login falho 500, conexão permitida 3000, conexão bloqueada 800, acesso suspeito 300, anomalia de tráfego 300, alertas de fundo 700 e **20 campanhas** (1000): força bruta, varredura de portas, credential stuffing, exfiltração e beaconing C2, com janelas, IPs atacantes e alvos fixos derivados da seed. Cerca de 12% dos eventos de campanha são alertas de severidade 3–5; o total de alertas fica em ~8,2%.

Realismo controlado: perfil horário e de dia útil para logins/conexões; popularidade Zipf (inteira) de dispositivos, IPs e contas; 393 dispositivos em papéis (firewall, VPN, DC, IDS, EDR, servidores, estações); IPv4 ~69% e IPv6 ~31%. Endereços apenas de faixas privadas/documentação (RFC 1918, 4193, 5737, 3849) e contas sintéticas `acct-NNNNN`; não há dados pessoais nem credenciais. Rótulos MITRE ATT&CK são apenas identificadores públicos.

### Manifesto

`python scripts/generation/generate_bulk.py --count 1000000` percorre o fluxo e grava `data/bulk/cyberguard-bulk-v1.manifest.json` (≈86 KB, versionável) com seed, algoritmos, mundo (dispositivos, campanhas), SHA-256 de cada chunk de 1000 eventos e, para cada perfil (10 mil/100 mil/1 M): SHA-256 do NDJSON canônico do prefixo, contagens por categoria/tipo/severidade/resultado, alertas, linhas Cassandra esperadas e distribuição esperada de partições. Repetir o comando deve reproduzir o arquivo byte a byte; um manifesto diferente nunca é sobrescrito. O tempo de geração vai para um relatório separado.

## Particionamento: avaliação antes da carga

O manifesto calcula a distribuição exata que as projeções terão. Em 1 M:

| Projeção | Partições | p50 | p99 | Máximo |
| --- | --- | --- | --- | --- |
| `events_by_device_day` | 10 811 | 9 | 1 867 | 11 822 (`ids-sensor-06`, 27/10) |
| `events_by_ip_day` | 183 130 | 2 | 63 | 11 517 (`2001:db8:bad:4::6`, 27/10, campanha) |
| `alerts_by_severity_day` | 140 | 576 | 1 268 | 1 320 (severidade 3, 14/10) |

O risco previsto para Q3 (severidade/dia) não é o maior em linhas: as partições mais densas vêm de sensores e de IPs de campanha. Todas ficam muito abaixo do limiar de revisão (~100 mil chaves ou 50 MiB). Por isso, **não foram introduzidos buckets/shards**: seria alteração de modelagem sem evidência. O validador mede a distribuição real (exportação integral) e `nodetool tablehistograms`. Em 5 M (não gerado nem carregado), a estimativa linear da maior partição é ~59 mil linhas, ainda abaixo do limiar; uma janela ou fonte muito mais concentrada exigiria bucket horário.

## Carga (`scripts/loading/load_bulk.py`)

A carga inicial passa pela **API real** (`POST /api/{fonte}/events`). Assim, o PostgreSQL usa a mesma transação (reserva, dispositivo e evento) e o Cassandra o mesmo fluxo `pending → logged batch de projeções → active` com LWT. Não há escrita direta em tabelas, `COPY`/`sstableloader` ou atalho que pule validação, projeções ou reserva de UUID.

- Executada **separadamente por banco** (`--source`), para que tempos e recursos não se misturem.
- 16 workers por padrão, conexões HTTP/1.1 keep-alive por thread, 2 chunks em voo. O pool PostgreSQL da API continua com 5 conexões; a API usa 64 locks por fonte. Nenhuma configuração dos bancos foi alterada.
- Antes de enviar, cada chunk regenerado é comparado ao SHA-256 do manifesto.
- Uma resposta só é aceita se for 201/200 **com o envelope exatamente igual** a `{"data": evento, "revision": 1}`.
- 409, 4xx inesperado ou conteúdo divergente encerram a carga sem sobrescrever nada.
- 502/503/504 ou erro de conexão: até 6 tentativas com backoff exponencial e jitter (0,25 s → 8 s), sempre com o mesmo UUID. Persistindo, o ID vai para `uncertain-<fonte>.ndjson` e a carga para.
- Checkpoint (`data/generated/cyberguard-bulk-v1/checkpoint-<fonte>.json`, escrita atômica com `fsync`) registra só chunks totalmente confirmados. Na retomada, chunks incompletos são reenviados. Eventos já gravados retornam 200 idêntico (`reused`), e uma reserva Cassandra `pending` é concluída pelo próprio CREATE repetido.
- `--max-seconds` para em fronteira de chunk; Ctrl+C também preserva o checkpoint; `--ignore-checkpoint` reenvia tudo para testar idempotência.
- Registros: `load-<fonte>.ndjson` (duração por chunk) e `resources-<fonte>-<run>.ndjson` (`docker stats` + RAM livre do host a cada 10 s), ignorados pelo Git; relatório final pequeno em `data/bulk/reports/load-<fonte>-<alvo>-<run>.json`.

### O que o tempo de carga significa

É o tempo de **carga inicial via API** em laboratório: inclui cliente Python, HTTP, validação e serialização na API (build **debug**), além do fluxo completo de cada banco (PostgreSQL ≈ 7 comandos por transação; Cassandra = 2 LWT + 1 logged batch + 2 leituras). As durabilidades são diferentes: PostgreSQL com `synchronous_commit=on` (fsync no commit) e Cassandra com `commitlog_sync: periodic` de 10 s e RF=1. Esses números **não são benchmark** e não demonstram superioridade de nenhum banco. As medições comparativas controladas (30 execuções, aquecimento, versões e variante com confirmação antes do fsync) estão em [benchmark-methodology.md](benchmark-methodology.md) (E6 para escrita).

## Validação (`scripts/validation/check_bulk.py --target N`)

Exige que exatamente N eventos do dataset estejam carregados nos dois bancos. Regenera o estado esperado em streaming e compara com:

1. **Exportação integral** de `events` (PostgreSQL, `COPY ... TO STDOUT`) e de `events_by_id` + três projeções (Cassandra, `cqlsh COPY ... TO STDOUT`), em pipe, sem arquivos. A comparação usa multiconjuntos com hash (soma de prefixos SHA-256 mod 2¹²⁸) + contagem, com memória constante. Cobre conteúdo completo, IDs e chaves de cada projeção.
2. Duplicação lógica (mesmo `seq` com outro UUID), revisão 1, reservas ativas sem evento (PostgreSQL), estados `pending`/`deleting` (Cassandra) e `3N + A`.
3. Distribuição de partições medida = manifesto; `nodetool flush` (não destrutivo) seguido de `tablestats`/`tablehistograms`, `du` e tamanhos PostgreSQL de tabelas e índices.
4. API: ~500 READs por amostragem determinística nos dois bancos; Q1–Q3 em seis filtros (dispositivo quente/frio, IPv6 de campanha, IPv4, severidade quente, severidade 5) com paginação completa até 100 páginas. Os resultados precisam ser iguais entre os bancos e iguais à expectativa do gerador.
5. `EXPLAIN (ANALYZE, BUFFERS)` da primeira página no PostgreSQL, como evidência de uso dos índices.

Um controle negativo (`--target 9000` com 10 mil carregados) falhou em 10 checks, como esperado; o validador não aprova por vacuidade.

## Condições de cache e recursos

Nenhum cache foi limpo, nenhum serviço foi reiniciado entre etapas e não houve aquecimento deliberado. As leituras de validação ocorrem logo após a carga, com memtables/page cache quentes, e o `flush` precede apenas as métricas de tamanho. Por isso, as durações de consultas registradas pelo validador são observações funcionais, não latências comparáveis.

## Reproduzir

```powershell
python scripts/validation/test_bulk_generator.py
python scripts/generation/generate_bulk.py --count 1000000      # reproduz o manifesto versionado
# API ativa (README), bancos healthy e schemas aplicados
foreach ($n in 10000, 100000, 1000000) {
  python scripts/loading/load_bulk.py --source postgresql --target $n --api-build debug
  python scripts/loading/load_bulk.py --source cassandra  --target $n --api-build debug
  python scripts/validation/check_bulk.py --target $n
}
```

Use `--docker-config tmp/docker` nos scripts que acessam Docker, se o perfil Docker não puder ser lido. A carga é retomável: repetir o mesmo comando continua do checkpoint. Para recomeçar do zero em outro ambiente, use bancos novos; nunca apague volumes ou tabelas existentes para isso.
