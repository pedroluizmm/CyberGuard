# Geração determinística

`generate_sample.py` produz exatamente 24 eventos sintéticos estáveis e manifesto com SHA-256. Datas, conteúdo e IDs são fixados pela versão do dataset; arquivos existentes diferentes são preservados e causam erro. Não depende do relógio atual ou de bibliotecas externas.

`bulk_events.py` é o gerador volumoso (Task 03): `BulkGenerator(seed).event(i)` é função pura de dataset, seed e índice, baseada apenas em SHA-256 e pesos inteiros. Perfis crescentes são prefixos `[0, N)` do mesmo conjunto lógico. Os eventos são produzidos em streaming, nunca gravados em massa.

`generate_bulk.py --count 1000000` calcula o manifesto versionável `data/bulk/cyberguard-bulk-v1.manifest.json` (seed, algoritmos, hashes por chunk e por perfil, contagens e distribuição de partições) e recusa sobrescrever um manifesto diferente. Repetir o comando reproduz o arquivo byte a byte. Limite: 5 000 000 eventos; nada é gerado automaticamente. Ver `docs/bulk-load.md`.
