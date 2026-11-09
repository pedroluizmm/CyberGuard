<script lang="ts">
  let { kind = 'neutral', label }: { kind?: 'good' | 'warning' | 'neutral'; label: string } = $props()
</script>

<span class="badge {kind}"><span class="status-dot" aria-hidden="true"></span>{label}</span>

<style>
  .badge { display: inline-flex; gap: .45rem; align-items: center; font-size: .72rem; font-weight: 600; padding: .35rem .6rem; border: 1px solid var(--line); border-radius: 5px; color: var(--muted); white-space: nowrap; }
  .status-dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
  .good { color: var(--accent); background: #a8eb8308; border-color: #a8eb8333; }
  .warning { color: #edc285; background: #edc28508; border-color: #edc28533; }
</style>
