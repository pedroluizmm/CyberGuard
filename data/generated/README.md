# Estado local de geração/carga (fora do Git)

Arquivos produzidos aqui são ignorados, exceto este README. `cyberguard-bulk-v1/` guarda checkpoints de carga por banco, logs por chunk, amostras de recursos e IDs de resposta incerta. Não contém a massa de eventos: ela é regenerada deterministicamente a partir da seed.

O manifesto pequeno e os relatórios de execução ficam versionáveis em `data/bulk/`. Não apague checkpoints de uma carga em andamento; sem eles, a retomada reenvia chunks já concluídos (idempotente, porém mais lenta). Não confundir linhas físicas Cassandra com registros lógicos distintos.
