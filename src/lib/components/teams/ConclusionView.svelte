<script lang="ts">
	import { onDestroy, onMount, tick } from 'svelte';
	import { fade } from 'svelte/transition';
	import { toast } from 'svelte-sonner';

	import {
		getTeamConclusion,
		teamFilePath,
		teamFileUrl,
		writeTeamConclusion,
		type ConclusionEntry,
		type Team,
		type TeamConclusion,
		type TeamStage
	} from '$lib/apis/teams';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import { copyToClipboard } from '$lib/utils';
	import type { HeadingItem } from '$lib/utils/headings';
	import ConclusionNext from './ConclusionNext.svelte';
	import ReportMarkdown from './ReportMarkdown.svelte';
	import RunnerBadge from './RunnerBadge.svelte';
	import StatusChip from './StatusChip.svelte';
	import { etaSentence, formatBytes, formatStamp, prepareReport, statusLabel } from './model';
	import { now } from './clock';

	/**
	 * The team's conclusion: the lead's final report (Markdown, images from the workspace), the
	 * files the team produced, and every task's own result. `panel` sits beside the board;
	 * `page` is the full reading view with a table of contents.
	 */
	export let teamId: string;
	export let title = '';
	export let variant: 'panel' | 'page' = 'panel';
	/** Team phase (running / attention / paused / stopped / completed) and the snapshot's brief. */
	export let phase = 'running';
	export let brief: ConclusionEntry | undefined = undefined;
	export let progress: { done: number; total: number } | null = null;
	/** The team's chat and where its conclusion went (from the team record). */
	export let chatId: string | null = null;
	export let outputs: Team['outputs'] = undefined;
	/** The team's stage (the workbench passes it): how long writing the result may still take. */
	export let stage: TeamStage | null = null;
	$: writingEta =
		stage?.key === 'concluding' ? etaSentence(stage.eta, stage.at, $now) : '';

	const POLL_MS = 3000;
	let data: TeamConclusion | null = null;
	let loading = true;
	let error = '';
	let writing = false;
	let copied = false;
	let confirmRewrite = false;
	let timer: ReturnType<typeof setTimeout> | null = null;
	let destroyed = false;
	let headings: HeadingItem[] = [];
	let toc: HeadingItem[] = [];
	let activeHeading = '';
	let openResults = new Set<string>();
	let observer: IntersectionObserver | null = null;
	let lastBrief = '';

	$: status = data?.status ?? 'none';
	$: entry = data?.entry ?? {};
	$: generating = status === 'generating' || writing;
	$: finished = phase === 'completed' || phase === 'stopped';
	$: doneTasks = data?.tasks.filter((t) => t.status === 'done').length ?? progress?.done ?? 0;
	$: fileList = data?.files ?? [];
	$: images = fileList.filter((f) => f.kind === 'image');
	$: others = fileList.filter((f) => f.kind !== 'image');
	// Files the lead placed in the result in full (format 2: the conclusion is the complete result).
	$: included = new Set(entry.included ?? []);
	$: oldFormat = status === 'ready' && entry.source === 'lead' && !entry.format;
	$: reportOpts = {
		workspace: data?.workspace ?? null,
		fileUrl: (path: string) => teamFilePath(teamId, path),
		files: fileList.map((f) => f.path)
	};
	$: prepared = data?.markdown ? prepareReport(data.markdown, reportOpts) : '';
	$: words = (data?.markdown ?? '').replace(/\s+/g, '').length;

	const load = async () => {
		try {
			data = await getTeamConclusion(localStorage.token, teamId);
			error = '';
		} catch (e) {
			error = `${(e as Error)?.message ?? e}`;
		} finally {
			loading = false;
		}
		schedule();
	};

	const schedule = () => {
		if (timer) clearTimeout(timer);
		if (
			destroyed ||
			!(data?.status === 'generating' || writing || data?.entry?.illustration?.status === 'generating')
		)
			return;
		timer = setTimeout(load, POLL_MS);
	};

	// The workbench's snapshot says when the report changed (written / regenerated): reload then.
	$: {
		const key = `${brief?.status ?? ''}:${brief?.generated_at ?? ''}:${brief?.illustration?.status ?? ''}:${brief?.illustration?.at ?? ''}`;
		if (key !== lastBrief) {
			const first = lastBrief === '';
			lastBrief = key;
			if (!first) load();
		}
	}

	const write = async () => {
		if (writing) return;
		writing = true;
		try {
			await writeTeamConclusion(localStorage.token, teamId);
			if (data)
				data = {
					...data,
					status: 'generating',
					entry: { ...data.entry, status: 'generating', error: '' }
				};
			toast.success('负责人开始整理完整结果，通常 1–3 分钟');
		} catch (e) {
			toast.error(`${(e as Error)?.message ?? e}`);
		} finally {
			writing = false;
			schedule();
			setTimeout(load, 800);
		}
	};

	const copy = async () => {
		if (!data?.markdown) return;
		const ok = await copyToClipboard(data.markdown);
		if (ok === false) {
			toast.error('复制失败');
			return;
		}
		copied = true;
		setTimeout(() => (copied = false), 1600);
	};

	const download = () => {
		if (!data?.markdown) return;
		const blob = new Blob([data.markdown], { type: 'text/markdown;charset=utf-8' });
		const a = document.createElement('a');
		a.href = URL.createObjectURL(blob);
		a.download = `${(title || '协作任务').replace(/[\\/:*?"<>|]+/g, ' ').trim()} - 结论.md`;
		a.click();
		setTimeout(() => URL.revokeObjectURL(a.href), 1000);
	};

	const toggleResult = (key: string, open: boolean) => {
		const next = new Set(openResults);
		if (open) next.add(key);
		else next.delete(key);
		openResults = next;
	};

	// Table of contents: real headings only (code blocks are listed in `headings` too).
	const buildToc = async (_h: HeadingItem[]) => {
		await tick();
		toc = _h.filter((h) => /^H[1-4]$/.test(document.getElementById(h.id)?.tagName ?? ''));
		observer?.disconnect();
		if (variant !== 'page' || typeof IntersectionObserver === 'undefined' || !toc.length) return;
		observer = new IntersectionObserver(
			(entries) => {
				const visible = entries
					.filter((e) => e.isIntersecting)
					.sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
				if (visible[0]) activeHeading = visible[0].target.id;
			},
			{ rootMargin: '0px 0px -70% 0px', threshold: 0 }
		);
		for (const h of toc) {
			const el = document.getElementById(h.id);
			if (el) observer.observe(el);
		}
	};
	$: buildToc(headings);
	$: tocMin = toc.length ? Math.min(...toc.map((h) => h.depth)) : 1;

	const jump = (id: string) => {
		activeHeading = id;
		document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	};

	onMount(load);
	onDestroy(() => {
		destroyed = true;
		if (timer) clearTimeout(timer);
		observer?.disconnect();
	});
</script>

<section
	class="team-conclusion flex min-w-0 flex-col"
	data-team-conclusion
	data-status={status}
	aria-label="任务结论"
>
	{#if loading && !data}
		<div class="flex flex-col gap-3 py-2" aria-busy="true">
			<div class="h-6 w-2/3 rounded-lg bg-gray-500/10 animate-pulse" />
			<div class="h-3 w-full rounded bg-gray-500/10 animate-pulse" />
			<div class="h-3 w-5/6 rounded bg-gray-500/10 animate-pulse" />
			<div class="h-3 w-4/6 rounded bg-gray-500/10 animate-pulse" />
		</div>
	{:else if error && !data}
		<div
			class="rounded-2xl border border-red-500/20 bg-red-500/[0.07] px-4 py-3 text-sm text-red-800 dark:text-red-200"
			role="alert"
		>
			读不到结论：{error}
			<button type="button" class="ml-2 underline underline-offset-2" on:click={load}>重试</button>
		</div>
	{:else if status === 'none'}
		<div class="flex flex-col items-center gap-3 px-4 py-10 text-center" data-conclusion-empty>
			<div
				class="tm-card-quiet grid size-12 place-items-center text-gray-400 dark:text-gray-500"
				aria-hidden="true"
			>
				<svg class="size-6" viewBox="0 0 24 24" fill="none"
					><path
						d="M7 3.75h7.5L19.25 8.5v11a.75.75 0 0 1-.75.75h-11.5a.75.75 0 0 1-.75-.75V4.5A.75.75 0 0 1 7 3.75Z M14.25 3.75v5h5 M9.5 12.5h6 M9.5 16h4"
						stroke="currentColor"
						stroke-width="1.4"
						stroke-linecap="round"
						stroke-linejoin="round"
					/></svg
				>
			</div>
			{#if finished && doneTasks > 0}
				<div>
					<div class="text-sm font-medium text-gray-900 dark:text-gray-100">还没有结论</div>
					<p class="mt-1 max-w-sm text-xs leading-relaxed text-gray-500">
						{phase === 'stopped'
							? `协作任务已停止，${doneTasks} 个任务有结果。`
							: ''}让负责人把各成员的成果整合成一份完整结果。
					</p>
				</div>
				<button type="button" class="tm-btn-primary" disabled={writing} on:click={write}
					>{writing ? '正在开始…' : '让负责人写结论'}</button
				>
			{:else}
				<div>
					<div class="text-sm font-medium text-gray-900 dark:text-gray-100">结论还没开始写</div>
					<p class="mt-1 max-w-xs text-xs leading-relaxed text-gray-500">
						所有任务完成后，负责人会把各成员的成果整合成这次任务的完整结果（完整的答案、文档、图片），显示在这里。
					</p>
				</div>
				{#if progress && progress.total}
					<div class="w-full max-w-[14rem]">
						<div class="h-1.5 overflow-hidden rounded-full bg-gray-500/10">
							<div
								class="h-full rounded-full bg-[hsl(var(--tm-accent))] transition-[width] duration-500"
								style="width:{Math.round((progress.done / progress.total) * 100)}%"
							/>
						</div>
						<div class="mt-1 text-[11px] tabular-nums text-gray-400">
							已完成 {progress.done}/{progress.total} 个任务
						</div>
					</div>
				{/if}
			{/if}
		</div>
	{:else}
		<header
			class="flex flex-wrap items-center gap-x-3 gap-y-2 {variant === 'page'
				? 'tm-hairline border-b pb-4'
				: 'pb-3'}"
		>
			<div class="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
				{#if generating}
					<StatusChip
						status="running"
						label={data?.markdown ? '正在重写结论' : '负责人正在整理结果'}
					/>
				{:else if status === 'failed'}
					<StatusChip status="failed" label="生成失败" />
				{:else if status === 'outdated'}
					<StatusChip status="paused" label="上一版结论" />
				{:else}
					<StatusChip status="done" label={entry.source === 'assembled' ? '按记录整理' : '结论'} />
				{/if}
				<span
					class="min-w-0 truncate text-xs text-gray-500 dark:text-gray-400"
					data-conclusion-meta
				>
					{#if entry.model}<span class="font-mono text-gray-700 dark:text-gray-300"
							>{entry.model}</span
						>{#if entry.model_label}<span class="text-gray-400">{' · '}{entry.model_label}</span
							>{/if}{/if}
					{#if entry.generated_at}
						· {formatStamp(entry.generated_at)}{/if}
					{#if entry.tasks_total}
						· {entry.tasks_done}/{entry.tasks_total} 个任务{/if}
					{#if words}
						· {words.toLocaleString('zh-CN')} 字{/if}
				</span>
			</div>
			{#if data?.markdown}
				<div class="flex items-center gap-1">
					<button type="button" class="tm-btn-ghost" on:click={copy} aria-live="polite">
						{#if copied}
							<svg
								class="size-3.5 text-[hsl(var(--tm-accent))]"
								viewBox="0 0 16 16"
								fill="none"
								aria-hidden="true"
								><path
									d="m3.5 8.5 3 3 6-7"
									stroke="currentColor"
									stroke-width="1.7"
									stroke-linecap="round"
									stroke-linejoin="round"
								/></svg
							>已复制
						{:else}
							<svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
								><rect
									x="5"
									y="5"
									width="8.5"
									height="8.5"
									rx="1.8"
									stroke="currentColor"
									stroke-width="1.3"
								/><path
									d="M10.5 3.2V3a1.5 1.5 0 0 0-1.5-1.5H3.5A1.5 1.5 0 0 0 2 3v5.5A1.5 1.5 0 0 0 3.5 10h.2"
									stroke="currentColor"
									stroke-width="1.3"
								/></svg
							>复制
						{/if}
					</button>
					<button
						type="button"
						class="tm-btn-ghost !hidden sm:!inline-flex"
						on:click={download}
						title="下载 Markdown 文件">下载</button
					>
					<button
						type="button"
						class="tm-btn-ghost"
						disabled={generating}
						on:click={() => (confirmRewrite = true)}
						title="让负责人根据现在的记录重新写一遍">重写</button
					>
					{#if variant === 'panel'}
						<a
							href="/teams/{teamId}/conclusion"
							class="tm-btn-primary !gap-1 !px-2.5 !py-1 !text-xs"
							data-conclusion-open
							>全文阅读<svg class="size-3" viewBox="0 0 16 16" fill="none" aria-hidden="true"
								><path
									d="M6 3.5h6.5V10M12.3 3.7 4 12"
									stroke="currentColor"
									stroke-width="1.6"
									stroke-linecap="round"
								/></svg
							></a
						>
					{/if}
				</div>
			{/if}
		</header>

		{#if generating}
			<div
				class="mb-3 overflow-hidden rounded-xl border border-sky-500/20 bg-sky-500/[0.07] text-xs text-sky-900 dark:text-sky-100"
				role="status"
				in:fade={{ duration: 150 }}
			>
				<div class="h-0.5 w-full overflow-hidden bg-sky-500/15">
					<div class="conclusion-progress h-full w-1/3 bg-sky-500" />
				</div>
				<div class="px-3 py-2">
					负责人{entry.model ? `（${entry.model}）` : ''}正在把 {data?.tasks.length ??
						progress?.total ??
						''} 个任务的成果和工作目录里的产出整合成完整结果，成员写好的成品文件会原样放进来，{writingEta || '通常 1–3 分钟'}。{data?.markdown
						? '下面是上一版。'
						: ''}
				</div>
			</div>
		{/if}
		{#if status === 'outdated' && !generating}
			<div
				class="mb-3 rounded-xl border border-amber-500/20 bg-amber-500/[0.07] px-3 py-2 text-xs text-amber-900 dark:text-amber-100"
				role="status"
				data-conclusion-outdated
			>
				团队按你的要求接着干活了，这是上一版结论；新的任务做完后负责人会重写。
			</div>
		{/if}
		{#if oldFormat && !generating}
			<div
				class="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-sky-500/20 bg-sky-500/[0.06] px-3 py-2 text-xs text-sky-900 dark:text-sky-100"
				data-conclusion-old-format
			>
				<span class="min-w-0 flex-1"
					>这是旧版的概述式结论。现在的结论就是任务的完整结果——成员写好的完整文档会原样放进来。</span
				>
				<button
					type="button"
					class="shrink-0 font-medium underline underline-offset-2"
					disabled={writing}
					on:click={write}>整理成完整结果</button
				>
			</div>
		{/if}
		{#if status === 'failed' && entry.error}
			<div
				class="mb-3 rounded-xl border border-red-500/20 bg-red-500/[0.07] px-3 py-2 text-xs text-red-800 dark:text-red-200"
				role="alert"
			>
				{entry.error}
				<button
					type="button"
					class="ml-1 underline underline-offset-2"
					on:click={write}
					disabled={writing}>重新生成</button
				>
			</div>
		{/if}
		{#if entry.source === 'assembled' && !generating}
			<div
				class="mb-3 rounded-xl border border-amber-500/20 bg-amber-500/[0.07] px-3 py-2 text-xs text-amber-900 dark:text-amber-100"
			>
				负责人模型这次没有给出结论，下面按各任务的记录整理。{entry.fallback_reason
					? `（${entry.fallback_reason}）`
					: ''}
			</div>
		{/if}

		{#if prepared}
			<div class={variant === 'page' ? 'grid gap-8 pt-6 lg:grid-cols-[13rem_minmax(0,1fr)]' : ''}>
				{#if variant === 'page' && toc.length > 2}
					<nav class="hidden lg:block" aria-label="结论目录">
						<div class="sticky top-4 max-h-[calc(100dvh-6rem)] overflow-y-auto pr-2">
							<div class="mb-2 text-[11px] font-medium uppercase tracking-wider text-gray-400">
								目录
							</div>
							<ol class="tm-hairline flex flex-col gap-0.5 border-l">
								{#each toc as h (h.id)}
									<li>
										<button
											type="button"
											class="-ml-px block w-full border-l-2 py-1 pr-1 text-left text-[13px] leading-snug transition
											{activeHeading === h.id
												? 'border-sky-500 font-medium text-gray-900 dark:border-sky-400 dark:text-gray-100'
												: 'border-transparent text-gray-500 hover:text-gray-900 dark:hover:text-gray-200'}"
											style="padding-left:{0.75 + (h.depth - tocMin) * 0.75}rem"
											on:click={() => jump(h.id)}>{h.text}</button
										>
									</li>
								{/each}
							</ol>
						</div>
					</nav>
				{/if}
				<div class="min-w-0">
					{#if variant === 'page' && toc.length > 2}
						<details class="tm-card-quiet mb-4 px-3 py-2 text-sm lg:hidden">
							<summary
								class="cursor-pointer select-none text-xs font-medium text-gray-600 dark:text-gray-300"
								>目录 · {toc.length} 节</summary
							>
							<ol class="mt-2 flex flex-col gap-1">
								{#each toc as h (h.id)}
									<li style="padding-left:{(h.depth - tocMin) * 0.75}rem">
										<button
											type="button"
											class="py-0.5 text-left text-[13px] text-gray-600 dark:text-gray-300"
											on:click={() => jump(h.id)}>{h.text}</button
										>
									</li>
								{/each}
							</ol>
						</details>
					{/if}
					<article class="{generating ? 'opacity-60' : ''} transition-opacity" data-team-report>
						<ReportMarkdown
							id={`team-report-${teamId.slice(0, 8)}`}
							content={prepared}
							size={variant}
							bind:headings
						/>
					</article>
				</div>
			</div>
		{/if}

		{#if data?.markdown && !generating && status !== 'outdated'}
			<ConclusionNext
				{teamId}
				{chatId}
				{outputs}
				generatedAt={entry.generated_at}
				{variant}
				illustration={entry.illustration}
				on:illustrate={(e) => {
					if (data) data = { ...data, entry: { ...data.entry, illustration: e.detail } };
					schedule();
				}}
			/>
		{/if}

		{#if fileList.length}
			<section
				class="mt-8 {variant === 'page' ? 'lg:ml-[15rem]' : ''}"
				aria-label="产出文件"
				data-conclusion-files
			>
				<h3 class="tm-eyebrow mb-3">
					产出文件 <span class="tm-num ml-1 font-normal normal-case">{fileList.length}</span>
				</h3>
				{#if images.length}
					<ul
						class="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3 {variant === 'page'
							? 'xl:grid-cols-4'
							: ''}"
					>
						{#each images.slice(0, 24) as f (f.path)}
							<li>
								<a
									href={teamFileUrl(teamId, f.path)}
									target="_blank"
									rel="noopener"
									class="tm-card tm-hover group block overflow-hidden !rounded-xl"
								>
									<img
										src={teamFileUrl(teamId, f.path)}
										alt={f.path}
										loading="lazy"
										class="aspect-[4/3] w-full object-cover transition duration-300 group-hover:scale-[1.02]"
									/>
									<div class="truncate px-2 py-1.5 text-[11px] text-gray-500" title={f.path}>
										{f.path}
									</div>
								</a>
							</li>
						{/each}
					</ul>
				{/if}
				{#if others.length}
					<ul class="tm-card files divide-y overflow-hidden !rounded-xl">
						{#each others.slice(0, 60) as f (f.path)}
							<li>
								<a
									href={teamFileUrl(teamId, f.path)}
									target="_blank"
									rel="noopener"
									class="flex items-center gap-3 px-3 py-2 text-xs transition hover:bg-gray-500/[0.06]"
								>
									<span
										class="ext grid size-7 shrink-0 place-items-center rounded-lg font-mono text-[9px] uppercase"
										aria-hidden="true">{(f.path.split('.').pop() ?? '').slice(0, 4)}</span
									>
									<span
										class="min-w-0 flex-1 truncate font-mono text-gray-700 dark:text-gray-200"
										title={f.path}>{f.path}</span
									>
									{#if included.has(f.path)}<span
											class="shrink-0 rounded-full bg-gray-500/10 px-1.5 py-0.5 text-[10px] text-gray-600 dark:text-gray-300"
											title="这个文件的全文已经放在上面的结果里"
											data-file-included>全文在上面</span
										>{/if}
									<span class="shrink-0 tabular-nums text-gray-400">{formatBytes(f.size)}</span>
								</a>
							</li>
						{/each}
					</ul>
					{#if others.length > 60}<div class="mt-1 text-[11px] text-gray-400">
							还有 {others.length - 60} 个文件没有列出
						</div>{/if}
				{/if}
			</section>
		{/if}

		{#if data?.tasks.length}
			<section
				class="mt-8 {variant === 'page' ? 'lg:ml-[15rem]' : ''}"
				aria-label="各任务的原始结果"
				data-conclusion-tasks
			>
				<details class="process">
					<summary
						class="tm-eyebrow flex cursor-pointer select-none list-none items-center gap-1.5 [&::-webkit-details-marker]:hidden"
						data-conclusion-process
						><svg
							class="process-caret size-3 shrink-0 transition-transform"
							viewBox="0 0 16 16"
							fill="none"
							aria-hidden="true"
							><path
								d="m6 3.5 4.5 4.5L6 12.5"
								stroke="currentColor"
								stroke-width="1.6"
								stroke-linecap="round"
								stroke-linejoin="round"
							/></svg
						>过程记录<span class="tm-num ml-1 font-normal normal-case"
							>{data.tasks.length} 个任务的原始结果</span
						></summary
					>
					<p class="mb-3 mt-1.5 text-xs text-gray-500">
						上面就是这次任务的完整结果；这里是成员交付时的原始记录，想看某一步怎么做的再展开。
					</p>
				<ul class="flex flex-col gap-2">
					{#each data.tasks as t (t.id)}
						<li>
							<details
								class="tm-card group !rounded-xl"
								on:toggle={(e) => toggleResult(t.id, e.currentTarget.open)}
							>
								<summary
									class="flex cursor-pointer select-none list-none items-center gap-2 px-3 py-2.5 text-sm [&::-webkit-details-marker]:hidden"
								>
									<svg
										class="size-3 shrink-0 text-gray-400 transition-transform group-open:rotate-90"
										viewBox="0 0 16 16"
										fill="none"
										aria-hidden="true"
										><path
											d="m6 3.5 4.5 4.5L6 12.5"
											stroke="currentColor"
											stroke-width="1.6"
											stroke-linecap="round"
											stroke-linejoin="round"
										/></svg
									>
									<span class="shrink-0 font-mono text-xs font-semibold text-gray-500"
										>#{t.key}</span
									>
									<span class="min-w-0 flex-1 truncate font-medium text-gray-900 dark:text-gray-100"
										>{t.title}</span
									>
									<span class="hidden shrink-0 text-xs text-gray-500 sm:inline">{t.member}</span>
									<RunnerBadge actual={t.executor} />
									<StatusChip
										status={t.status === 'done'
											? 'done'
											: t.status === 'blocked'
												? 'failed'
												: t.status}
										label={t.status === 'done'
											? '已完成'
											: statusLabel(t.status === 'blocked' ? 'failed' : t.status)}
									/>
								</summary>
								{#if openResults.has(t.id)}
									<div class="tm-hairline border-t px-4 py-3">
										{#if t.result}
											<div class="max-h-[70vh] overflow-y-auto">
												<ReportMarkdown
													id={`team-result-${t.key}`}
													content={prepareReport(t.result, reportOpts)}
													size="panel"
												/>
											</div>
										{:else}
											<div class="text-xs text-gray-400">{t.error || '这个任务没有结果'}</div>
										{/if}
									</div>
								{/if}
							</details>
						</li>
					{/each}
				</ul>
				</details>
			</section>
		{/if}
	{/if}
</section>

<ConfirmDialog
	bind:show={confirmRewrite}
	title="重写结论？"
	message="负责人会根据现在的任务记录和工作目录重新写一份结论，替换当前这一版（会调用一次模型）。"
	confirmLabel="重写"
	on:confirm={write}
/>

<style>
	.process[open] .process-caret {
		transform: rotate(90deg);
	}
	.files > li + li {
		border-color: hsl(var(--tm-line));
	}
	.ext {
		color: hsl(var(--tm-accent));
		background: hsl(var(--tm-accent) / 0.08);
	}
	.conclusion-progress {
		animation: conclusion-slide 1.4s ease-in-out infinite;
	}
	@keyframes conclusion-slide {
		0% {
			transform: translateX(-100%);
		}
		100% {
			transform: translateX(300%);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.conclusion-progress {
			animation: none;
			width: 100%;
			opacity: 0.4;
		}
	}
</style>
