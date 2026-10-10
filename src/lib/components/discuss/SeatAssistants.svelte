<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { slide } from 'svelte/transition';

	import { choiceLabel } from '$lib/apis/assistant-library';
	import type { DiscussAsk } from '$lib/apis/discussions';
	import { modeSpec, seatHue } from './model';

	/** How one question's table was set (主持人安排: the moderator's format, rounds and seats, and
	 * why), which assistant each seat speaks with: matched (with why), picked, or none; its
	 * settings on request, and the undo of an upgrade this question made. */
	export let ask: DiscussAsk;
	/** Undo is offered on the last question only (the backend undoes that one). */
	export let undoable = false;
	export let busy = false;

	const dispatch = createEventDispatcher<{ undo: string }>();
	let open: string | null = null;

	$: planning = ask.planning ?? null;
	$: planned = !!planning && (planning.status === 'done' || planning.status === 'error') && ask.seats.length > 0;
	$: matching = ask.matching ?? null;
	$: rows = ask.seats
		.map((seat, si) => ({ seat, si, choice: seat.assistant_choice ?? null }))
		.filter((r) => r.choice || r.seat.duty);
</script>

{#if planning || matching || rows.length}
	<div class="flex flex-col gap-1.5" data-discuss-assistants>
		{#if planning?.status === 'waiting' || planning?.status === 'running'}
			<div class="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400" data-discuss-planning>
				<span class="size-3 animate-spin rounded-full border-2 border-current border-r-transparent" aria-hidden="true" />
				主持人 {ask.moderator.name} 正在读题，安排讨论方式、轮数和参与模型…
			</div>
		{:else if planning?.status === 'stopped'}
			<div class="text-xs text-gray-500 dark:text-gray-400" data-discuss-planning>主持人还没安排好就停下了</div>
		{/if}
		{#if planning?.status === 'error' && planning.error}
			<div class="text-xs text-amber-600 dark:text-amber-400" data-discuss-planning-error>{planning.error}</div>
		{/if}
		{#if planned}
			<div class="rounded-xl bg-gray-500/5 px-3 py-2 text-xs" data-discuss-plan>
				<span class="font-medium text-gray-800 dark:text-gray-100">主持人的安排</span>
				<span class="text-gray-500 dark:text-gray-400">· {modeSpec(ask.mode).label} · {ask.seats.length} 位 · {ask.rounds} 轮</span>
				{#if planning?.reason}
					<div class="mt-0.5 text-gray-600 dark:text-gray-300">{planning.reason}</div>
				{/if}
			</div>
		{/if}
		{#if matching?.status === 'waiting' || matching?.status === 'running'}
			<div class="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400" data-discuss-matching>
				<span class="size-3 animate-spin rounded-full border-2 border-current border-r-transparent" aria-hidden="true" />
				正在为每位参与者匹配助手…
			</div>
		{:else if matching?.status === 'error' && matching.error}
			<div class="text-xs text-amber-600 dark:text-amber-400" data-discuss-matching-error>{matching.error}</div>
		{/if}
		{#each rows as { seat, si, choice } (seat.id)}
			<div class="rounded-xl bg-gray-500/5 px-3 py-2 text-xs" data-discuss-seat-assistant={seat.id}>
				<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
					<span class="font-medium" style="color: hsl({seatHue(si)} 70% 50%)">{seat.label}</span>
					{#if choice && choice.action !== 'generic'}
						<span class="text-gray-800 dark:text-gray-100">{choice.emoji || '✦'} {choice.name}</span>
						<span class="rounded-full bg-gray-500/10 px-1.5 py-px text-[10px] text-gray-500 dark:text-gray-400" data-discuss-choice-action
							>{choiceLabel(choice.action)}{choice.version ? ` · v${choice.version}` : ''}{choice.reverted ? ' · 已撤销' : ''}</span
						>
					{:else if matching?.status === 'waiting' || matching?.status === 'running'}
						<span class="text-gray-400 dark:text-gray-500">{seat.role || '匹配助手中'}</span>
					{:else}
						<span class="text-gray-500 dark:text-gray-400">通用角色</span>
					{/if}
					{#if choice?.system}
						<button type="button" class="text-gray-500 hover:underline dark:text-gray-400" on:click={() => (open = open === seat.id ? null : seat.id)}
							>{open === seat.id ? '收起设定' : '查看设定'}</button
						>
					{/if}
					{#if undoable && choice?.action === 'update' && !choice.reverted}
						<button
							type="button"
							class="text-gray-500 hover:underline disabled:opacity-40 dark:text-gray-400"
							disabled={busy}
							on:click={() => dispatch('undo', seat.id)}
							data-discuss-undo-assistant={seat.id}>撤销这次升级</button
						>
					{/if}
				</div>
				{#if seat.duty}
					<div class="mt-0.5 text-gray-600 dark:text-gray-300">本次职责：{seat.duty}</div>
				{/if}
				{#if choice?.reason || choice?.change || choice?.note}
					<div class="mt-0.5 text-gray-500 dark:text-gray-400">
						{[choice.reason, choice.change ? `新增：${choice.change}` : '', choice.note].filter(Boolean).join('；')}
					</div>
				{/if}
				{#if open === seat.id && choice?.system}
					<pre
						class="mt-1.5 max-h-56 overflow-y-auto whitespace-pre-wrap rounded-lg bg-gray-500/5 px-2 py-1.5 font-sans text-[11px] leading-relaxed text-gray-700 dark:text-gray-300"
						transition:slide={{ duration: 140 }}>{choice.system}</pre>
				{/if}
			</div>
		{/each}
	</div>
{/if}
