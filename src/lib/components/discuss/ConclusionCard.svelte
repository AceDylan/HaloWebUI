<script lang="ts">
	import { toast } from 'svelte-sonner';

	import type { DiscussAsk } from '$lib/apis/discussions';
	import { copyToClipboard } from '$lib/utils';
	import ReportMarkdown from '$lib/components/teams/ReportMarkdown.svelte';
	import { now } from '$lib/components/teams/clock';
	import SeatAvatar from './SeatAvatar.svelte';
	import { domainOf, linkCitations, parseSections, retryText, sectionKind, seconds, tokens } from './model';

	/** The moderator's conclusion of one question: the answer first, then agreements,
	 *  disagreements, positions and next steps as separate panels. */
	export let ask: DiscussAsk;
	/** 「接下来」 under the latest conclusion: carry it into a chat, a team, or Hermes. */
	export let next: {
		chat?: () => void;
		answer?: (() => void) | null;
		team?: (() => void) | null;
		studio?: (() => void) | null;
		hermes?: (() => void) | null;
	} | null = null;
	/** 「重写结论」 on a conclusion that failed (only once the question has settled). */
	export let rewrite: (() => void) | null = null;
	export let busy = false;

	$: conclusion = ask.conclusion;
	$: sources = ask.research?.status === 'done' ? ask.research.sources : [];
	$: cite = (md: string) => linkCitations(md, sources);
	$: state = conclusion.status;
	$: sections = state === 'done' ? parseSections(conclusion.content) : [];
	$: answer = sections.length ? sections[0] : null;
	$: rest = sections.slice(1).map((s, i) => ({ ...s, kind: sectionKind(s.title, i + 1) }));
	$: pair = rest.filter((s) => s.kind === 'agree' || s.kind === 'disagree');
	$: others = rest.filter((s) => s.kind !== 'agree' && s.kind !== 'disagree');
	$: took = seconds(conclusion.startedAt, conclusion.endedAt);
	$: total = ask.usage?.total_tokens;
	$: waiting = state === 'waiting' && ask.status !== 'concluding';
	// a stand-in seat writes it when the moderator cannot
	$: writer = conclusion.standIn ? { model: conclusion.model, name: conclusion.name } : ask.moderator;
	$: retrying = conclusion.retry ? retryText(conclusion.retry, $now) : '';
	$: ringState = (
		state === 'streaming' ? (conclusion.thinking && !conclusion.content ? 'thinking' : 'streaming') : state
	) as 'thinking' | 'streaming' | 'waiting' | 'done' | 'error' | 'stopped';

	const MARK: Record<string, string> = { agree: '✓', disagree: '≠', positions: '◎', next: '→', other: '·' };

	const copy = async () => {
		if (await copyToClipboard(conclusion.content)) toast.success('已复制结论');
	};
</script>

{#if waiting}
	<div
		class="flex items-center gap-3 rounded-2xl border border-dashed border-gray-300/70 px-4 py-3 text-xs text-gray-400 dark:border-gray-700/70 dark:text-gray-500"
		data-discuss-conclusion="waiting"
	>
		<SeatAvatar model={ask.moderator.model} name={ask.moderator.name} hue={268} state="waiting" size={20} />
		{#if ask.status === 'running'}
			所有人发言后，主持人 {ask.moderator.name} 会在这里写结论
		{:else}
			还没有结论{ask.turns.some((t) => t.status === 'done') ? '——可以让主持人根据已有发言直接总结' : ''}
		{/if}
	</div>
{:else}
	<section
		class="dc-conclusion"
		data-state={state}
		aria-busy={state === 'streaming'}
		data-discuss-conclusion={state}
	>
		<header class="flex items-center gap-2.5 px-5 pt-4 pb-1">
			<SeatAvatar
				model={writer.model}
				name={writer.name}
				hue={268}
				state={ringState}
				size={24}
			/>
			<div class="min-w-0 flex-1">
				<div class="tm-eyebrow">主持人结论</div>
				<div class="truncate text-xs text-gray-500 dark:text-gray-400">
					{writer.name}{conclusion.standIn ? ' 代写' : ''}
					{#if retrying}
						· {retrying}
					{:else if state === 'streaming'}
						· {conclusion.thinking && !conclusion.content ? '思考中…' : '正在写结论…'}
					{:else if state === 'done'}
						{[took !== null ? `用时 ${took}s` : '', total ? `本问共 ${tokens(total)} tokens` : '']
							.filter(Boolean)
							.map((s) => ` · ${s}`)
							.join('')}
					{:else if state === 'error'}
						· 没写完：{conclusion.error}
					{:else if state === 'stopped'}
						· 被停止
					{/if}
				</div>
			</div>
			{#if conclusion.content && state !== 'streaming'}
				<button
					type="button"
					class="dc-chip"
					on:click={copy}
					data-discuss-copy-conclusion>复制</button
				>
			{/if}
		</header>

		<div class="px-5 pb-5">
			{#if conclusion.standIn}
				<p class="mb-1.5 text-[11px] text-amber-600 dark:text-amber-300" title={conclusion.standIn.error ?? ''} data-discuss-stand-in>
					主持人 {conclusion.standIn.for} 暂时写不了（{conclusion.standIn.reason}），由 {conclusion.name} 代写
				</p>
			{/if}
			{#if conclusion.imagesDropped}
				<p class="mb-1.5 text-[11px] text-amber-600 dark:text-amber-300" data-discuss-images-dropped>主持人没能看图，按文字总结</p>
			{/if}
			{#if state === 'error' && rewrite}
				<button type="button" class="dc-chip mb-2" disabled={busy} on:click={rewrite} data-discuss-rewrite>重写结论</button>
			{/if}
			{#if state === 'streaming' || !answer}
				{#if conclusion.content}
					<ReportMarkdown id="dc-conclusion-{ask.id}" content={cite(conclusion.content)} />
				{:else if state === 'streaming' || state === 'waiting'}
					<div class="flex flex-col gap-2 pt-2" style="--dc-hue: 268">
						<div class="dc-skeleton w-full" />
						<div class="dc-skeleton w-11/12" />
						<div class="dc-skeleton w-3/4" />
					</div>
				{/if}
			{:else}
				{#if answer.title}
					<h3 class="sr-only">{answer.title}</h3>
				{/if}
				<div data-discuss-answer>
					<ReportMarkdown id="dc-answer-{ask.id}" content={cite(answer.body)} />
				</div>

				{#if pair.length}
					<div class="mt-4 grid items-start gap-3 {pair.length > 1 ? 'md:grid-cols-2' : ''}">
						{#each pair as section, i (section.title + i)}
							<div class="dc-section px-4 py-3" data-kind={section.kind}>
								<div class="mb-1 flex items-center gap-1.5 text-[12.5px] font-semibold text-gray-800 dark:text-gray-100">
									<span class="dc-section-mark" aria-hidden="true">{MARK[section.kind]}</span>
									{section.title}
								</div>
								<ReportMarkdown id="dc-{section.kind}-{ask.id}" content={cite(section.body)} />
							</div>
						{/each}
					</div>
				{/if}
				{#each others as section, i (section.title + i)}
					<div class="dc-section mt-3 px-4 py-3" data-kind={section.kind}>
						<div class="mb-1 flex items-center gap-1.5 text-[12.5px] font-semibold text-gray-800 dark:text-gray-100">
							<span class="dc-section-mark" aria-hidden="true">{MARK[section.kind]}</span>
							{section.title}
						</div>
						<ReportMarkdown id="dc-{section.kind}-{i}-{ask.id}" content={cite(section.body)} />
					</div>
				{/each}
			{/if}

			{#if sources.length && state === 'done'}
				<div class="mt-4 flex flex-wrap items-center gap-1.5 text-[11px] text-gray-400" data-discuss-conclusion-sources>
					<span>来源</span>
					{#each sources as source (source.n)}
						<a href={source.url} target="_blank" rel="noopener noreferrer" class="dc-chip !py-0.5 max-w-[14rem] truncate" title={source.title}
							><span class="tm-num">[{source.n}]</span> {domainOf(source.url)}</a
						>
					{/each}
				</div>
			{/if}

			{#if next && state === 'done'}
				<div class="mt-4 flex flex-wrap items-center gap-1.5 border-t border-gray-100 pt-3 dark:border-gray-800/70" data-discuss-next>
					<span class="mr-0.5 text-[11px] text-gray-400">接下来</span>
					{#if next.chat}
						<button type="button" class="dc-chip" on:click={next.chat} data-discuss-to-chat title="新对话里接着聊，结论放进输入框">继续对话</button>
					{/if}
					{#if next.answer}
						<button type="button" class="dc-chip" on:click={next.answer} data-discuss-to-answer title="最合适的助手带着结论把这个问题答细">交给精答深挖</button>
					{/if}
					{#if next.team}
						<button type="button" class="dc-chip" on:click={next.team} data-discuss-to-team title="一支 AI 团队按结论去做">交给协作台</button>
					{/if}
					{#if next.studio}
						<button type="button" class="dc-chip" on:click={next.studio} data-discuss-to-studio title="生图工作台：把结论画成一张图">画成图</button>
					{/if}
					{#if next.hermes}
						<button type="button" class="dc-chip" on:click={next.hermes} data-discuss-hermes title="Hermes 联网核查结论里的说法">交给 Hermes 核查</button>
					{/if}
				</div>
			{/if}

			{#if ask.previousConclusions?.length && state !== 'streaming'}
				<details class="mt-4 text-sm">
					<summary class="cursor-pointer text-xs text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-100">
						上一版结论（{ask.previousConclusions.length}）
					</summary>
					{#each [...ask.previousConclusions].reverse() as old, i (i)}
						<div class="dc-section mt-2 px-4 py-3 opacity-80">
							<ReportMarkdown id="dc-old-{ask.id}-{i}" content={old.content} />
						</div>
					{/each}
				</details>
			{/if}
		</div>
	</section>
{/if}
