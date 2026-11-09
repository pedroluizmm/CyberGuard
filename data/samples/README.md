# Amostras versionáveis

`events.json`: 24 eventos sintéticos determinísticos para três dias UTC e duas identidades de dispositivo; nove são alertas. `events.manifest.json` contém versão do dataset, algoritmo dos UUIDs, SHA-256 e previsão de linhas físicas ativas Cassandra (81).

Gerar/conferir com `python scripts/generation/generate_sample.py`; carregar com `python scripts/loading/load_sample.py`; validar com `python scripts/validation/check_sample.py`. Nenhum registro representa atividade real. Não editar a amostra carregada para demonstrar UPDATE: crie outro UUID de teste, pois a carga posterior detecta conflito em vez de sobrescrever alterações.
