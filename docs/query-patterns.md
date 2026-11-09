# Consultas Q1, Q2 e Q3

## Contrato comum

Rotas: `GET /api/{source}/queries/device`, `/ip` e `/alerts`, onde `source` é `postgresql` ou `cassandra`. Não há endpoint de listagem irrestrita de toda a base.

| Consulta | Filtro obrigatório | Semântica |
| --- | --- | --- |
| Q1 | `device_id` | Histórico de todas as categorias do dispositivo na janela |
| Q2 | `source_ip` | Histórico do IP exato, normalizado, na janela; não aceita CIDR |
| Q3 | `severity` (1..5) | Apenas `category=alert` e severidade **exatamente** igual; não significa severidade mínima |

Todas exigem `from` e `to` em RFC3339 UTC, com intervalo **`[from,to)`**: início inclusivo e fim exclusivo. A janela deve tocar no máximo sete datas UTC. Por exemplo, `06/11 00:00` a `13/11 00:00` toca sete dias; acrescentar um milissegundo ao fim toca oito e é rejeitado. Nenhum filtro extra de outra consulta é aceito.

Ordenação: `occurred_at DESC, event_id DESC`. O UUID v4 desempata eventos no mesmo milissegundo. `page_size` padrão 50, intervalo 1..100. O servidor busca no máximo mais um evento válido para decidir se há próxima página. Resposta: `{"items":[{"data":{...},"revision":1}],"next_cursor":null}`.

O cursor é JSON codificado em base64url, versão 1, vinculado ao tipo/valor do filtro, janela e page_size. Não é um segredo, assinatura ou autorização. Conteúdo inválido, posição fora da janela, UUID inválido e reaproveitamento com outro filtro retornam 400. Ele representa a última chave entregue, usando seek/keyset, sem OFFSET. Pode ser usado na outra fonte se os dados lógicos forem equivalentes. Não oferece snapshot entre páginas: inserções mais recentes que a posição já percorrida não reaparecem; atualizações e exclusões podem ocorrer durante a navegação.

## SQL parametrizado

Os valores abaixo são parâmetros vinculados pelo SQLx; nenhuma entrada do usuário é concatenada ao SQL. A implementação seleciona apenas fragmentos fixos para Q1/Q2/Q3.

```sql
-- Q1: $1 dispositivo, $2 início, $3 fim, $4/$5 posição, $6 page_size + 1
SELECT event_id, occurred_at, event_date, device_id, host(source_ip) AS source_ip,
       category, event_type, severity, outcome, message, metadata, revision
FROM events
WHERE device_id = $1
  AND occurred_at >= $2 AND occurred_at < $3
  AND (occurred_at, event_id) < ($4, $5)
ORDER BY occurred_at DESC, event_id DESC
LIMIT $6;

-- Q2: mesmas colunas, janela, seek, ordenação e limite da Q1.
-- Trocar somente o predicado de igualdade:
-- WHERE source_ip = $1::inet

-- Q3: mesmas colunas, janela, seek, ordenação e limite da Q1.
-- Trocar somente o predicado de igualdade:
-- WHERE category = 'alert' AND severity = $1
```

`$n` é um parâmetro; `::inet` converte o IP validado; `host()` devolve somente o endereço, sem máscara. A comparação de tuplas implementa o desempate do cursor. Na primeira página, `$4=to` e `$5=00000000-0000-0000-0000-000000000000`; o fim já é exclusivo. Nas seguintes, usar o timestamp/UUID do cursor. `LIMIT` contém page_size+1, nunca uma quantidade irrestrita. Todos os índices necessários estão no SQL versionado; o planner pode escolher leitura sequencial para uma amostra minúscula sem indicar erro de modelagem. Ver [índices multicoluna PostgreSQL 17](https://www.postgresql.org/docs/17/indexes-multicolumn.html).

### Exemplos SQL executáveis com a amostra

```sql
-- Q1
SELECT event_id, occurred_at, device_id, category, severity
FROM events
WHERE device_id = 'soc-sensor-01'
  AND occurred_at >= '2026-11-06T00:00:00Z'::timestamptz
  AND occurred_at <  '2026-11-09T00:00:00Z'::timestamptz
ORDER BY occurred_at DESC, event_id DESC LIMIT 20;

-- Q2
SELECT event_id, occurred_at, host(source_ip), category
FROM events
WHERE source_ip = '2001:db8::10'::inet
  AND occurred_at >= '2026-11-06T00:00:00Z'::timestamptz
  AND occurred_at <  '2026-11-09T00:00:00Z'::timestamptz
ORDER BY occurred_at DESC, event_id DESC LIMIT 20;

-- Q3: um evento network com severidade 4 continua excluído.
SELECT event_id, occurred_at, severity, message
FROM events
WHERE category = 'alert' AND severity = 4
  AND occurred_at >= '2026-11-06T00:00:00Z'::timestamptz
  AND occurred_at <  '2026-11-09T00:00:00Z'::timestamptz
ORDER BY occurred_at DESC, event_id DESC LIMIT 20;
```

## CQL parametrizado

```cql
-- Q1, uma partição por vez
SELECT occurred_at, event_id
FROM cyberguard.events_by_device_day
WHERE device_id = ? AND event_date = ?
  AND (occurred_at, event_id) >= (?, ?)
  AND (occurred_at, event_id) < (?, ?)
LIMIT ?;

-- Q2
SELECT occurred_at, event_id
FROM cyberguard.events_by_ip_day
WHERE source_ip = ? AND event_date = ?
  AND (occurred_at, event_id) >= (?, ?)
  AND (occurred_at, event_id) < (?, ?)
LIMIT ?;

-- Q3, a tabela contém somente alertas
SELECT occurred_at, event_id
FROM cyberguard.alerts_by_severity_day
WHERE severity = ? AND event_date = ?
  AND (occurred_at, event_id) >= (?, ?)
  AND (occurred_at, event_id) < (?, ?)
LIMIT ?;

-- Materialização do conteúdo por ID para cada candidato
SELECT payload, revision, lifecycle FROM cyberguard.events_by_id WHERE event_id = ?;
```

Cada `?` recebe um valor serializado pelo driver e as instruções são preparadas/cacheadas. As duas primeiras igualdades identificam a chave completa de partição. O par de clustering `(timestamp,UUID)` permite intervalos e continuação ordenada; a ordem DESC está declarada no esquema. O limite inferior é `(from,UUID nulo)` e o superior é `(to,UUID nulo)` ou a posição exclusiva do cursor. UUID nulo é apenas sentinela interna, nunca um ID de evento aceito.

O backend percorre as datas do fim para o início, no máximo sete. Busca somente o número de candidatos ainda necessário, valida o registro canônico e o filtro e concatena os resultados nessa ordem. A leitura canônica evita retornar conteúdo desatualizado de projeções. Projeções antigas de registros excluídos/pendentes não aparecem como eventos ativos. Se precisar ultrapassar 1000 candidatos examinados numa página, retorna 503 `scan_limit`, em vez de varrer indefinidamente ou apresentar um resultado incompleto como completo. As consultas seguem as restrições de chave/intervalo do [CQL](https://cassandra.apache.org/doc/latest/cassandra/developing/cql/dml.html).

### Exemplos CQL executáveis, dia 06/11

```cql
SELECT occurred_at, event_id FROM cyberguard.events_by_device_day
WHERE device_id = 'soc-sensor-01' AND event_date = '2026-11-06'
AND (occurred_at, event_id) >= ('2026-11-06T00:00:00Z', 00000000-0000-0000-0000-000000000000)
AND (occurred_at, event_id) < ('2026-11-07T00:00:00Z', 00000000-0000-0000-0000-000000000000)
LIMIT 20;

SELECT occurred_at, event_id FROM cyberguard.events_by_ip_day
WHERE source_ip = '2001:db8::10' AND event_date = '2026-11-06'
AND (occurred_at, event_id) >= ('2026-11-06T00:00:00Z', 00000000-0000-0000-0000-000000000000)
AND (occurred_at, event_id) < ('2026-11-07T00:00:00Z', 00000000-0000-0000-0000-000000000000)
LIMIT 20;

SELECT occurred_at, event_id FROM cyberguard.alerts_by_severity_day
WHERE severity = 4 AND event_date = '2026-11-06'
AND (occurred_at, event_id) >= ('2026-11-06T00:00:00Z', 00000000-0000-0000-0000-000000000000)
AND (occurred_at, event_id) < ('2026-11-07T00:00:00Z', 00000000-0000-0000-0000-000000000000)
LIMIT 20;
```

Para uma janela de três dias, a API consulta 08/11, 07/11 e 06/11 e lê os IDs canônicos necessários. Executar somente a instrução de um dia manualmente não equivale à janela inteira SQL. Os exemplos de projeção mostram chaves, não o payload completo; a API entrega o mesmo envelope de evento nos dois bancos.

## Exemplos HTTP

```text
GET /api/postgresql/queries/device?device_id=soc-sensor-01&from=2026-11-06T00:00:00Z&to=2026-11-09T00:00:00Z&page_size=2
GET /api/cassandra/queries/ip?source_ip=192.0.2.10&from=2026-11-06T00:00:00Z&to=2026-11-09T00:00:00Z&page_size=2
GET /api/cassandra/queries/alerts?severity=4&from=2026-11-06T00:00:00Z&to=2026-11-09T00:00:00Z&page_size=2
```

Adicionar `cursor=<next_cursor>` preservando todos os outros parâmetros para continuar. Janela sem resultados retorna 200 com `items=[]` e `next_cursor=null`. Parâmetros inválidos retornam 400. Nenhuma duração desta etapa comprova vantagem de um banco; canonical lookups, LWTs, transações, índices e limites precisam compor o futuro protocolo experimental.
