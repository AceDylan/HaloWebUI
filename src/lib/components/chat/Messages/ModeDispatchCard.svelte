<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import '$lib/components/teams/teams.css';
	import '$lib/components/discuss/discuss.css';
	import '$lib/components/answer/answer.css';
	import { getAnswer, reportBackAnswer, type AnswerRun } from '$lib/apis/answers';
	import { getDiscussion, reportBackDiscussion, type DiscussAsk } from '$lib/apis/discussions';
	import StatusChip from '$lib/components/teams/StatusChip.svelte';
	import AssistantAvatar from '$lib/components/answer/AssistantAvatar.svelte';
	import SeatAvatar from '$lib/components/discuss/SeatAvatar.svelte';
	import { actionSentence, STATUS_LABEL as ANSWER_STATUS } from '$lib/components/answer/model';
	import { modeSpec, seatHue, STATUS_LABEL as DISCUSS_STATUS } from '$lib/components/discuss/model';

	/**
	 * 派发方式「精答」/「讨论」 in the chat it was sent from: the run at work, live — who answers or
	 * sits at the table and where it is — with the way to its page, and once the answer / the
	 * conclusion is written, the way to it in this chat (it comes back as its own reply).
	 */
	export let kind: 'answer' | 'discuss';
	/** The run's own chat (/answer/<id>, /discuss/<id>). */
	export let chatId: string;
	/** The chat around the card: whether the result is already in it, and where. */
	export let history: { messages?: Record<string, any> } | null = null;

	const POLL_MS = { answer: 2500, discuss: 4000 };
	const POLL_HIDDEN_MS = 30000;
	// right after the run ends the result is on its way into this chat (title first, then the post)
	const ARRIVING_MS = 45000;

	let run: AnswerRun | null = null;
	let ask: DiscussAsk | null = null;
	let error = '';
	let gone = false;
	let bringing = false;
	let timer: ReturnType<typeof setTimeout> | null = null;
	let destroyed = false;
	let clock = Date.now();

	$: label = kind === 'answer' ? '精答' : '讨论台';
	$: href = `/${kind}/${chatId}`;
	$: status = (kind === 'answer' ? run?.status : ask?.status) ?? '';
	$: live = ['routing', 'researching', 'answering', 'running', 'concluding'].includes(status);
	$: settled = gone || (!!status && !live);
	$: done = status === 'done';
	$: chip = done
		? 'done'
		: live
			? 'running'
			: status === 'stopped'
				? 'stopped'
				: status
					? 'failed'
					: 'running';
	$: chipLabel =
		(kind === 'answer'
			? ANSWER_STATUS[status as keyof typeof ANSWER_STATUS]
			: DISCUSS_STATUS[status as keyof typeof DISCUSS_STATUS]) ?? label;
	$: question = (kind === 'answer' ? run?.question : ask?.question) ?? '';
	$: endedAt = (kind === 'answer' ? run?.endedAt : ask?.endedAt) ?? 0;

	// 精答: the assistant once the dispatcher picked it, and a glimpse of its answer as it streams
	$: assistant = run?.assistant ?? null;
	$: answerTail = (() => {
		const text = (run?.answer?.content ?? '').replace(/\s+/g, ' ').trim();
		return text.length > 120 ? `…${text.slice(-120)}` : text;
	})();
	$: answerLine = !run
		? ''
		: run.status === 'routing'
			? `${run.planner?.name ?? '调度器'} 在从助手库挑最合适的助手`
			: run.status === 'researching'
				? `${assistant?.name ?? '助手'} 在网上查资料`
				: run.status === 'answering'
					? run.answer?.retry
						? `${run.answer.retry.reason}，稍后重试`
						: `${assistant?.name ?? '助手'} 在回答`
					: assistant
						? actionSentence(assistant.action, assistant.name)
						: '';

	// 讨论: the table, the round and who is speaking
	$: seats = ask?.seats ?? [];
	$: speaking = (ask?.turns ?? [])
		.filter((t) => t.status === 'streaming' || (t.status === 'waiting' && t.startedAt))
		.map((t) => seats.find((s) => s.id === t.seat)?.label ?? '')
		.filter(Boolean);
	$: seatState = (seatId: string) => {
		const turn = [...(ask?.turns ?? [])].reverse().find((t) => t.seat === seatId);
		if (!turn) return 'waiting';
		if (turn.status === 'streaming') return turn.thinking ? 'thinking' : 'streaming';
		return turn.status === 'done' ? 'done' : turn.status === 'error' ? 'error' : 'waiting';
	};
	$: discussLine = !ask
		? ''
		: ask.status === 'concluding'
			? `${ask.conclusion?.name ?? '主持人'} 在写结论`
			: ask.status === 'running'
				? ask.matching?.status === 'running'
					? '在给每个席位匹配助手'
					: ask.round
						? `第 ${ask.round}/${ask.rounds} 轮${speaking.length ? ` · ${speaking.join('、')} 在发言` : ''}`
						: '准备开始'
				: ask.status === 'done'
					? `${seats.length} 个模型讨论了 ${ask.rounds} 轮，${ask.conclusion?.name ?? '主持人'} 写好了结论`
					: '';
	$: failure = (kind === 'answer' ? run?.error : ask?.error) ?? '';

	// The result posted into this chat: the reply under its notice (run id "<kind>:<chat id>:…").
	const findResult = (h: typeof history, prefix: string): string | null => {
		for (const m of Object.values(h?.messages ?? {})) {
			const runId = m?.hermes_notice?.run_id;
			if (
				m?.role === 'user' &&
				typeof runId === 'string' &&
				runId.startsWith(prefix) &&
				m?.childrenIds?.[0]
			)
				return m.childrenIds[0];
		}
		return null;
	};
	$: resultId = findResult(history, `${kind}:${chatId}:`);
	$: arriving = done && !resultId && endedAt > 0 && clock - endedAt < ARRIVING_MS;

	const jump = () => {
		document
			.getElementById(`message-${resultId}`)
			?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	};

	// 「把结果放进这个对话」: it did not make it in by itself (the chat stayed busy, a restart).
	const bring = async () => {
		if (bringing) return;
		bringing = true;
		try {
			const out = await (kind === 'answer' ? reportBackAnswer : reportBackDiscussion)(
				localStorage.token,
				chatId
			);
			if (!out.posted) toast.info('结果已经在这个对话里了');
		} catch (e) {
			toast.error(`${(e as Error)?.message ?? e}`);
		} finally {
			bringing = false;
		}
	};

	const load = async () => {
		try {
			if (kind === 'answer') {
				run = (await getAnswer(localStorage.token, chatId)).run;
			} else {
				const detail = await getDiscussion(localStorage.token, chatId);
				// the question sent from this chat (later questions are asked in the room itself)
				ask = detail.asks.find((a) => a.origin) ?? detail.asks[0] ?? null;
			}
			error = '';
		} catch (e) {
			if ((e as any)?.status === 404) {
				gone = true; // deleted on its page: nothing more to read
				return;
			}
			error = `${(e as any)?.message ?? e}`;
		}
		schedule();
	};

	const schedule = () => {
		if (timer) clearTimeout(timer);
		clock = Date.now();
		if (destroyed || gone) return;
		// settled: once more while the result is on its way, so 「正在发回」 turns into the button
		if (settled && !arriving) return;
		const hidden = typeof document !== 'undefined' && document.visibilityState === 'hidden';
		timer = setTimeout(settled ? () => schedule() : load, hidden ? POLL_HIDDEN_MS : POLL_MS[kind]);
	};

	const onVisibility = () => {
		if (document.visibilityState === 'visible' && !settled) load();
	};

	onMount(() => {
		load();
		document.addEventListener('visibilitychange', onVisibility);
	});
	onDestroy(() => {
		destroyed = true;
		if (timer) clearTimeout(timer);
		if (typeof document !== 'undefined')
			document.removeEventListener('visibilitychange', onVisibility);
	});
</script>

<!-- not-prose: the chat's Markdown typography must not style the card -->
<div
	class="not-prose my-2 flex max-w-2xl flex-col gap-2"
	data-teams-ui
	data-discuss-ui
	data-answer-ui
	data-mode-dispatch-card={kind}
	data-mode-dispatch-state={gone ? 'gone' : status || 'loading'}
>
	{#if gone}
		<div
			class="tm-card-quiet flex items-center gap-2.5 px-3.5 py-2.5 text-xs text-gray-500 dark:text-gray-400"
			data-mode-dispatch-gone
		>
			这个{kind === 'answer' ? '精答' : '讨论'}已经删除了；对话和发回来的结果都还在。
		</div>
	{:else}
		<div class="flex min-w-0 items-center gap-2.5">
			{#if kind === 'answer'}
				{#if assistant}
					<AssistantAvatar
						id={assistant.id}
						name={assistant.name}
						emoji={assistant.emoji ?? ''}
						size={26}
						state={live
							? run?.answer?.thinking
								? 'thinking'
								: 'streaming'
							: done
								? 'done'
								: 'idle'}
					/>
				{:else}
					<span
						class="tm-card-quiet grid size-[30px] shrink-0 place-items-center !rounded-full text-sm"
						aria-hidden="true">🎯</span
					>
				{/if}
			{:else}
				<span
					class="tm-card-quiet grid size-[30px] shrink-0 place-items-center !rounded-full text-sm"
					aria-hidden="true">💬</span
				>
			{/if}
			<div class="min-w-0 flex-1">
				<div class="flex min-w-0 items-center gap-2">
					<span
						class="truncate text-sm font-semibold text-gray-900 dark:text-gray-100"
						title={question}>{question || label}</span
					>
					{#if status}<span class="shrink-0"
							><StatusChip status={chip} label={chipLabel} size="sm" /></span
						>{/if}
				</div>
				<div class="flex min-w-0 items-center gap-1.5 text-[11px] text-gray-500 dark:text-gray-400">
					{#if kind === 'discuss' && seats.length}
						<span class="flex shrink-0 -space-x-1" aria-hidden="true">
							{#each seats.slice(0, 5) as seat, i (seat.id)}
								<SeatAvatar
									model={seat.model}
									name={seat.label}
									hue={seatHue(i)}
									state={seatState(seat.id)}
									size={14}
								/>
							{/each}
						</span>
					{/if}
					<span class="truncate" data-mode-dispatch-line
						>{label}{kind === 'discuss' && ask ? ` · ${modeSpec(ask.mode).label}` : ''}{(
							kind === 'answer' ? answerLine : discussLine
						)
							? ` · ${kind === 'answer' ? answerLine : discussLine}`
							: ''}</span
					>
				</div>
			</div>
			<a {href} class="tm-btn-ghost shrink-0 !text-xs" data-mode-dispatch-open
				>{live ? '去看看' : `打开${label}`}</a
			>
		</div>
		{#if kind === 'answer' && live && answerTail}
			<div
				class="tm-card-quiet line-clamp-2 px-3.5 py-2 text-xs leading-relaxed text-gray-600 dark:text-gray-300"
				data-mode-dispatch-preview
			>
				{answerTail}
			</div>
		{/if}
		{#if done}
			<div
				class="tm-card-quiet flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3.5 py-2.5 text-xs text-gray-600 dark:text-gray-300"
				data-mode-dispatch-done
			>
				<span class="font-medium text-gray-900 dark:text-gray-100"
					>{kind === 'answer' ? '回答已写好' : '结论已写好'}</span
				>
				{#if resultId}
					<span class="min-w-0 flex-1">已发回这个对话，可以接着追问。</span>
					<button
						type="button"
						class="shrink-0 font-medium text-sky-700 hover:underline dark:text-sky-300"
						on:click={jump}
						data-mode-dispatch-jump>看结果 ↓</button
					>
				{:else if arriving}
					<span class="min-w-0 flex-1" data-mode-dispatch-arriving>正在发回这个对话…</span>
				{:else}
					<span class="min-w-0 flex-1">还没放进这个对话。</span>
					<button
						type="button"
						class="shrink-0 font-medium text-sky-700 hover:underline disabled:opacity-60 dark:text-sky-300"
						disabled={bringing}
						on:click={bring}
						data-mode-dispatch-bring>{bringing ? '正在放进来…' : '把结果放进这个对话'}</button
					>
				{/if}
			</div>
		{:else if settled && failure}
			<div class="text-xs text-gray-500 dark:text-gray-400">{failure} · 可以到{label}页重试</div>
		{:else if error}
			<div class="text-xs text-amber-700 dark:text-amber-300">读不到{label}的进度：{error}</div>
		{:else if !status}
			<div class="tm-card-quiet h-12 animate-pulse" aria-busy="true" />
		{/if}
	{/if}
</div>
