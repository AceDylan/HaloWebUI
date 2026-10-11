<script lang="ts">
	import type { ModeIllustration } from '$lib/apis/discussions';
	import { now } from '$lib/components/teams/clock';

	/** 结论配图 of a finished answer (精答) or conclusion (讨论台): drawn on its own once the text is
	 *  done, in the owner's 「手绘万能图」 template, and kept in the image studio gallery too. */
	export let illustration: ModeIllustration | null | undefined;
	export let alt = '配图';

	// a picture still "being drawn" long after the server's own limit was cut off by a restart
	const STALE_SECONDS = 8 * 60;

	$: started = Math.floor((illustration?.startedAt ?? 0) / 1000);
	$: status = illustration?.status === 'generating' && started && $now - started > STALE_SECONDS ? 'failed' : illustration?.status;
	$: error = status === 'failed' && illustration?.status === 'generating' ? '配图被中断（服务重启）' : illustration?.error;
	$: elapsed = started ? Math.max(0, $now - started) : 0;
</script>

{#if status === 'generating'}
	<div class="dc-picture tm-live mb-3 flex items-center gap-3 rounded-xl bg-gray-500/5 px-3.5 py-3" data-mode-picture="generating">
		<svg class="size-4 shrink-0 text-gray-400" viewBox="0 0 16 16" fill="none" aria-hidden="true"
			><rect x="2.25" y="3" width="11.5" height="10" rx="1.6" stroke="currentColor" stroke-width="1.3" /><circle cx="6" cy="6.6" r="1.2" stroke="currentColor" stroke-width="1.2" /><path
				d="m2.75 11.5 3.2-2.9 2.3 2 2.1-1.7 2.9 2.6"
				stroke="currentColor"
				stroke-width="1.3"
				stroke-linejoin="round"
			/></svg
		>
		<div class="min-w-0 flex-1 text-xs text-gray-500 dark:text-gray-400">
			<span class="tm-shimmer text-[13px] font-medium text-gray-800 dark:text-gray-100">正在配图</span>
			<span>
				· {illustration?.template ? `「${illustration.template}」· ` : ''}{illustration?.step === 'draw' ? '在画图' : '在提炼图上的要点'}{elapsed
					? ` · 已 ${elapsed}s`
					: ''}
			</span>
		</div>
	</div>
{:else if status === 'ready' && illustration?.url}
	<figure class="dc-picture mb-4" data-mode-picture="ready">
		<a href={illustration.url} target="_blank" rel="noopener noreferrer" class="block overflow-hidden rounded-xl bg-gray-500/5" title="看大图">
			<img src={illustration.url} {alt} class="w-full object-contain" loading="lazy" />
		</a>
		<figcaption class="mt-1.5 text-[11px] text-gray-400 dark:text-gray-500">
			配图：{illustration.template ?? '模板'}{illustration.model ? ` · ${illustration.model}` : ''} · 已存进<a
				href="/workspace/images?tab=gallery"
				class="underline-offset-2 hover:text-gray-700 hover:underline dark:hover:text-gray-200">生图图库</a
			>
		</figcaption>
	</figure>
{:else if status === 'failed'}
	<p class="mb-2 text-[11px] text-gray-400 dark:text-gray-500" title={error ?? ''} data-mode-picture="failed">配图没画成：{error || '生图出错'}</p>
{/if}
