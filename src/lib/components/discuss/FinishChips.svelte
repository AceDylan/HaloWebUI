<script lang="ts">
	import { toast } from 'svelte-sonner';

	import type { ModeCard, ModeIllustration } from '$lib/apis/discussions';
	import { now } from '$lib/components/teams/clock';
	import { cardFailureText } from '$lib/utils/html-card';
	import { cardDesigning, cardHtml, pictureError, pictureState } from './model';

	/**
	 * 「生成 HTML 卡片」 / 「生成配图」 for a finished answer (精答) or conclusion (讨论台): nothing makes
	 * either on its own any more. Each chip asks for it once; the page follows the run's own
	 * `card` / `illustration` as they move (the chips go once there is one).
	 */
	export let card: ModeCard | null | undefined = null;
	export let illustration: ModeIllustration | null | undefined = null;
	/** Whether this user may generate images at all (else no picture chip). */
	export let pictureAllowed = true;
	export let onCard: () => Promise<unknown>;
	export let onPicture: () => Promise<unknown>;

	let startingCard = false;
	let startingPicture = false;

	$: designing = startingCard || cardDesigning(card, $now);
	$: cardFailed = !designing && (card?.status === 'failed' || card?.status === 'skipped');
	$: picture = pictureState(illustration, $now);
	$: drawing = startingPicture || picture === 'generating';

	const run = async (which: 'card' | 'picture') => {
		if (which === 'card') {
			if (designing) return;
			startingCard = true;
		} else {
			if (drawing) return;
			startingPicture = true;
		}
		try {
			await (which === 'card' ? onCard() : onPicture());
			if (which === 'picture') toast.success('开始配图：先提炼要点再画，通常 1–3 分钟');
		} catch (e: any) {
			toast.error(e?.message || (typeof e === 'string' ? e : '没能开始，请稍后再试'));
		} finally {
			if (which === 'card') startingCard = false;
			else startingPicture = false;
		}
	};
</script>

{#if !cardHtml(card)}
	<button
		type="button"
		class="dc-chip {cardFailed ? '!text-amber-700 dark:!text-amber-300' : ''}"
		disabled={designing}
		title={cardFailed
			? `上次没生成：${cardFailureText(card)}`
			: 'AGY 按这份结果设计一张 HTML 可视化卡片，通常 10–60 秒'}
		on:click={() => run('card')}
		data-make-card={designing ? 'designing' : cardFailed ? 'failed' : 'idle'}
	>
		{designing ? '正在排版卡片…' : cardFailed ? '重试 HTML 卡片' : '生成 HTML 卡片'}
	</button>
{/if}
{#if pictureAllowed && picture !== 'ready'}
	<button
		type="button"
		class="dc-chip {picture === 'failed' && !drawing ? '!text-amber-700 dark:!text-amber-300' : ''}"
		disabled={drawing}
		title={picture === 'failed' && !drawing
			? `上次没画成：${pictureError(illustration, $now)}`
			: '按「手绘万能图」模板把结果画成一张图，放在结果上方，也存进生图图库'}
		on:click={() => run('picture')}
		data-make-picture={drawing ? 'generating' : picture === 'failed' ? 'failed' : 'idle'}
	>
		{drawing ? '配图中…' : picture === 'failed' ? '重新配图' : '生成配图'}
	</button>
{/if}
