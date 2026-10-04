<script lang="ts">
	import { afterUpdate, onDestroy, onMount, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { fade, fly } from 'svelte/transition';
	import { toast } from 'svelte-sonner';

	import '$lib/components/teams/teams.css';
	import './discuss.css';
	import { chatId as currentChatId, config, mobile, models, showSidebar, socket, WEBUI_NAME } from '$lib/stores';
	import {
		askDiscussion,
		concludeDiscussion,
		continueDiscussion,
		deleteDiscussion,
		getDiscussion,
		interjectDiscussion,
		retryDiscussionTurn,
		stopDiscussion,
		type DiscussAsk,
		type Discussion
	} from '$lib/apis/discussions';
	import { copyToClipboard } from '$lib/utils';
	import { isHermesAgentModel } from '$lib/utils/hermes';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import { now, timeAgo } from '$lib/components/teams/clock';
	import ConclusionCard from './ConclusionCard.svelte';
	import ResearchPanel from './ResearchPanel.svelte';
	import SeatAvatar from './SeatAvatar.svelte';
	import TurnCard from './TurnCard.svelte';
	import {
		applyEvent,
		discussionMarkdown,
		isLive,
		modelRef,
		modeSpec,
		roundsOf,
		seatHue,
		seatIndex,
		STATUS_LABEL,
		type DiscussEvent
	} from './model';

	/** One discussion: every question asked in it, its rounds and the moderator's conclusions. */
	export let chatId: string;

	let discussion: Discussion | null = null;
	let asks: DiscussAsk[] = [];
	let loadError = '';
	let input = '';
	let busy = false;
	let scroller: HTMLDivElement;
	let follow = true;
	let width = 1280;
	let showDelete = false;
	let showMenu = false;
	let showHermes = false;
	let hermesPrompt = '';
	let reloadTimer: ReturnType<typeof setTimeout> | null = null;
	let pollTimer: ReturnType<typeof setInterval> | null = null;
	let boundSocket: any = null;
	let inputEl: HTMLTextAreaElement;

	$: title = discussion?.title ?? '讨论';
	$: last = asks[asks.length - 1] ?? null;
	$: liveNow = !!last && isLive(last.status);
	$: concluding = last?.status === 'concluding';
	$: hasSpoken = !!last?.turns?.some((t) => t.status === 'done');
	$: settled = !!last && !liveNow;
	$: canConclude = settled && hasSpoken && last?.conclusion?.status !== 'done';
	$: canContinue = settled && hasSpoken && last?.mode !== 'review';
	$: hermes = (($models ?? []) as any[]).find((m) => isHermesAgentModel(m, $config?.hermes_agent_model_ids));
	$: canHandOff = !!hermes && last?.conclusion?.status === 'done';

	const cols = (n: number, w: number) => (w >= 1280 ? (n === 4 ? 2 : Math.min(n, 3)) : Math.min(n, 2));

	// ---- data ---------------------------------------------------------------------------------

	const load = async () => {
		try {
			const res = await getDiscussion(localStorage.token, chatId);
			discussion = res;
			asks = res.asks;
			loadError = '';
		} catch (e: any) {
			loadError = e?.status === 404 ? '这个讨论不存在或已删除' : e?.message || '加载失败';
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
		if (event?.chat_id !== chatId || event?.data?.type !== 'discuss') return;
		const data = event.data.data as DiscussEvent;
		if (data.kind === 'meta') {
			if (discussion) discussion = { ...discussion, title: data.title ?? discussion.title, folder_id: data.folderId ?? discussion.folder_id };
			return;
		}
		const result = applyEvent(asks, data);
		asks = result.asks;
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

	const run = async (fn: () => Promise<any>, ok?: string) => {
		if (busy) return;
		busy = true;
		try {
			const res = await fn();
			if (res?.asks) {
				discussion = res;
				asks = res.asks;
			}
			if (ok) toast.success(ok);
			return res;
		} catch (e: any) {
			toast.error(e?.message || '操作失败');
		} finally {
			busy = false;
		}
	};

	const submit = async () => {
		const text = input.trim();
		if (!text || busy) return;
		if (liveNow) {
			if (concluding) return;
			const res = await run(() => interjectDiscussion(localStorage.token, chatId, text), '已插话：下一轮的发言和主持人都会看到');
			if (res) input = '';
			return;
		}
		const res = await run(() => askDiscussion(localStorage.token, chatId, text));
		if (res) {
			input = '';
			follow = true;
			await tick();
			scrollToBottom();
		}
	};

	const stop = () => run(() => stopDiscussion(localStorage.token, chatId), '已停止');
	let retrying = '';
	const retry = async (turnId: string) => {
		retrying = turnId;
		await run(() => retryDiscussionTurn(localStorage.token, chatId, turnId));
		retrying = '';
	};
	const conclude = () => run(() => concludeDiscussion(localStorage.token, chatId));
	const more = async () => {
		const res = await run(() => continueDiscussion(localStorage.token, chatId));
		if (res) {
			follow = true;
			await tick();
			scrollToBottom();
		}
	};

	const copyAll = async () => {
		showMenu = false;
		if (await copyToClipboard(discussionMarkdown(title, asks))) toast.success('已复制整个讨论（Markdown）');
	};

	const remove = async () => {
		try {
			await deleteDiscussion(localStorage.token, chatId);
			toast.success('已删除');
			goto('/discuss');
		} catch (e: any) {
			toast.error(e?.message || '删除失败');
		}
	};

	const openHermes = () => {
		if (!last) return;
		hermesPrompt = [
			'下面是一次多模型讨论的结论。请用你的工具（联网搜索、读文件等）核查其中需要事实支撑的说法：哪些成立、哪些不成立或要修正，并给出依据。',
			'如果结论里有可以直接做的下一步，先说你打算怎么做，等我确认再动手。',
			'',
			`问题：${last.question}`,
			'',
			'讨论结论：',
			last.conclusion.content
		].join('\n');
		showHermes = true;
	};
	const sendToHermes = () => {
		if (!hermes || !hermesPrompt.trim()) return;
		showHermes = false;
		goto(`/?models=${encodeURIComponent(modelRef(hermes))}&q=${encodeURIComponent(hermesPrompt.trim())}`);
	};

	const newWithSeats = () => {
		const refs = (discussion?.setup?.seats ?? []).map((s) => s.model).join(',');
		goto(`/discuss?models=${encodeURIComponent(refs)}`);
	};

	// ---- scrolling ----------------------------------------------------------------------------

	const scrollToBottom = () => {
		if (scroller) scroller.scrollTop = scroller.scrollHeight;
	};
	const onScroll = () => {
		if (!scroller) return;
		follow = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 160;
	};
	afterUpdate(() => {
		if (liveNow && follow) scrollToBottom();
	});

	const resizeInput = () => {
		if (!inputEl) return;
		inputEl.style.height = 'auto';
		inputEl.style.height = `${Math.min(inputEl.scrollHeight, 160)}px`;
	};

	onMount(async () => {
		currentChatId.set(chatId);
		await load();
		await tick();
		if (liveNow) scrollToBottom();
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

<svelte:head><title>{title} · 讨论台 | {$WEBUI_NAME}</title></svelte:head>
<svelte:window bind:innerWidth={width} />

<div class="tm-ambient relative flex h-screen max-h-[100dvh] w-full flex-col" data-teams-ui data-discuss-ui data-discuss-room={chatId}>
	<nav class="flex min-w-0 items-center gap-1.5 px-3 pt-2 pb-1">
		<div class="{$mobile ? '' : 'hidden'} flex flex-none items-center">
			<button class="rounded-xl p-1.5 hover:bg-gray-100 dark:hover:bg-gray-850" on:click={() => showSidebar.set(!$showSidebar)} aria-label="切换侧栏"
				><MenuLines /></button
			>
		</div>
		<a href="/discuss" class="halo-crumb shrink-0 px-1 hover:text-gray-900 dark:hover:text-white">讨论台</a>
		<span class="shrink-0 text-gray-300 dark:text-gray-700" aria-hidden="true">/</span>
		<span class="min-w-0 truncate text-sm font-medium text-gray-800 dark:text-gray-100" data-discuss-title>{title}</span>
		{#if last}
			<span
				class="ml-1 shrink-0 rounded-full px-2 py-0.5 text-[11px] {liveNow
					? 'bg-blue-500/10 text-blue-600 dark:text-blue-300'
					: last.status === 'error'
						? 'bg-red-500/10 text-red-600 dark:text-red-300'
						: 'bg-gray-500/10 text-gray-500 dark:text-gray-400'}"
				data-discuss-status={last.status}>{STATUS_LABEL[last.status] ?? last.status}</span
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
				<div
					class="tm-card absolute right-0 z-40 mt-1 flex w-44 flex-col p-1 text-sm"
					transition:fly={{ y: -4, duration: 140 }}
					role="menu"
				>
					<button type="button" role="menuitem" class="rounded-lg px-3 py-2 text-left hover:bg-gray-500/10" on:click={copyAll}>复制整个讨论</button>
					<button type="button" role="menuitem" class="rounded-lg px-3 py-2 text-left hover:bg-gray-500/10" on:click={newWithSeats}>用这些席位开新讨论</button>
					<button
						type="button"
						role="menuitem"
						class="rounded-lg px-3 py-2 text-left text-red-600 hover:bg-red-500/10 dark:text-red-400"
						on:click={() => {
							showMenu = false;
							showDelete = true;
						}}>删除讨论</button
					>
				</div>
			{/if}
		</div>
	</nav>

	<div bind:this={scroller} class="tm-scroll flex-1 overflow-y-auto px-4 pb-48" on:scroll={onScroll}>
		<div class="mx-auto flex max-w-5xl flex-col gap-12 pt-4 sm:pt-8">
			{#if loadError}
				<div class="flex flex-col items-center gap-3 py-24 text-center">
					<p class="text-sm text-gray-500 dark:text-gray-400">{loadError}</p>
					<a href="/discuss" class="tm-btn-ghost">回到讨论台</a>
				</div>
			{:else if !discussion}
				<div class="flex flex-col gap-4" aria-busy="true">
					<div class="h-7 w-2/3 animate-pulse rounded-lg bg-gray-500/10" />
					<div class="grid gap-3 md:grid-cols-2">
						<div class="tm-card h-40 animate-pulse opacity-60" />
						<div class="tm-card h-40 animate-pulse opacity-60" />
					</div>
				</div>
			{:else}
				{#each asks as ask, ai (ask.id)}
					{@const spec = modeSpec(ask.mode)}
					{@const rounds = roundsOf(ask)}
					{@const maxRound = rounds.length ? rounds[rounds.length - 1].round : 0}
					<section class="flex flex-col gap-5" data-discuss-ask={ask.id} in:fade={{ duration: 200 }}>
						<header class="flex flex-col gap-3">
							<div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-gray-400 dark:text-gray-500">
								<span class="tm-eyebrow">{ai === 0 ? '问题' : `追问 ${ai}`}</span>
								<span aria-hidden="true">·</span>
								<span>{spec.label}</span>
								<span aria-hidden="true">·</span>
								<span>主持人 {ask.moderator.name}</span>
								<span aria-hidden="true">·</span>
								<span>{timeAgo(Math.floor(ask.startedAt / 1000), $now)}</span>
							</div>
							<p class="dc-question text-[19px] font-semibold leading-snug whitespace-pre-wrap text-gray-950 sm:text-[22px] dark:text-white" data-discuss-question>
								{ask.question}
							</p>
							<div class="flex flex-wrap gap-1.5">
								{#each ask.seats as seat, si (seat.id)}
									{@const speaking = ask.turns.find((t) => t.seat === seat.id && t.status === 'streaming')}
									{@const latest = [...ask.turns].reverse().find((t) => t.seat === seat.id)}
									<span class="dc-chip !py-1 !pl-1" data-discuss-seat-chip={seat.id}>
										<SeatAvatar
											model={seat.model}
											name={seat.label}
											hue={seatHue(si)}
											state={speaking ? (speaking.thinking && !speaking.content ? 'thinking' : 'streaming') : latest?.status === 'error' ? 'error' : latest ? 'done' : 'waiting'}
											size={18}
										/>
										<span class="font-medium text-gray-800 dark:text-gray-100">{seat.label}</span>
										{#if seat.role && !seat.label.includes(seat.role)}
											<span style="color: hsl({seatHue(si)} 70% 52%)">{seat.role}</span>
										{/if}
									</span>
								{/each}
							</div>
						</header>

						{#if ask.research}
							<ResearchPanel research={ask.research} />
						{/if}

						{#each rounds as { round, turns } (round)}
							{@const doneCount = turns.filter((t) => t.status === 'done').length}
							<div class="flex flex-col gap-3" data-discuss-round={round}>
								<div class="dc-round-head">
									<span class="tm-eyebrow">第 {round} 轮</span>
									<span class="text-xs text-gray-600 dark:text-gray-300">{spec.roundName(round, ask.rounds)}</span>
									<span class="tm-num text-[11px] text-gray-400">{doneCount}/{turns.length}</span>
								</div>
								<div class="dc-round-grid" style="--dc-cols: {cols(turns.length, width)}">
									{#each turns as turn (turn.id)}
										{@const si = seatIndex(ask.seats, turn.seat)}
										<TurnCard
											{turn}
											seat={ask.seats[si]}
											hue={seatHue(si)}
											sources={ask.research?.status === 'done' ? ask.research.sources : []}
											canRetry={ai === asks.length - 1 && settled}
											retrying={retrying === turn.id}
											on:retry={(e) => retry(e.detail)}
										/>
									{/each}
								</div>
								{#each ask.interjections.filter((x) => x.afterRound === round) as note}
									<div class="flex justify-end">
										<p class="max-w-[85%] rounded-2xl rounded-br-md bg-gray-900 px-3.5 py-2 text-[13px] text-white dark:bg-gray-100 dark:text-gray-900">
											<span class="mr-1 opacity-60">你插话</span>{note.text}
										</p>
									</div>
								{/each}
							</div>
						{/each}

						{#if ask.status === 'running'}
							{#each Array.from({ length: Math.max(0, ask.rounds - maxRound) }, (_, k) => maxRound + k + 1) as round}
								<div class="dc-round-head opacity-50">
									<span class="tm-eyebrow">第 {round} 轮</span>
									<span class="text-xs text-gray-500">{spec.roundName(round, ask.rounds)} · 等上一轮说完</span>
								</div>
							{/each}
						{/if}

						<ConclusionCard {ask} />

						{#if ask.error && ask.status === 'error'}
							<p class="rounded-xl bg-red-500/5 px-3 py-2 text-xs text-red-700 dark:text-red-300">{ask.error}</p>
						{:else if ask.status === 'interrupted'}
							<p class="rounded-xl bg-amber-500/5 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
								服务重启打断了这次讨论。可以让主持人根据已有发言直接总结，或再讨论一轮。
							</p>
						{/if}
					</section>
				{/each}
			{/if}
		</div>
	</div>

	{#if discussion}
		<div class="dc-dock-wrap pointer-events-none absolute inset-x-0 bottom-0 px-3 pb-3 sm:px-6 sm:pb-5" data-discuss-dock>
			<div class="pointer-events-auto mx-auto flex max-w-3xl flex-col gap-2">
				{#if settled && (canConclude || canContinue || canHandOff)}
					<div class="flex flex-wrap justify-center gap-1.5" transition:fade={{ duration: 150 }}>
						{#if canConclude}
							<button type="button" class="dc-chip" disabled={busy} on:click={conclude} data-discuss-conclude>
								让主持人直接总结
							</button>
						{/if}
						{#if canContinue}
							<button type="button" class="dc-chip" disabled={busy} on:click={more} data-discuss-continue>
								再讨论一轮
							</button>
						{/if}
						{#if canHandOff}
							<button type="button" class="dc-chip" disabled={busy} on:click={openHermes} data-discuss-hermes>
								交给 Hermes 核查
							</button>
						{/if}
					</div>
				{/if}
				<form class="dc-dock flex items-end gap-2 p-2 pl-4" on:submit|preventDefault={submit}>
					<textarea
						bind:this={inputEl}
						bind:value={input}
						rows="1"
						maxlength={liveNow ? 1000 : 8000}
						disabled={concluding}
						class="tm-scroll max-h-40 min-w-0 flex-1 resize-none bg-transparent py-1.5 text-[14px] leading-relaxed text-gray-900 outline-none placeholder:text-gray-400 disabled:opacity-60 dark:text-gray-100 dark:placeholder:text-gray-500"
						placeholder={concluding
							? '主持人正在写结论…'
							: liveNow
								? '插话：补充信息或要求，下一轮的发言会看到'
								: '追问：接着这个讨论继续问'}
						on:input={resizeInput}
						on:keydown={(e) => {
							if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !$mobile) {
								e.preventDefault();
								submit();
							}
						}}
						data-discuss-input
					/>
					{#if liveNow}
						<button
							type="button"
							class="tm-btn-ghost shrink-0 !px-3"
							disabled={busy}
							on:click={stop}
							aria-label="停止讨论"
							data-discuss-stop
							><span class="size-2.5 rounded-[2px] bg-current" aria-hidden="true" />停止</button
						>
					{/if}
					<button type="submit" class="tm-btn-primary shrink-0 !px-3.5" disabled={busy || !input.trim() || concluding} data-discuss-send>
						{liveNow ? '插话' : '追问'}
					</button>
				</form>
			</div>
		</div>
	{/if}
</div>

{#if showHermes}
	<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
	<div class="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4 backdrop-blur-sm" transition:fade={{ duration: 150 }} on:click|self={() => (showHermes = false)}>
		<div class="tm-card flex w-full max-w-xl flex-col gap-3 p-5" data-teams-ui role="dialog" aria-modal="true" aria-label="交给 Hermes 核查">
			<div>
				<h3 class="tm-display text-base font-semibold text-gray-900 dark:text-white">交给 Hermes 核查</h3>
				<p class="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
					会新开一个和 Hermes 的对话并发送下面这段话。Hermes 能联网、读文件、跑工具，核查一次可能要几分钟。可以先改改再发。
				</p>
			</div>
			<textarea
				bind:value={hermesPrompt}
				rows="10"
				class="tm-scroll w-full resize-y rounded-xl border border-gray-200/70 bg-transparent p-3 text-[13px] leading-relaxed text-gray-800 outline-none focus:border-blue-400/60 dark:border-gray-700/60 dark:text-gray-100"
			/>
			<div class="flex justify-end gap-2">
				<button type="button" class="tm-btn-ghost" on:click={() => (showHermes = false)}>取消</button>
				<button type="button" class="tm-btn-primary" disabled={!hermesPrompt.trim()} on:click={sendToHermes} data-discuss-send-hermes>发送给 Hermes</button>
			</div>
		</div>
	</div>
{/if}

<ConfirmDialog
	bind:show={showDelete}
	title="删除这个讨论？"
	message={`「${title}」和其中所有发言、结论都会删除（它也是一个对话，会一起从侧栏消失）。`}
	confirmLabel="删除"
	on:confirm={remove}
/>
