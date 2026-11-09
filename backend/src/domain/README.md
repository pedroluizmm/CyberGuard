# Domínio

`mod.rs` implementa EventData, envelope Event/revision, UpdateEvent e validações independentes de persistência. UUID v4, UTC em milissegundos, data derivada, IP canônico, tipos por categoria, severidade e JSON limitado estão documentados em `docs/data-model.md`.

Campos de roteamento são imutáveis; PUT altera somente outcome/message/metadata com revisão esperada. Manter o mesmo contrato nas duas fontes.
