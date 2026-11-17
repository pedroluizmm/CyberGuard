<script lang="ts" module>
  // Minimal line-icon set (24 px grid, 1.75 stroke). Drawn for this project; no icon library.
  const PATHS = {
    grid: 'M4 4h6.5v6.5H4zM13.5 4H20v6.5h-6.5zM4 13.5h6.5V20H4zM13.5 13.5H20V20h-6.5z',
    search: 'M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14zM20 20l-4-4',
    compare: 'M7 4v14M3.5 14.5 7 18l3.5-3.5M17 20V6M13.5 9.5 17 6l3.5 3.5',
    chart: 'M3.5 20.5h17M7 17v-6M12 17V6.5M17 17v-9',
    shield: 'M12 3 19.5 6v5.6c0 4.4-3.1 8.2-7.5 9.4-4.4-1.2-7.5-5-7.5-9.4V6L12 3zM9 12.2l2.1 2.1L15.2 10',
    relational: 'M3.5 5.5h17v13h-17zM3.5 10h17M9.5 10v8.5',
    widecol: 'M3.5 5.5h17v13h-17zM8.5 5.5v13M13.5 5.5v13M3.5 9.5h17',
    server: 'M4 4.5h16v6H4zM4 13.5h16v6H4zM7.5 7.5h.01M7.5 16.5h.01',
    refresh: 'M20 12a8 8 0 1 1-2.35-5.65L20 8.7M20 4v4.7h-4.7',
    clock: 'M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17zM12 7.5V12l3 2',
    activity: 'M3 12h3.5l2.8-7 5.4 14 2.8-7H21',
    alert: 'M12 4 21 19.5H3L12 4zM12 10v4.2M12 16.9v.01',
    critical: 'M8.3 3.5h7.4l4.8 4.8v7.4l-4.8 4.8H8.3l-4.8-4.8V8.3zM12 8v4.6M12 15.9v.01',
    calendar: 'M4 6h16v14H4zM4 10.5h16M8.5 3.5V8M15.5 3.5V8',
    check: 'M5 12.5l4.5 4.5L19 7.5',
    x: 'M6.5 6.5l11 11M17.5 6.5l-11 11',
    left: 'M14.5 6l-6 6 6 6',
    right: 'M9.5 6l6 6-6 6',
    copy: 'M9 9h11v11H9zM15 9V4H4v11h5',
    play: 'M7.5 5v14l11-7z',
    info: 'M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17zM12 11v5.5M12 7.8v.01',
    layers: 'M12 3.5l8.5 4.5-8.5 4.5L3.5 8zM3.5 12.5l8.5 4.5 8.5-4.5M3.5 16.5 12 21l8.5-4.5',
    zap: 'M13 2.5 4.5 13.5h6.5l-1 8 8.5-11h-6.5z',
    filter: 'M4 5h16l-6.2 7.5v5.8l-3.6 1.7v-7.5z',
    table: 'M3.5 5h17v14h-17zM3.5 9.5h17M3.5 14h17M9.5 9.5V19',
    flask: 'M9.5 3.5h5M10.5 3.5v5.2L5 18.2c-.6 1.1.2 2.3 1.4 2.3h11.2c1.2 0 2-1.2 1.4-2.3l-5.5-9.5V3.5M7.5 14.5h9',
    arrowUpRight: 'M7 17 17 7M8.5 7H17v8.5',
    target: 'M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17zM12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM12 11.9v.2',
  } as const
  export type IconName = keyof typeof PATHS
</script>

<script lang="ts">
  let { name, size = 18, stroke = 1.75, label }: { name: IconName; size?: number; stroke?: number; label?: string } = $props()
</script>

<svg class="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width={stroke}
  stroke-linecap="round" stroke-linejoin="round" role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : 'true'}>
  <path d={PATHS[name]} />
</svg>

<style>
  .icon { display: block; flex-shrink: 0; }
</style>
