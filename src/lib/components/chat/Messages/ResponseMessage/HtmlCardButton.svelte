<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { LayoutTemplate } from 'lucide-svelte';

	import { generateMessageHtmlCard } from '$lib/apis/chats';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { now } from '$lib/components/teams/clock';
	import { cardBusy, cardFailureText, messageCardEntry, type HtmlCardEntry } from '$lib/utils/html-card';

	/**
	 * 「生成 HTML 卡片」 under a finished reply: nothing designs a card on its own any more; this asks
	 * AGY for one (the same design as before, from the reply's text). The card arrives in the reply
	 * itself (a content update over the socket); while it is designed the button spins.
	 */
	export let chatId: string;
	export let message: any;
	/** The toolbar's own button look (desktop or phone). */
	export let buttonClass = '';

	let requested: HtmlCardEntry | null = null;
	let starting = false;
	let lastStatus = '';

	// The newer of what the page was told (socket / saved message) and what this click got back.
	$: own = messageCardEntry(message);
	$: entry =
		requested && (requested.startedAt ?? 0) > (own?.startedAt ?? 0) ? requested : (own ?? requested);
	$: busy = starting || cardBusy(entry, $now * 1000);
	$: seconds = busy && entry?.startedAt ? Math.max(0, Math.round($now - entry.startedAt / 1000)) : 0;
	$: failed = !busy && (entry?.status === 'failed' || entry?.status === 'skipped');
	$: label = busy
		? `正在生成 HTML 卡片${seconds ? ` · 已 ${seconds}s` : ''}`
		: failed
			? `上次没生成：${cardFailureText(entry)} · 点击重试`
			: '生成 HTML 卡片';

	// Tell once when a card asked for here did not come out.
	$: {
		const status = `${entry?.status ?? ''}`;
		if (lastStatus === 'designing' && failed) {
			toast.error(`HTML 卡片没生成：${cardFailureText(entry)}`);
		}
		lastStatus = busy ? 'designing' : status;
	}

	const start = async () => {
		if (busy || !chatId || !message?.id) return;
		starting = true;
		try {
			requested = await generateMessageHtmlCard(localStorage.token, chatId, message.id);
			lastStatus = 'designing';
		} catch (error) {
			toast.error(typeof error === 'string' && error ? error : 'HTML 卡片没能开始生成，请稍后再试');
		} finally {
			starting = false;
		}
	};
</script>

<Tooltip content={label} placement="bottom">
	<button
		type="button"
		class="{buttonClass} {failed ? 'text-amber-600 dark:text-amber-400' : ''}"
		aria-label={label}
		aria-busy={busy}
		disabled={busy}
		data-halo-html-card={busy ? 'designing' : failed ? 'failed' : 'idle'}
		on:click={start}
	>
		{#if busy}
			<Spinner className="size-4" />
		{:else}
			<LayoutTemplate class="w-4 h-4" strokeWidth={2} />
		{/if}
	</button>
</Tooltip>
