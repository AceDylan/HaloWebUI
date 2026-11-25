<script lang="ts">
	// One row of star-core pills: pick the model a slot runs on. `emptyLabel` adds the
	// "follow the default" choice (value ""); logged-in OAuth models (e.g. openai-codex:*)
	// sit in a compact inline selector so 10+ account models never flood every row; a value
	// hermes could not map (set from the command line) shows as its own pressed pill.
	import { createEventDispatcher } from 'svelte';
	import {
		isForeignModel,
		isOAuthModelId,
		modelFamily,
		modelLabel
	} from '$lib/utils/hermes-routing';

	export let value = '';
	export let models: string[] = [];
	export let emptyLabel = '';
	export let compact = false;
	export let label = '';
	export let oauthLabel = '已登录模型';

	const dispatch = createEventDispatcher<{ change: string }>();
	const pick = (id: string) => {
		if (id !== value) dispatch('change', id);
	};

	$: customModels = models.filter((id) => !isOAuthModelId(id));
	$: oauthModels = models.filter((id) => isOAuthModelId(id));
	$: oauthSelected = isOAuthModelId(value) && oauthModels.includes(value);
</script>

<div class="hr-picker" class:compact role="radiogroup" aria-label={label}>
	{#if emptyLabel}
		<button
			type="button"
			class="halo-wb-opt hr-pill"
			role="radio"
			aria-checked={value === ''}
			on:click={() => pick('')}
		>
			<span class="hr-dot hr-dot-follow" aria-hidden="true"></span>{emptyLabel}
		</button>
	{/if}
	{#each customModels as id (id)}
		<button
			type="button"
			class="halo-wb-opt hr-pill"
			role="radio"
			data-model={id}
			aria-checked={value === id}
			on:click={() => pick(id)}
		>
			<span class="hr-dot" data-family={modelFamily(id)} aria-hidden="true"></span>{id}
		</button>
	{/each}
	{#if oauthModels.length > 0}
		<div class="hr-oauth-wrap" class:is-active={oauthSelected}>
			<span
				class="hr-dot"
				class:hr-dot-follow={!oauthSelected}
				data-family={oauthSelected ? modelFamily(value) : 'gpt'}
				aria-hidden="true"
			></span>
			<select
				class="hr-oauth-select"
				aria-label="{label}（{oauthLabel}）"
				data-oauth-picker
				value={oauthSelected ? value : ''}
				on:change={(e) => {
					const el = e.currentTarget;
					const next = el.value || el.options?.[el.selectedIndex]?.value || '';
					if (next) pick(next);
				}}
			>
				<option value="" disabled>{oauthLabel}（{oauthModels.length}）</option>
				{#each oauthModels as id (id)}
					<option value={id}>{modelLabel(id)}</option>
				{/each}
			</select>
		</div>
	{/if}
	{#if isForeignModel(value)}
		<span
			class="halo-wb-opt hr-pill"
			role="radio"
			aria-checked="true"
			title="命令行配置的，页面不改它"
		>
			<span class="hr-dot" aria-hidden="true"></span>{modelLabel(value)}
		</span>
	{/if}
</div>

<style>
	.hr-picker {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
	}
	.hr-picker.compact {
		gap: 0.3rem;
	}
	.hr-picker.compact .hr-pill {
		padding: 0.22rem 0.5rem;
		font-size: 0.7rem;
	}
	.hr-pill {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		letter-spacing: -0.01em;
	}
	.hr-oauth-wrap {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		border-radius: 0.65rem;
		border: 1px solid rgb(15 23 42 / 0.14);
		background: rgb(255 255 255 / 0.65);
		padding: 0.18rem 0.45rem;
		transition:
			border-color 0.15s ease,
			box-shadow 0.15s ease;
	}
	:global(.dark) .hr-oauth-wrap {
		border-color: rgb(255 255 255 / 0.12);
		background: rgb(255 255 255 / 0.04);
	}
	.hr-oauth-wrap.is-active {
		border-color: var(--scifi-cyan, #0891b2);
		background: rgb(8 145 178 / 0.1);
		box-shadow: 0 0 0 1px rgb(8 145 178 / 0.18);
	}
	:global(.dark) .hr-oauth-wrap.is-active {
		border-color: var(--scifi-cyan, #5ee7ff);
		background: rgb(94 231 255 / 0.12);
	}
	.hr-oauth-select {
		background: transparent;
		border: 0;
		outline: 0;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.75rem;
		color: inherit;
		max-width: 14rem;
		cursor: pointer;
	}
	.compact .hr-oauth-wrap {
		padding: 0.12rem 0.38rem;
	}
	.compact .hr-oauth-select {
		font-size: 0.7rem;
		max-width: 12rem;
	}
	:global(.dark) .hr-oauth-select {
		color-scheme: dark;
	}
	:global(.dark) .hr-oauth-select option {
		background-color: #0f172a;
		color: #e2e8f0;
	}
</style>
