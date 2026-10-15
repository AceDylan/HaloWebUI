<script lang="ts">
	import type { ModeCard } from '$lib/apis/discussions';
	import ReportMarkdown from '$lib/components/teams/ReportMarkdown.svelte';
	import { cardHtml, withCard } from './model';

	/**
	 * A finished answer / conclusion / result: once its 结论卡片 is designed, the card the way a
	 * chat reply shows one (the chat's renderer, 「显示原文」 brings the text back); the text alone
	 * until then, or when there is no card. `withText={false}`: only the card, nothing without one
	 * (a page that shows the text anyway).
	 */
	export let id: string;
	export let content: string;
	export let card: ModeCard | null | undefined = null;
	export let withText = true;

	const history = { messages: {}, currentId: null };
	let ContentRenderer: any = null;
	let loading = false;

	$: html = cardHtml(card);
	$: if (html && !ContentRenderer && !loading) load();

	async function load() {
		loading = true;
		try {
			ContentRenderer = (await import('$lib/components/chat/Messages/ContentRenderer.svelte'))
				.default;
		} finally {
			loading = false;
		}
	}
</script>

{#if html && ContentRenderer}
	<div data-conclusion-card>
		<svelte:component
			this={ContentRenderer}
			id={`${id}-card`}
			content={withCard(withText ? content : '', html)}
			{history}
			floatingButtons={false}
			forceExpand={true}
			autoOpenArtifacts={false}
		/>
	</div>
{:else if withText}
	<ReportMarkdown {id} {content} />
{/if}
