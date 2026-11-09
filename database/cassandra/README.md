# Cassandra

`001_events.cql` cria o keyspace e quatro tabelas de forma aditiva. `events_by_id` contém envelope JSON/revisão/ciclo de vida; as três projeções armazenam chaves imutáveis por dispositivo/dia, IP/dia e severidade/dia. Modelo, hot partitions, amplificação e recovery: `docs/data-model.md` e `docs/consistency.md`.

Aplicar da raiz: `python scripts/apply_schema.py` após os healthchecks. A imagem Cassandra não executa automaticamente `/docker-entrypoint-initdb.d`. Reaplicar o arquivo preserva dados; alterações futuras de esquema exigem migrações explícitas.

Laboratório: `NetworkTopologyStrategy`, `datacenter1:1`, `LOCAL_QUORUM` e `LOCAL_SERIAL` para LWT. Um nó não oferece redundância. Probes de saúde continuam consultando apenas `system.local`.
