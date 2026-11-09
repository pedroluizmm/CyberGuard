# Experimentos (ainda não executados)

Manter protocolo, resultados brutos pequenos e análise separados dos dados de produção. Definir pelo menos três operações equivalentes; executar no mínimo dez vezes por operação/banco; comparar medianas sem eliminar amostras desfavoráveis sem justificativa.

Registrar hardware, SO/WSL, versões, limites de CPU/RAM, tamanho lógico/físico, índices, parâmetros, consistência, ordem, relógio, fronteira medida, aquecimento e cache. Especificar se os bancos rodam simultaneamente e controlar interferência. Os limites iniciais de 5 GiB/2 GiB não são prova de equivalência de recursos.

Não usar durações dos healthchecks como benchmark: incluem abertura de conexão e sondam consultas diferentes. Não há resultados ou vantagem NoSQL comprovados nesta etapa.
