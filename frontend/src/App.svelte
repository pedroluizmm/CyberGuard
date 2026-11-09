<script lang="ts">
  import { onMount } from 'svelte'
  import StatusBadge from './lib/StatusBadge.svelte'
  import { describeProbe, getHealth, getStorageHealth, type Health, type StorageHealth } from './lib/api'

  const sections = ['Overview', 'Eventos', 'Investigação', 'Benchmark'] as const
  type Section = typeof sections[number]
  let section = $state<Section>('Overview')
  let loading = $state(true)
  let api = $state<Health | null>(null)
  let storage = $state<StorageHealth | null>(null)
  let apiError = $state(false)
  let storageError = $state(false)
  let checkedAt = $state<string | null>(null)
  const descriptions: Record<Section, string> = {
    Overview: 'Visibilidade começa com uma conexão confiável.',
    Eventos: 'O ponto de partida para entender cada sinal.',
    Investigação: 'Contexto para conectar eventos de segurança.',
    Benchmark: 'O mesmo cenário. Duas formas de armazenar.',
  }
  const emptyStates: Record<Section, [string, string]> = {
    Overview: ['Seu ambiente, pronto para o próximo sinal.', 'A ingestão de eventos ainda não foi implementada. Os indicadores serão construídos com consultas reais às fontes de dados.'],
    Eventos: ['Nenhum conjunto de eventos disponível.', 'O catálogo e os filtros de eventos serão implementados após a definição do modelo de dados e da carga inicial.'],
    Investigação: ['As investigações começam com os dados.', 'A análise por origem e período depende da modelagem das consultas de segurança. Esta área está reservada para a próxima etapa.'],
    Benchmark: ['As evidências vêm antes das conclusões.', 'Os experimentos ainda não foram executados. Tempos brutos, medianas e condições de cache serão registrados aqui após a carga equivalente.'],
  }

  async function refresh() {
    loading = true
    api = null
    storage = null
    apiError = false
    storageError = false
    await Promise.all([
      getHealth().then((value) => { api = value }).catch(() => { apiError = true }),
      getStorageHealth().then((value) => { storage = value }).catch(() => { storageError = true }),
    ])
    checkedAt = new Date().toLocaleTimeString('pt-BR')
    loading = false
  }

  onMount(() => { void refresh() })
</script>

<svelte:head><title>{section} · CyberGuard</title></svelte:head>

<div class="workspace">
  <aside class="sidebar">
    <a class="brand" href="#overview" onclick={() => { section = 'Overview' }} aria-label="CyberGuard, início">
      <svg width="32" height="36" viewBox="0 0 32 36" fill="none" aria-hidden="true"><path d="M16 3 28 8v9c0 8-12 15-12 15S4 25 4 17V8L16 3Z" stroke="currentColor" stroke-width="1.7"/><path d="m10 17 4 4 8-9" stroke="currentColor" stroke-width="1.7"/></svg>
      <span>CYBER<span class="brand-accent">GUARD</span><small>SECURITY WORKSPACE</small></span>
    </a>
    <div class="workspace-label"><span class="workspace-icon">CG</span><span>Projeto CyberGuard<small>Laboratório local</small></span><span class="local-dot" aria-hidden="true"></span></div>
    <p class="nav-label">WORKSPACE</p>
    <nav aria-label="Navegação principal">
      {#each sections as item, index}
        <button class:active={section === item} aria-current={section === item ? 'page' : undefined} onclick={() => { section = item }}>
          <span class="nav-icon" aria-hidden="true">{['◫', '≡', '⌕', '▥'][index]}</span>{item}<span class="nav-index">0{index + 1}</span>
        </button>
      {/each}
    </nav>
    <div class="sidebar-bottom"><span class="outline-icon" aria-hidden="true">⌘</span><p>Um cenário. Dois bancos.<small>Comparação com evidências reais.</small></p></div>
    <footer class="sidebar-footer"><span>UNIFOR · NoSQL</span><span>V3 / 2026</span></footer>
  </aside>

  <div class="main-shell">
    <header class="topbar"><div><span class="breadcrumb">Workspace</span><span class="slash">/</span>{section}</div><div class="topbar-right"><span class="environment">AMBIENTE LOCAL</span><span class="avatar">CG</span></div></header>
    <main id="overview">
      <div class="page-heading"><div><p class="eyebrow">CENTRAL DE OPERAÇÕES DE SEGURANÇA</p><h1>{section === 'Overview' ? 'Visão geral' : section}</h1><p class="subtitle">{descriptions[section]}</p></div><button class="refresh-button" disabled={loading} onclick={refresh}><span aria-hidden="true" class:spinning={loading}>↻</span>{loading ? 'Verificando…' : 'Verificar conexões'}</button></div>

      <section class="foundation-banner" aria-label="Etapa do projeto"><div class="banner-symbol" aria-hidden="true">⌁</div><div><div class="banner-title">Fundação em construção <span>TASK 01</span></div><p>Infraestrutura, conexões e base da aplicação. A próxima etapa começa pelos dados.</p></div><span class="banner-step">01 <span>/ 04</span></span></section>

      <section aria-labelledby="connections-title" aria-busy={loading}>
        <div class="section-heading"><h2 id="connections-title">Estado do ambiente</h2><span aria-live="polite">{loading ? 'Consultando serviços…' : checkedAt ? `Última verificação às ${checkedAt}` : 'Ainda não verificado'}</span></div>
        <div class="connection-grid">
          <article class="connection-card"><div class="card-top"><span class="service-symbol api-symbol" aria-hidden="true">⌘</span><StatusBadge kind={loading ? 'neutral' : api ? 'good' : 'warning'} label={loading ? 'Verificando' : api ? 'Conectada' : 'Indisponível'} /></div><h3>CyberGuard API</h3><p class="technology">Rust <span>·</span> Axum <span>·</span> Tokio</p><div class="card-divider"></div><p class="connection-description">{loading ? 'Consultando o estado da aplicação.' : api ? `Aplicação respondendo · v${api.version}` : 'Sem resposta válida da aplicação.'}</p><span class="source-label">CAMADA DE APLICAÇÃO</span></article>
          {#each [{ key: 'cassandra' as const, name: 'Apache Cassandra', tech: 'Wide-column · CQL', symbol: '◉', source: 'FONTE NoSQL' }, { key: 'postgresql' as const, name: 'PostgreSQL', tech: 'Relacional · SQL', symbol: '▤', source: 'FONTE RELACIONAL' }] as database}
            {@const probe = storage?.[database.key]}
            <article class="connection-card"><div class="card-top"><span class="service-symbol" aria-hidden="true">{database.symbol}</span><StatusBadge kind={loading ? 'neutral' : probe?.status === 'up' ? 'good' : 'warning'} label={loading ? 'Verificando' : !probe ? 'Não verificado' : probe.status === 'up' ? 'Conectado' : 'Indisponível'} /></div><h3>{database.name}</h3><p class="technology">{database.tech}</p><div class="card-divider"></div><p class="connection-description">{loading ? 'Aguardando verificação da API.' : !probe ? 'A API não confirmou a conectividade.' : probe.status === 'up' ? 'Consulta de verificação concluída.' : describeProbe(probe.error)}</p><span class="source-label">{database.source}</span></article>
          {/each}
        </div>
        {#if !loading && (apiError || storageError)}<div class="connection-notice" role="status"><span aria-hidden="true">ⓘ</span><p>{apiError ? 'A conexão com a API não pôde ser confirmada.' : 'A API responde, mas a verificação dos bancos não foi concluída.'} Inicie os serviços locais e tente novamente.</p></div>{/if}
      </section>

      <section class="data-panel" aria-labelledby="data-title"><div class="panel-header"><h2 id="data-title">{section === 'Benchmark' ? 'Experimentos comparativos' : section === 'Investigação' ? 'Área de investigação' : 'Atividade de segurança'}</h2><span class="muted-tag">{section === 'Benchmark' ? 'NÃO EXECUTADOS' : 'AGUARDANDO IMPLEMENTAÇÃO'}</span></div><div class="empty-state"><div class="empty-illustration" aria-hidden="true"><div class="orbit orbit-one"></div><div class="orbit orbit-two"></div><svg width="48" height="54" viewBox="0 0 32 36" fill="none"><path d="M16 3 28 8v9c0 8-12 15-12 15S4 25 4 17V8L16 3Z" stroke="currentColor"/><path d="M10 18h4l2-5 3 10 2-5h4" stroke="currentColor"/></svg></div><h3>{emptyStates[section][0]}</h3><p>{emptyStates[section][1]}</p><span class="empty-caption">{section === 'Benchmark' ? 'Nenhuma medição disponível' : 'Nenhuma massa de dados carregada nesta etapa'}</span></div><div class="panel-footer"><span class="tiny-square" aria-hidden="true"></span>Somente dados e resultados verificados serão apresentados.</div></section>

      <section class="next-section"><div><p class="eyebrow">PRÓXIMA ETAPA</p><h2>Dar estrutura aos sinais.</h2><p>Definir eventos, modelar consultas e preparar uma carga equivalente.</p></div><div class="stack-tags"><span>Svelte 5</span><span>TypeScript</span><span>Python</span><span>Docker</span></div></section>
      <footer class="main-footer"><span>CYBERGUARD <span class="footer-dot">/</span> Monitoramento & investigação</span><span>Fundação · v0.1.0</span></footer>
    </main>
  </div>
</div>
