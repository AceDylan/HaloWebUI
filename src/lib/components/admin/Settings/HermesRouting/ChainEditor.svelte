<script lang="ts">
	// An ordered fallback chain: numbered chips joined by a conduit, each can move or go,
	// and the models left over can be added at the end (up to `limit`).
	import { createEventDispatcher } from 'svelte';
	import {
		chainAdd,
		chainCandidates,
		chainMove,
		chainRemove,
		isOAuthModelId,
		modelFamily,
		modelLabel
	} from '$lib/utils/hermes-routing';

	export let chain: string[] = [];
	export let models: string[] = [];
	export let primary = '';
	export let limit = 3;
	export let compact = false;
	export let emptyText = '不兜底';
	export let label = '兜底链';

	const dispatch = createEventDispatcher<{ change: string[] }>();
	const emit = (next: string[]) => {
		if (JSON.stringify(next) !== JSON.stringify(chain)) dispatch('change', next);
	};

	$: candidates = chainCandidates(models, chain, primary);
	$: customCandidates = candidates.filter((id) => !isOAuthModelId(id));
	$: oauthCandidates = candidates.filter((id) => isOAuthModelId(id));
</script>

<div class="hr-chain" class:compact aria-label={label} role="list">
	{#if chain.length === 0}
		<span class="hr-chain-empty">{emptyText}</span>
	{/if}
	{#each chain as id, i (id)}
		{#if i > 0}<span class="hr-link" aria-hidden="true"></span>{/if}
		<span class="hr-chip" role="listitem" data-model={id}>
			<span class="hr-chip-no">{i + 1}</span>
			<span class="hr-dot" data-family={modelFamily(id)} aria-hidden="true"></span>
			<span class="hr-chip-name">{modelLabel(id)}</span>
			<span class="hr-chip-tools">
				<button
					type="button"
					class="hr-chip-btn"
					disabled={i === 0}
					title="往前挪"
					aria-label="把 {id} 往前挪"
					on:click={() => emit(chainMove(chain, i, -1))}>‹</button
				>
				<button
					type="button"
					class="hr-chip-btn"
					disabled={i === chain.length - 1}
					title="往后挪"
					aria-label="把 {id} 往后挪"
					on:click={() => emit(chainMove(chain, i, 1))}>›</button
				>
				<button
					type="button"
					class="hr-chip-btn hr-chip-del"
					title="移除"
					aria-label="移除 {id}"
					on:click={() => emit(chainRemove(chain, i))}>×</button
				>
			</span>
		</span>
	{/each}
	{#if chain.length < limit && candidates.length}
		<span class="hr-add">
			{#each customCandidates as id (id)}
				<button
					type="button"
					class="hr-add-btn"
					data-add={id}
					title="加到兜底链末尾"
					on:click={() => emit(chainAdd(chain, id, limit))}
				>
					+ {id}
				</button>
			{/each}
			{#if oauthCandidates.length > 0}
				<select
					class="hr-add-btn hr-add-select"
					aria-label="添加已登录模型到{label}"
					data-add-oauth
					value=""
					on:change={(e) => {
						const el = e.currentTarget;
						const picked = el.value || el.options?.[el.selectedIndex]?.value || '';
						if (picked) {
							emit(chainAdd(chain, picked, limit));
							el.value = '';
						}
					}}
				>
					<option value="">+ 已登录模型</option>
					{#each oauthCandidates as id (id)}
						<option value={id}>{modelLabel(id)}</option>
					{/each}
				</select>
			{/if}
		</span>
	{/if}
</div>

<style>
	.hr-chain {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.35rem;
		min-height: 1.9rem;
	}
	.hr-chain-empty {
		font-size: 0.72rem;
		color: rgb(148 163 184);
	}
	.hr-chip {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		border-radius: 0.6rem;
		border: 1px solid rgb(15 23 42 / 0.12);
		background: rgb(255 255 255 / 0.75);
		padding: 0.2rem 0.25rem 0.2rem 0.4rem;
		font-size: 0.74rem;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		color: rgb(30 41 59);
	}
	:global(.dark) .hr-chip {
		border-color: rgb(255 255 255 / 0.1);
		background: rgb(255 255 255 / 0.04);
		color: rgb(226 232 240);
	}
	.compact .hr-chip {
		font-size: 0.68rem;
		padding: 0.12rem 0.2rem 0.12rem 0.35rem;
	}
	.hr-chip-no {
		font-size: 0.62rem;
		font-weight: 600;
		color: rgb(100 116 139);
		min-width: 0.7rem;
		text-align: center;
	}
	.hr-chip-tools {
		display: inline-flex;
		gap: 1px;
		margin-left: 0.1rem;
	}
	.hr-chip-btn {
		width: 1.15rem;
		height: 1.15rem;
		border-radius: 0.35rem;
		line-height: 1;
		font-size: 0.8rem;
		color: rgb(100 116 139);
	}
	.hr-chip-btn:hover:not(:disabled) {
		background: rgb(15 23 42 / 0.06);
		color: rgb(15 23 42);
	}
	:global(.dark) .hr-chip-btn:hover:not(:disabled) {
		background: rgb(255 255 255 / 0.08);
		color: #fff;
	}
	.hr-chip-btn:disabled {
		opacity: 0.25;
	}
	.hr-chip-del:hover:not(:disabled) {
		color: rgb(225 29 72) !important;
	}
	.hr-link {
		width: 0.9rem;
		height: 1px;
		background: linear-gradient(90deg, rgb(100 116 139 / 0.2), rgb(100 116 139 / 0.6));
	}
	.hr-add {
		display: inline-flex;
		flex-wrap: wrap;
		gap: 0.25rem;
		margin-left: 0.2rem;
	}
	.hr-add-btn {
		border-radius: 0.55rem;
		border: 1px dashed rgb(100 116 139 / 0.35);
		padding: 0.16rem 0.45rem;
		font-size: 0.68rem;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		color: rgb(100 116 139);
		transition:
			border-color 0.15s ease,
			color 0.15s ease;
	}
	.hr-add-btn:hover {
		border-color: var(--scifi-cyan, rgb(8 145 178));
		color: var(--scifi-cyan, rgb(8 145 178));
	}
	.hr-add-select {
		background: transparent;
		cursor: pointer;
	}
	:global(.dark) .hr-add-select {
		color-scheme: dark;
	}
	:global(.dark) .hr-add-select option {
		background-color: #0f172a;
		color: #e2e8f0;
	}
	:global(html.halo-scifi.dark) .hr-link {
		background: linear-gradient(90deg, rgb(94 231 255 / 0.15), rgb(94 231 255 / 0.7));
		box-shadow: 0 0 6px rgb(94 231 255 / 0.5);
	}
	:global(html.halo-scifi.dark) .hr-chip {
		border-color: rgb(94 231 255 / 0.18);
		background: rgb(9 13 28 / 0.6);
	}
</style>
