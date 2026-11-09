# Analytics

`mod.rs` define Q1 (dispositivo), Q2 (IP) e Q3 (alertas por severidade exata), janela de até sete datas UTC, limites de página e cursor keyset. Consultas físicas ficam nos adaptadores storage, seguindo `docs/query-patterns.md`.

Não há indicadores agregados ou executor experimental nesta etapa. Não misturar consultas de negócio com repetição de benchmark.
