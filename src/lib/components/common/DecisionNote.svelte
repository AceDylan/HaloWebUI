<script lang="ts">
	// Which 辅助决策模型 made this run's automatic choices, or why the module decided as before.
	import type { DecisionTrace } from '$lib/apis/decision-model';

	export let trace: DecisionTrace | null | undefined = null;
</script>

{#if trace}
	<p
		class="text-xs text-gray-500"
		data-decision-note
		data-fallback={trace.fallback ? 'true' : 'false'}
	>
		辅助决策 <span class="font-mono text-gray-700 dark:text-gray-300"
			>{trace.name || trace.model}</span
		>{#if trace.fallback}<span class="text-amber-700 dark:text-amber-300"
				>没用上（{trace.reason || '调用失败'}），按原来的方式选择</span
			>{/if}
	</p>
{/if}
