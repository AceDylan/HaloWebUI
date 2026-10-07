<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { fade, fly, slide } from 'svelte/transition';
	import { toast } from 'svelte-sonner';

	import '$lib/components/teams/teams.css';
	import '$lib/components/discuss/discuss.css';
	import './answer.css';
	import { chatId as currentChatId, config, mobile, models, showSidebar, socket, user, WEBUI_NAME } from '$lib/stores';
	import {
		deleteAnswer,
		getAnswer,
		retryAnswer,
		revertAnswerUpgrade,
		stopAnswer,
		type AnswerDetail,
		type AnswerRun
	} from '$lib/apis/answers';
	import { refreshModels } from '$lib/services/models';
	import { copyToClipboard } from '$lib/utils';
	import { handOff, HANDOFF_PATH } from '$lib/utils/handoff';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import ReportMarkdown from '$lib/components/teams/ReportMarkdown.svelte';
	import { now, timeAgo } from '$lib/components/teams/clock';
	import ResearchPanel from '$lib/components/discuss/ResearchPanel.svelte';
	import { linkCitations, modelById, retryText, seconds, tokens } from '$lib/components/discuss/model';
	import AssistantAvatar from './AssistantAvatar.svelte';
	import { ACTION_LABEL, actionSentence, answerContext, applyEvent, isLive, stagesOf, STATUS_LABEL, type AnswerEvent } from './model';

	/** One 精答: the dispatcher picking (or writing) an assistant, then its answer, streaming. */
	export let chatId: string;

	let detail: AnswerDetail | null = null;
	let run: AnswerRun | null = null;
	let loadError = '';
	let busy = false;
	let showMenu = false;
	let showDelete = false;
	let showPrompt = false;
	let reloadTimer: ReturnType<typeof setTimeout> | null = null;
	let pollTimer: ReturnType<typeof setInterval> | null = null;
	let boundSocket: any = null;
	let modelsRefreshedFor = '';

	$: title = detail?.title ?? '精答';
	$: liveNow = !!run && isLive(run.status);
	$: stages = run ? stagesOf(run) : [];
	$: assistant = run?.assistant ?? null;
	$: answer = run?.answer ?? null;
	$: sources = run?.research?.status === 'done' ? run.research.sources : [];
	$: answerState = (
		answer?.status === 'streaming' ? (answer.thinking && !answer.content ? 'thinking' : 'streaming') : answer?.status ?? 'waiting'
	) as 'thinking' | 'streaming' | 'waiting' | 'done' | 'error' | 'stopped';
	$: took = seconds(answer?.startedAt, answer?.endedAt);
	$: retrying = answer?.retry ? retryText(answer.retry, $now) : '';
	$: canRetry = !!run && !liveNow && run.status !== 'done';
	$: canRevert = !!assistant && assistant.action === 'update' && !assistant.reverted && !liveNow;
	$: teamsEnabled = !!$config?.features?.enable_agent_teams;
	$: studioAllowed =
		!!$config?.features?.enable_image_generation &&
		($user?.role === 'admin' || !!($user as any)?.permissions?.features?.image_generation);
	$: knownAssistant = assistant?.saved ? modelById($models as any[], assistant.id) : undefined;

	// A new or upgraded assistant is not in the app's model list yet: fetch it once, so the chat
	// (and the model menu) know it when the user follows up.
	$: if (assistant?.saved && (assistant.action === 'create' || assistant.action === 'update') && modelsRefreshedFor !== `${assistant.id}:${assistant.action}`) {
		modelsRefreshedFor = `${assistant.id}:${assistant.action}`;
		if (assistant.action === 'update' || !knownAssistant) {
			refreshModels(localStorage.token, { force: true, reason: 'answer-desk' }).catch(() => {});
		}
	}

	// ---- data ---------------------------------------------------------------------------------

	const load = async () => {
		try {
			const res = await getAnswer(localStorage.token, chatId);
			detail = res;
			run = res.run;
			loadError = '';
		} catch (e: any) {
			loadError = e?.status === 404 ? '这条精答不存在或已删除' : e?.message || '加载失败';
		}
	};

	const scheduleReload = (delay = 400) => {
		if (reloadTimer) clearTimeout(reloadTimer);
		reloadTimer = setTimeout(() => {
			reloadTimer = null;
			load();
		}, delay);
	};

	const onChatEvent = (event: any) => {
		if (event?.chat_id !== chatId || event?.data?.type !== 'answer') return;
		const data = event.data.data as AnswerEvent;
		if (data.kind === 'meta') {
			if (detail) detail = { ...detail, title: data.title ?? detail.title, folder_id: data.folderId ?? detail.folder_id };
			return;
		}
		const result = applyEvent(run, data);
		run = result.run;
		if (result.stale) scheduleReload();
		if (data.kind === 'end') scheduleReload(800);
	};

	const bindSocket = (s: any) => {
		if (boundSocket === s) return;
		boundSocket?.off?.('chat-events', onChatEvent);
		boundSocket = s;
		boundSocket?.on?.('chat-events', onChatEvent);
	};
	$: bindSocket($socket);

	const onVisible = () => {
		if (!document.hidden) load();
	};

	// ---- actions ------------------------------------------------------------------------------

	const act = async (fn: () => Promise<AnswerDetail>, ok?: string) => {
		if (busy) return;
		busy = true;
		try {
			const res = await fn();
			detail = res;
			run = res.run;
			if (ok) toast.success(ok);
		} catch (e: any) {
			toast.error(e?.message || '操作失败');
		} finally {
			busy = false;
		}
	};
	const stop = () => act(() => stopAnswer(localStorage.token, chatId), '已停止');
	const retry = () => act(() => retryAnswer(localStorage.token, chatId));
	const revert = () => act(() => revertAnswerUpgrade(localStorage.token, chatId), `已撤销对「${assistant?.name}」的升级`);

	const copyAnswer = async () => {
		showMenu = false;
		if (run?.answer.content && (await copyToClipboard(run.answer.content))) toast.success('已复制回答');
	};
	const remove = async () => {
		try {
			await deleteAnswer(localStorage.token, chatId);
			toast.success('已删除');
			goto('/answer');
		} catch (e: any) {
			toast.error(e?.message || '删除失败');
		}
	};

	// 「接下来」: follow up in the chat (it is one), or hand the answer to the other modes
	const toMode = (to: 'discuss' | 'teams' | 'studio') => {
		if (!run) return;
		const gist = (run.answer.content ?? '').replace(/\s+/g, ' ').trim().slice(0, 600);
		handOff(typeof sessionStorage === 'undefined' ? null : sessionStorage, {
			to,
			text:
				to === 'discuss'
					? run.question
					: to === 'teams'
						? `按这个回答去做：${run.question}`
						: `一张清晰的说明图，讲清「${title || run.question}」：${gist}`,
			context: to === 'studio' ? '' : answerContext(run),
			from: { kind: 'answer', id: chatId, title }
		});
		goto(HANDOFF_PATH[to]);
	};

	onMount(async () => {
		currentChatId.set(chatId);
		await load();
		document.addEventListener('visibilitychange', onVisible);
		// the socket carries every token; this only catches up when it is down or a tab slept
		pollTimer = setInterval(() => {
			if (!document.hidden && liveNow && !$socket?.connected) load();
		}, 3000);
	});
	onDestroy(() => {
		boundSocket?.off?.('chat-events', onChatEvent);
		if (reloadTimer) clearTimeout(reloadTimer);
		if (pollTimer) clearInterval(pollTimer);
		if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisible);
		if ($currentChatId === chatId) currentChatId.set('');
	});
</script>

<svelte:head><title>{title} · 精答 | {$WEBUI_NAME}</title></svelte:head>

<div class="tm-ambient relative flex h-screen max-h-[100dvh] w-full flex-col" data-teams-ui data-discuss-ui data-answer-ui data-answer-run={chatId}>
	<nav class="flex min-w-0 items-center gap-1.5 px-3 pt-2 pb-1">
		<div class="{$mobile ? '' : 'hidden'} flex flex-none items-center">
			<button class="rounded-xl p-1.5 hover:bg-gray-100 dark:hover:bg-gray-850" on:click={() => showSidebar.set(!$showSidebar)} aria-label="切换侧栏"
				><MenuLines /></button
			>
		</div>
		<a href="/answer" class="halo-crumb shrink-0 px-1 hover:text-gray-900 dark:hover:text-white">精答</a>
		<span class="shrink-0 text-gray-300 dark:text-gray-700" aria-hidden="true">/</span>
		<span class="min-w-0 truncate text-sm font-medium text-gray-800 dark:text-gray-100" data-answer-title>{title}</span>
		{#if run}
			<span
				class="ml-1 shrink-0 rounded-full px-2 py-0.5 text-[11px] {liveNow
					? 'bg-blue-500/10 text-blue-600 dark:text-blue-300'
					: run.status === 'error'
						? 'bg-red-500/10 text-red-600 dark:text-red-300'
						: 'bg-gray-500/10 text-gray-500 dark:text-gray-400'}"
				data-answer-status={run.status}>{STATUS_LABEL[run.status] ?? run.status}</span
			>
		{/if}
		<div class="relative ml-auto shrink-0">
			<button
				type="button"
				class="rounded-xl p-1.5 text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-850"
				aria-label="更多"
				aria-expanded={showMenu}
				on:click={() => (showMenu = !showMenu)}
				><svg class="size-4" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"
					><circle cx="3.5" cy="8" r="1.3" /><circle cx="8" cy="8" r="1.3" /><circle cx="12.5" cy="8" r="1.3" /></svg
				></button
			>
			{#if showMenu}
				<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
				<div class="fixed inset-0 z-30" on:click={() => (showMenu = false)} />
				<div class="tm-card absolute right-0 z-40 mt-1 flex w-44 flex-col p-1 text-sm" transition:fly={{ y: -4, duration: 140 }} role="menu">
					<button type="button" role="menuitem" class="rounded-lg px-3 py-2 text-left hover:bg-gray-500/10 disabled:opacity-40" disabled={!run?.answer.content} on:click={copyAnswer}
						>复制回答</button
					>
					<a role="menuitem" class="rounded-lg px-3 py-2 text-left hover:bg-gray-500/10" href="/c/{chatId}">在对话里打开</a>
					<button
						type="button"
						role="menuitem"
						class="rounded-lg px-3 py-2 text-left text-red-600 hover:bg-red-500/10 dark:text-red-400"
						on:click={() => {
							showMenu = false;
							showDelete = true;
						}}>删除</button
					>
				</div>
			{/if}
		</div>
	</nav>

	<div class="tm-scroll flex-1 overflow-y-auto px-4 pb-40">
		<div class="mx-auto flex max-w-3xl flex-col gap-6 pt-4 sm:pt-8">
			{#if loadError}
				<div class="flex flex-col items-center gap-3 py-24 text-center">
					<p class="text-sm text-gray-500 dark:text-gray-400">{loadError}</p>
					<a href="/answer" class="tm-btn-ghost">回到精答</a>
				</div>
			{:else if !run}
				<div class="flex flex-col gap-4" aria-busy="true">
					<div class="h-7 w-2/3 animate-pulse rounded-lg bg-gray-500/10" />
					<div class="tm-card h-24 animate-pulse opacity-60" />
					<div class="tm-card h-40 animate-pulse opacity-60" />
				</div>
			{:else}
				<header class="tm-rise flex flex-col gap-3">
					<div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-gray-400 dark:text-gray-500">
						<span class="tm-eyebrow">问题</span>
						<span aria-hidden="true">·</span>
						<span>调度 {run.planner.name}</span>
						<span aria-hidden="true">·</span>
						<span>{timeAgo(Math.floor(run.startedAt / 1000), $now)}</span>
					</div>
					<p class="dc-question text-[19px] font-semibold leading-snug whitespace-pre-wrap text-gray-950 sm:text-[22px] dark:text-white" data-answer-question>
						{run.question}
					</p>
					{#if run.context?.text}
						<details class="dc-context text-xs text-gray-500 dark:text-gray-400" data-answer-context>
							<summary class="inline-flex cursor-pointer items-center gap-1 rounded-full hover:text-gray-800 dark:hover:text-gray-200">
								背景：{run.context.title ? `对话「${run.context.title}」` : '之前的对话'}
							</summary>
							<div class="mt-1.5 max-h-48 overflow-y-auto whitespace-pre-wrap rounded-xl bg-gray-500/5 px-3 py-2 leading-relaxed">{run.context.text}</div>
							{#if run.context.chatId}
								<a href="/c/{run.context.chatId}" class="mt-1 inline-block hover:underline">回到那个对话 →</a>
							{/if}
						</details>
					{/if}
				</header>

				<ol class="ad-pipe tm-rise" style="--i:1; --ad-steps: {stages.length}" aria-label="进度" data-answer-stages>
					{#each stages as s (s.key)}
						<li class="ad-step" data-state={s.state} data-answer-stage={s.key}>
							<span class="ad-dot" aria-hidden="true">
								{#if s.state === 'done'}
									<svg class="size-3" viewBox="0 0 16 16" fill="none"><path d="m3.5 8.5 3 3 6-7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>
								{:else if s.state === 'error'}
									<span class="text-[11px] font-bold">!</span>
								{:else if s.state === 'active'}
									<span class="size-1.5 rounded-full bg-current" />
								{/if}
							</span>
							<span class="ad-step-label truncate text-[12.5px] font-medium text-gray-800 dark:text-gray-100">{s.label}</span>
							{#if s.note}
								<span class="-mt-1 truncate text-[11px] text-gray-400 dark:text-gray-500" title={s.note}>{s.note}</span>
							{/if}
						</li>
					{/each}
				</ol>

				{#if assistant}
					<section class="ad-assistant flex flex-col gap-3 p-4 pl-5" data-action={assistant.action} data-answer-assistant={assistant.action}>
						<div class="flex items-start gap-3">
							<AssistantAvatar id={assistant.id} name={assistant.name} emoji={assistant.emoji ?? ''} size={36} state={answerState === 'done' ? 'done' : liveNow ? 'streaming' : 'idle'} />
							<div class="min-w-0 flex-1">
								<div class="flex flex-wrap items-center gap-2">
									<span class="text-[15px] font-semibold text-gray-900 dark:text-white" data-answer-assistant-name>{assistant.name}</span>
									<span class="ad-badge">{ACTION_LABEL[assistant.action] ?? assistant.action}</span>
									{#if assistant.reverted}<span class="ad-badge !text-gray-500" style="--ad-tone: var(--tm-muted)">已撤销升级</span>{/if}
									{#if assistant.baseName && assistant.action !== 'direct'}
										<span class="text-[11px] text-gray-400 dark:text-gray-500">底座 {assistant.baseName}</span>
									{/if}
								</div>
								{#if assistant.description}
									<p class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{assistant.description}</p>
								{/if}
							</div>
						</div>
						<div class="flex flex-col gap-1 text-[13px] leading-relaxed text-gray-700 dark:text-gray-300">
							<p data-answer-reason>
								<span class="text-gray-400 dark:text-gray-500">{actionSentence(assistant.action, assistant.name)}：</span>{run.plan.reason ||
									(run.plan.status === 'error' ? '调度没成功，直接回答' : '')}
							</p>
							{#if run.plan.change && (assistant.action === 'create' || assistant.action === 'update' || assistant.action === 'temporary')}
								<p class="text-xs text-gray-500 dark:text-gray-400" data-answer-change>
									<span aria-hidden="true">＋</span>
									{run.plan.change}
								</p>
							{/if}
							{#if run.plan.note}
								<p class="text-xs text-amber-600 dark:text-amber-300">{run.plan.note}</p>
							{/if}
							{#if run.plan.status === 'error' && run.plan.error}
								<p class="text-xs text-amber-600 dark:text-amber-300" title={run.plan.error}>调度出错：{run.plan.error}</p>
							{/if}
						</div>
						{#if assistant.system || canRevert || (assistant.saved && assistant.action !== 'direct')}
							<div class="flex flex-wrap items-center gap-1.5">
								{#if assistant.system}
									<button type="button" class="dc-chip" aria-expanded={showPrompt} on:click={() => (showPrompt = !showPrompt)} data-answer-show-prompt
										>{showPrompt ? '收起设定' : assistant.action === 'update' ? '看看升级后的设定' : '看看它的设定'}</button
									>
								{/if}
								{#if canRevert}
									<button type="button" class="dc-chip" disabled={busy} on:click={revert} data-answer-revert>撤销这次升级</button>
								{/if}
								{#if assistant.saved && assistant.action !== 'direct'}
									<a class="dc-chip" href="/workspace/models/edit?id={encodeURIComponent(assistant.id)}" data-answer-edit>在「助手」里编辑</a>
								{/if}
							</div>
							{#if showPrompt && assistant.system}
								<div class="ad-prompt text-gray-700 dark:text-gray-300" transition:slide={{ duration: 180 }} data-answer-prompt>{assistant.system}</div>
							{/if}
						{/if}
					</section>
				{/if}

				{#if run.research}
					<ResearchPanel research={run.research} />
				{/if}

				{#if assistant || answer?.content}
					<section class="dc-conclusion" data-state={answerState} aria-busy={answerState === 'streaming'} data-answer-answer={answerState} in:fade={{ duration: 200 }}>
						<header class="flex items-center gap-2.5 px-5 pt-4 pb-1">
							<div class="min-w-0 flex-1">
								<div class="tm-eyebrow">回答</div>
								<div class="truncate text-xs text-gray-500 dark:text-gray-400">
									{assistant?.name ?? ''}
									{#if retrying}
										· {retrying}
									{:else if answerState === 'thinking'}
										· 思考中…
									{:else if answerState === 'streaming'}
										· 正在回答…
									{:else if answerState === 'waiting' && liveNow}
										· {run.status === 'researching' ? '等资料查完' : '准备中'}
									{:else if answerState === 'done'}
										{[took !== null ? `用时 ${took}s` : '', answer?.usage?.total_tokens ? `${tokens(answer.usage.total_tokens)} tokens` : '']
											.filter(Boolean)
											.map((s) => ` · ${s}`)
											.join('')}
									{:else if answerState === 'error'}
										· 没答完：{answer?.error}
									{:else if answerState === 'stopped'}
										· 被停止
									{/if}
								</div>
							</div>
							{#if answer?.content && answerState !== 'streaming'}
								<button type="button" class="dc-chip" on:click={copyAnswer} data-answer-copy>复制</button>
							{/if}
						</header>
						<div class="px-5 pb-5" data-answer-body>
							{#if answer?.content}
								<ReportMarkdown id="ad-answer-{run.id}" content={linkCitations(answer.content, sources)} />
							{:else if liveNow}
								<div class="flex flex-col gap-2 pt-2" style="--dc-hue: 226">
									<div class="dc-skeleton w-full" />
									<div class="dc-skeleton w-11/12" />
									<div class="dc-skeleton w-2/3" />
								</div>
							{:else}
								<p class="pt-1 text-sm text-gray-400 dark:text-gray-500">没有回答</p>
							{/if}
						</div>
					</section>
				{/if}

				{#if (run.status === 'error' && run.error) || run.status === 'interrupted' || run.status === 'stopped'}
					<div
						class="flex flex-wrap items-center gap-2 rounded-xl px-3 py-2 text-xs {run.status === 'error'
							? 'bg-red-500/5 text-red-700 dark:text-red-300'
							: 'bg-amber-500/5 text-amber-700 dark:text-amber-300'}"
						data-answer-failure={run.status}
					>
						<p class="min-w-0 flex-1">
							{run.status === 'error' ? `出错：${run.error}` : run.status === 'interrupted' ? '服务重启打断了这次回答。' : '已停止。'}
						</p>
						{#if canRetry}
							<button type="button" class="dc-chip shrink-0 !text-current" disabled={busy} on:click={retry} data-answer-retry>
								{assistant && run.plan.status === 'done' ? `让「${assistant.name}」重新回答` : '重新开始'}
							</button>
						{/if}
					</div>
				{/if}
			{/if}
		</div>
	</div>

	{#if run}
		<div class="dc-dock-wrap pointer-events-none absolute inset-x-0 bottom-0 px-3 pb-3 sm:px-6 sm:pb-5" data-answer-dock>
			<div class="pointer-events-auto mx-auto flex max-w-3xl flex-wrap items-center justify-center gap-2">
				{#if liveNow}
					<button type="button" class="tm-btn-ghost" disabled={busy} on:click={stop} data-answer-stop
						><span class="size-2.5 rounded-[2px] bg-current" aria-hidden="true" />停止</button
					>
				{:else if run.status === 'done'}
					<a class="tm-btn-primary" href="/c/{chatId}" data-answer-followup transition:fade={{ duration: 150 }}>
						{detail?.followups ? `回到对话（已追问 ${detail.followups} 次）` : '到对话里继续追问'}
						<svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
							><path d="M3 8h9.5M8.5 4l4 4-4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" /></svg
						>
					</a>
					<button type="button" class="dc-chip" on:click={() => toMode('discuss')} title="让几个模型就这个问题再讨论，这次回答作背景" data-answer-to-discuss
						>多模型讨论</button
					>
					{#if teamsEnabled}
						<button type="button" class="dc-chip" on:click={() => toMode('teams')} title="交给协作台按这个回答去做" data-answer-to-teams>交给协作台</button>
					{/if}
					{#if studioAllowed}
						<button type="button" class="dc-chip" on:click={() => toMode('studio')} title="生图工作台：为这个回答画一张说明图" data-answer-to-studio>画一张图</button>
					{/if}
					<a class="dc-chip" href="/answer" data-answer-new>再问一个</a>
				{/if}
			</div>
		</div>
	{/if}
</div>

<ConfirmDialog
	bind:show={showDelete}
	title="删除这条精答？"
	message={`「${title}」和之后在对话里的追问都会删除（它也是一个对话，会一起从侧栏消失）。用到的助手不受影响。`}
	confirmLabel="删除"
	on:confirm={remove}
/>
