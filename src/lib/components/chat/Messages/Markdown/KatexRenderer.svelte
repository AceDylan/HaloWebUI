<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import katex from 'katex';
	import 'katex/contrib/mhchem';
	import 'katex/dist/katex.min.css';
	import { Copy } from 'lucide-svelte';

	import { copyToClipboard } from '$lib/utils';
	import { ensureKatexCopyTextEnabled, getKatexCopyText } from '$lib/utils/katex-copy';
	import { KATEX_STRICT } from '$lib/utils/katex-options';
	import { settings } from '$lib/stores';

	const i18n = getContext('i18n');

	export let content: string;
	export let displayMode: boolean = false;
	export let source: string | null = null;

	const copyFormula = async () => {
		const copied = await copyToClipboard(
			getKatexCopyText({
				source,
				content,
				displayMode
			})
		);

		if (copied) {
			toast.success($i18n.t('Copying to clipboard was successful!'));
		}
	};

	onMount(() => {
		void ensureKatexCopyTextEnabled();
	});
</script>

{#if displayMode}
	<div class="katex-copy-container katex-copy-container-block group">
		{#if $settings?.showFormulaQuickCopyButton ?? true}
			<button
				type="button"
				class="katex-copy-button"
				title={$i18n.t('Copy')}
				aria-label={$i18n.t('Copy')}
				on:click|stopPropagation={copyFormula}
			>
				<Copy class="size-3.5" strokeWidth={2.1} />
			</button>
		{/if}

		{@html katex.renderToString(content, {
			displayMode,
			throwOnError: false,
			strict: KATEX_STRICT
		})}
	</div>
{:else}
	<span class="katex-copy-container katex-copy-container-inline group">
		{#if $settings?.showFormulaQuickCopyButton ?? true}
			<button
				type="button"
				class="katex-copy-button"
				title={$i18n.t('Copy')}
				aria-label={$i18n.t('Copy')}
				on:click|stopPropagation={copyFormula}
			>
				<Copy class="size-3" strokeWidth={2.1} />
			</button>
		{/if}

		{@html katex.renderToString(content, {
			displayMode,
			throwOnError: false,
			strict: KATEX_STRICT
		})}
	</span>
{/if}

<style>
	.katex-copy-container {
		position: relative;
		max-width: 100%;
	}

	.katex-copy-container-inline {
		display: inline-block;
		vertical-align: baseline;
	}

	.katex-copy-container-block {
		display: block;
	}

	.katex-copy-button {
		position: absolute;
		z-index: 10;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border: none;
		border-radius: 9999px;
		padding: 0.25rem;
		background: rgba(255, 255, 255, 0.92);
		color: rgb(75 85 99);
		box-shadow: 0 1px 2px rgba(15, 23, 42, 0.16);
		opacity: 0;
		pointer-events: none;
		transition:
			opacity 0.15s ease,
			transform 0.15s ease,
			background-color 0.15s ease;
	}

	.katex-copy-container:hover .katex-copy-button,
	.katex-copy-container:focus-within .katex-copy-button,
	.katex-copy-button:focus-visible {
		opacity: 1;
		pointer-events: auto;
	}

	.katex-copy-button:hover {
		transform: scale(1.04);
		background: rgb(255 255 255);
	}

	.katex-copy-button:focus-visible {
		outline: 2px solid rgb(59 130 246 / 0.65);
		outline-offset: 2px;
	}

	.katex-copy-container-inline .katex-copy-button {
		top: -0.55rem;
		right: -0.55rem;
	}

	.katex-copy-container-block .katex-copy-button {
		top: 0.5rem;
		right: 0.5rem;
	}

	:global(.dark) .katex-copy-button {
		background: rgba(17, 24, 39, 0.94);
		color: rgb(229 231 235);
		box-shadow: 0 1px 3px rgba(0, 0, 0, 0.34);
	}

	:global(.dark) .katex-copy-button:hover {
		background: rgb(31 41 55);
	}
</style>
