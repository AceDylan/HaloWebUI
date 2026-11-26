<script lang="ts">
	import { onDestroy } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { hermesHandoffPrompt } from '$lib/components/discuss/model';
	import { getDiscussion } from '$lib/apis/discussions';

	export let roomId: string;
	export let originId: string;
	export let canUseHermes: boolean;
	export let prepare: (draft: string) => void;

	let loading = false;
	let destroyed = false;
	onDestroy(() => (destroyed = true));

	const useConclusion = async () => {
		if (loading) return;
		loading = true;
		try {
			const room = await getDiscussion(localStorage.token, roomId);
			if (destroyed || !canUseHermes) return;
			if (!room.asks.some((ask) => ask.origin?.chatId === originId)) {
				throw new Error('讨论来源与当前对话不一致');
			}
			const latest = room.asks.at(-1);
			if (room.running || latest?.status !== 'done' || !latest.conclusion?.content?.trim()) {
				throw new Error('最新一轮还没有结论，请到原讨论查看进度');
			}
			prepare(hermesHandoffPrompt(latest, 'execute'));
		} catch (error) {
			if (!destroyed) toast.error(error instanceof Error ? error.message : '读取讨论结论失败');
		} finally {
			loading = false;
		}
	};
</script>

<div
	class="mx-auto flex w-full max-w-3xl flex-wrap items-center gap-2 px-4 pb-2 text-xs"
	data-discussion-followup
>
	<a
		class="inline-flex items-center gap-1 rounded-xl border border-gray-200 bg-white/80 px-3 py-1.5 font-medium text-gray-700 transition hover:border-gray-300 hover:bg-gray-50 dark:border-gray-800 dark:bg-gray-900/70 dark:text-gray-200 dark:hover:border-gray-700 dark:hover:bg-gray-850"
		href={'/discuss/' + encodeURIComponent(roomId) + '#follow-up'}>继续这场讨论</a
	>
	{#if canUseHermes}
		<button
			type="button"
			class="inline-flex items-center gap-1 rounded-xl border border-sky-500/30 bg-sky-500/10 px-3 py-1.5 font-medium text-sky-700 transition hover:bg-sky-500/15 disabled:cursor-not-allowed disabled:opacity-60 dark:border-sky-400/30 dark:bg-sky-400/10 dark:text-sky-300 dark:hover:bg-sky-400/15"
			disabled={loading}
			on:click={useConclusion}
		>
			{loading ? '正在读取最新结论…' : '让 Hermes 按结论执行'}
		</button>
	{/if}
</div>
