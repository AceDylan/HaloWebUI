<script lang="ts">
	import { onMount } from 'svelte';
	import { targetAutoRoute, MODE_LABEL, type AutoMode, type AutoRoute } from '$lib/apis/auto';
	/**
	 * On a 精答 / 讨论 / 协作 page that 自动分流 chose: why it was chosen, and the way back — to the
	 * chat it came from (its result goes back there), else to its record on the 自动分流 page.
	 */
	export let mode: AutoMode;
	export let targetId: string;
	let row: AutoRoute | null = null;
	onMount(() => {
		targetAutoRoute(localStorage.token, mode, targetId)
			.then((r) => (row = r))
			.catch(() => {});
	});
	$: back = row?.origin_chat_id
		? { href: `/c/${row.origin_chat_id}`, label: '回到原对话' }
		: row
			? { href: `/auto?request=${encodeURIComponent(row.id)}`, label: '分流记录' }
			: null;
</script>

{#if row}
	<aside
		class="mb-3 flex items-start gap-3 rounded-xl border border-cyan-500/20 bg-cyan-500/5 px-4 py-2.5 text-sm"
		data-auto-notice
	>
		<span
			class="mt-0.5 shrink-0 rounded-full bg-cyan-500/10 px-2 py-0.5 text-[11px] font-medium text-cyan-700 dark:text-cyan-300"
			>{row.degraded ? '临时改用' : '自动分流 →'}
			{MODE_LABEL[mode]}{row.read_only ? '（只读）' : ''}</span
		>
		<p class="min-w-0 flex-1 text-xs leading-5 text-gray-600 dark:text-gray-300">
			{row.reason || '按问题选择了这种处理方式'}
		</p>
		{#if back}<a
				class="shrink-0 text-xs font-medium text-cyan-700 hover:underline dark:text-cyan-300"
				href={back.href}
				data-auto-notice-back>{back.label} →</a
			>{/if}
	</aside>
{/if}
