# Validação

`check_foundation.py`: integridade dos PDFs originais, exclusão de arquivos sensíveis pelo Git e preservação de amostras/manifestos versionáveis. Não depende de serviços externos.

`check_api.py`: verifica os contratos HTTP reais e CORS da API local. Exige API ativa; retorna falha se algum banco estiver indisponível. Não insere dados nem fabrica resultados.

Implementados na Task 02:

- `test_integration.py`: sete testes reais HTTP, cobrindo CREATE/READ/UPDATE/DELETE, retries, conflitos, três consultas, paginação, limites, dados inválidos, concorrência, health e repair. Só exclui UUIDs próprios com marcador de execução. Recusa alertas preexistentes na janela reservada de 06 a 09/11/2001.
- `test_recovery.py`: cria um UUID novo, injeta estados pending/deleting e uma projeção ausente; verifica recuperação por ID e conteúdo/visibilidade. Nunca toca IDs alheios.
- `check_sample.py`: exige a amostra carregada, compara 24 IDs/conteúdos e Q1/Q2/Q3 nas duas fontes, depois confere 81 linhas Cassandra por IDs e partições limitadas.

Implementados na Task 03 (massa volumosa, ver `docs/bulk-load.md`):

- `test_bulk_generator.py`: testes offline do gerador (contrato, determinismo, prefixos, disjunção da amostra, manifesto).
- `check_bulk.py --target N`: exige exatamente N eventos do dataset nos dois bancos. Compara exportações integrais (`COPY TO STDOUT`, em pipe) com o gerador por multiconjuntos com hash, verifica projeções, `3N + A`, duplicação, pendências, partições, READs amostrados e Q1–Q3 paginadas; registra tamanhos e planos em `data/bulk/reports/validate-N-*.json`. Só lê dados; executa `nodetool flush` (não destrutivo) salvo `--no-flush`.

Scripts com Docker aceitam `--docker-config tmp/docker`. Não há DROP, limpeza de tabelas ou remoção de volumes. Testes deixam reservas de IDs excluídos; isso é parte da semântica documentada. Resultados executados: `docs/verification-task02.md` e `docs/verification-task03.md`.
