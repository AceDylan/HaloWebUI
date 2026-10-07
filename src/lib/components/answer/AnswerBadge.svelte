<script context="module" lang="ts">
	// Answers being written, shared by the expanded and the collapsed sidebar entry (they swap).
	import { writable } from 'svelte/store';
	const running = writable<Set<string>>(new Set());
	let loadedOnce = false;
</script>

<script lang="ts">
	import { onDestroy, onMount } from 'svelte';

	import { listAnswers } from '$lib/apis/answers';
	import { socket } from '$lib/stores';
	import { setModeLive } from '$lib/components/scifi/mode-relay';
	import { isLive } from './model';

	/** Sidebar hint for 精答: how many answers are being worked on, live from the socket. */
	export let compact = false;

	let bound: any = null;
	const onEvent = (event: any) => {
		if (event?.data?.type !== 'answer') return;
		const data = event.data.data ?? {};
		const id = event.chat_id;
		if (!id) return;
		const live =
			data.kind === 'state' ? isLive(data.run?.status) : data.kind === 'end' ? false : null;
		if (live === null) return;
		running.update((set) => {
			if (set.has(id) === live) return set;
			const next = new Set(set);
			live ? next.add(id) : next.delete(id);
			return next;
		});
	};
	const bind = (s: any) => {
		if (bound === s) return;
		bound?.off?.('chat-events', onEvent);
		bound = s;
		bound?.on?.('chat-events', onEvent);
	};
	$: bind($socket);

	onMount(async () => {
		if (loadedOnce || typeof localStorage === 'undefined' || !localStorage.token) return;
		loadedOnce = true;
		try {
			const items = await listAnswers(localStorage.token);
			running.set(new Set(items.filter((d) => isLive(d.status) || d.running).map((d) => d.id)));
		} catch {
			// no list: the socket still fills it in
		}
	});
	onDestroy(() => bound?.off?.('chat-events', onEvent));

	$: count = $running.size;
	// the mode dock on the other pages shows the same count
	$: setModeLive('answer', count);
</script>

{#if count}
	{#if compact}
		<span
			class="answer-badge-live absolute right-1 top-1 size-2 rounded-full bg-sky-500 ring-2 ring-white dark:ring-gray-900"
			aria-label="{count} 个精答进行中"
			data-answer-badge
		/>
	{:else}
		<span
			class="ml-auto inline-flex items-center gap-1 rounded-full bg-sky-500/10 px-1.5 py-px text-[11px] font-semibold tabular-nums text-sky-700 dark:text-sky-300"
			title="{count} 个精答进行中"
			data-answer-badge
			><span
				class="answer-badge-live size-1.5 rounded-full bg-sky-500"
				aria-hidden="true"
			/>{count}</span
		>
	{/if}
{/if}

<style>
	.answer-badge-live {
		animation: answer-badge 1.8s ease-in-out infinite;
	}
	@keyframes answer-badge {
		50% {
			opacity: 0.35;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.answer-badge-live {
			animation: none;
		}
	}
</style>
