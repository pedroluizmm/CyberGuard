# Engenharia de dados

Python 3.11+, biblioteca padrão nesta etapa (sem dependências a instalar). Execute a partir da raiz:

```powershell
python scripts/setup_env.py
python scripts/validation/check_foundation.py
python scripts/validation/check_api.py
python scripts/apply_schema.py
python scripts/generation/generate_sample.py
python scripts/loading/load_sample.py
python scripts/validation/test_integration.py
python scripts/validation/test_recovery.py
python scripts/validation/check_sample.py
# Task 03 - massa volumosa (docs/bulk-load.md)
python scripts/validation/test_bulk_generator.py
python scripts/generation/generate_bulk.py --count 1000000
python scripts/loading/load_bulk.py --source postgresql --target 10000
python scripts/loading/load_bulk.py --source cassandra --target 10000
python scripts/validation/check_bulk.py --target 10000
```

`generation/`, `loading/` e `validation/` separam geração, carga e validação. A Task 02 fixa contrato, pequena amostra e manifesto. Preparar schemas antes do CRUD e iniciar a API antes de carregar/validar dados. A Task 03 acrescenta geração volumosa determinística em streaming, carga retomável com checkpoints e validação integral; nenhum script mantém milhões de eventos em RAM nem grava a massa em arquivo. Introduzir dependências fixadas apenas quando necessárias.
