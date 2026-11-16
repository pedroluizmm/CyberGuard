# Roteiro da demonstração ao vivo (cerca de 6 min)

## Antes da aula (10 a 15 min antes)

Use PowerShell na raiz do repositório e feche programas pesados: a máquina tem 16 GB e o Cassandra usa cerca de 3 GB.

```powershell
docker compose up -d --wait --wait-timeout 720      # bancos (Cassandra pode levar 1-3 min)
python scripts/run_api.py start                     # API release em 127.0.0.1:3000
python scripts/validation/check_api.py              # deve mostrar "both databases answered real queries"
npm.cmd --prefix frontend run dev                   # deixar este terminal aberto
```

Abra `http://localhost:5173` e confira:

- os três indicadores de serviço verdes na barra lateral;
- a visão geral carregada em "26/10–01/11";
- a fonte inicial **Cassandra**.

Para aquecer, clique uma vez em "Executar nos dois bancos": a primeira consulta de cada fonte abre conexões e prepara instruções. Depois de reiniciar o computador ou os contêineres, faça de 2 a 3 execuções: as caches do PostgreSQL e a JVM do Cassandra demoram para aquecer. Se `scripts/run_api.py start` disser que falta o binário, rode antes `python scripts/run_api.py build` (cerca de 5 min na primeira vez).

## Passo a passo

1. **Visão geral (Cassandra), cerca de 1 min.**
   - Mostre os indicadores: 244 881 eventos, 19 758 alertas, 2 741 críticos.
   - Mostre o **tempo no banco**, de 2 a 8 ms.
   - Na série horária, passe o mouse no pico de **27/10 às 09h**: são 11 379 eventos de rede, uma campanha de varredura da massa sintética.
   - Mostre a distribuição por severidade e a participação por categoria.
2. **Trocar para PostgreSQL**, cerca de 40 s. Os números são **exatamente os mesmos** e o tempo no banco fica entre 50 e 90 ms. Explique: o PostgreSQL agrega cerca de 245 mil entradas de índice; o Cassandra lê 7 partições pré-agregadas.
3. **Filtros**, cerca de 40 s.
   - Categoria **Alerta** e severidade **5**: novas consultas nas duas fontes.
   - Atalho **Pico · 27/10** (1 dia).
   - Volte para "Todas" e "26/10–01/11".
4. **Comparação ao vivo · Painel agregado**, cerca de 1 min. **Este é o ganho do NoSQL (R14).**
   - Escolha 10 repetições e clique em "Executar nos dois bancos".
   - Esperado: Cassandra mais rápido na mediana HTTP do navegador, tipicamente de 4× a 20× (o proxy do Vite e o aquecimento das caches reduzem a razão observada no navegador), com a mensagem **"Resultado de negócio idêntico nos dois bancos"**. O primeiro par é aquecimento e é descartado automaticamente.
   - O valor exato varia; o vencedor não.
5. **Comparação ao vivo · Q1 dispositivo**, cerca de 40 s. Agora o **PostgreSQL vence**, e o resultado também é idêntico. Mostre que o trabalho não esconde o caso favorável ao relacional.
6. **Investigação**, cerca de 1 min.
   - Na aba Investigação, escolha Q2 · IP de origem e clique no exemplo `2001:db8:bad:4::6`.
   - Mostre a página de eventos, o tempo da consulta e "Próxima →", que pagina por cursor.
   - Alterne a fonte no topo: a consulta é refeita no outro banco.
7. **Benchmarks**, cerca de 1 min.
   - Mostre o protocolo e o ambiente.
   - No gráfico de medianas (escala log), o PostgreSQL vence as leituras por chave e o Cassandra vence o painel.
   - Mostre a tabela N+1 (antes e depois), o controle E5 (view materializada) e o E6 (escritas, padrão e com confirmação antes do fsync).

## Plano B

| Problema | Ação |
| --- | --- |
| Cassandra demora a ficar *healthy* | `docker compose ps` e aguardar. O dashboard mostra "Cassandra indisponível" sem dados falsos; demonstre com PostgreSQL e use a aba Benchmarks |
| API não sobe (porta ocupada) | `python scripts/run_api.py stop`, depois `start`; ou `python scripts/run_api.py logs` |
| Dashboard em branco ou erro de proxy | Confirme o terminal do Vite e reabra `http://localhost:5173` |
| Tempo de resposta pior que o normal | Feche o navegador extra e o IDE; repita a comparação (o primeiro clique aquece) |
| Sem rede/internet | Nada depende de internet depois do build; tudo roda em loopback |

## Depois

```powershell
python scripts/run_api.py stop
docker compose stop          # preserva os volumes; NUNCA usar "down -v"
```
