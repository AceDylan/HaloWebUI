<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import '$lib/components/teams/teams.css';
	import '$lib/components/discuss/discuss.css';
	import '$lib/components/answer/answer.css';
	import { getAnswer, reportBackAnswer, type AnswerRun } from '$lib/apis/answers';
	import { getDiscussion, reportBackDiscussion, type DiscussAsk } from '$lib/apis/discussions';
	import StatusChip from '$lib/components/teams/StatusChip.svelte';
	import { elapsed, now } from '$lib/components/teams/clock';
	import AssistantAvatar from '$lib/components/answer/AssistantAvatar.svelte';
	import SeatAvatar from '$lib/components/discuss/SeatAvatar.svelte';
	import { actionSentence, STATUS_LABEL as ANSWER_STATUS } from '$lib/components/answer/model';
	import {
		modeSpec,
		seatHue,
		turnStatusText,
		STATUS_LABEL as DISCUSS_STATUS
	} from '$lib/components/discuss/model';

	/**
	 * 派发方式「精答」/「讨论」 in the chat it was sent from, in the 协作台 card's language: who
	 * answers or sits at the table, then one card with the steps (a halo on it while it works),
	 * what is happening right now and for how long — the answer as it streams, who is speaking —
	 * and once the answer / the conclusion is written, the way to it in this chat (it comes back
	 * as its own reply).
	 */
	export let kind: 'answer' | 'discuss';
	/** The run's own chat (/answer/<id>, /discuss/<id>). */
	export let chatId: string;
	/** The chat around the card: whether the result is already in it, and where. */
	export let history: { messages?: Record<string, any> } | null = null;

	type StepState = 'done' | 'active' | 'pending' | 'failed';
	type Step = { key: string; label: string; state: StepState; note?: string };

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
	$: ended = settled && !done && !gone;
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
	$: startedAt = (kind === 'answer' ? run?.startedAt : ask?.startedAt) ?? 0;
	$: endedAt = (kind === 'answer' ? run?.endedAt : ask?.endedAt) ?? 0;

	// 精答: the assistant once the dispatcher picked it, and a glimpse of its answer as it streams
	$: assistant = run?.assistant ?? null;
	$: answerTail = (() => {
		const text = (run?.answer?.content ?? '').replace(/\s+/g, ' ').trim();
		return text.length > 160 ? `…${text.slice(-160)}` : text;
	})();
	$: sources = (kind === 'answer' ? run?.research : ask?.research)?.sources?.length ?? 0;
	$: answerLine = !run
		? ''
		: run.status === 'routing'
			? `${run.planner?.name ?? '调度器'} 在从助手库挑最合适的助手`
			: run.status === 'researching'
				? `${assistant?.name ?? '助手'} 在网上查资料`
				: run.status === 'answering'
					? run.answer?.retry
						? `${run.answer.retry.reason}，稍后重试`
						: run.answer?.thinking && !run.answer?.content
							? `${assistant?.name ?? '助手'} 在思考`
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
	const lastTurn = (a: DiscussAsk | null, seatId: string) =>
		[...(a?.turns ?? [])].reverse().find((t) => t.seat === seatId) ?? null;
	$: seatState = (seatId: string) => {
		const turn = lastTurn(ask, seatId);
		if (!turn) return 'waiting';
		if (turn.status === 'streaming') return turn.thinking ? 'thinking' : 'streaming';
		return turn.status === 'done' ? 'done' : turn.status === 'error' ? 'error' : 'waiting';
	};
	$: seatText = (seatId: string) => {
		const turn = lastTurn(ask, seatId);
		if (!turn) return live ? '等待发言' : '';
		if (turn.status === 'done') return ask?.rounds && ask.rounds > 1 ? `第 ${turn.round} 轮已发言` : '已发言';
		return turnStatusText(turn, $now) || '';
	};
	$: moderatorState =
		ask?.conclusion?.status === 'streaming'
			? ask.conclusion.thinking
				? 'thinking'
				: 'streaming'
			: ask?.conclusion?.status === 'done'
				? 'done'
				: ask?.conclusion?.status === 'error'
					? 'error'
					: 'waiting';
	$: discussLine = !ask
		? ''
		: ask.status === 'concluding'
			? `${ask.conclusion?.name ?? '主持人'} 在写结论`
			: ask.status === 'running'
				? ask.matching?.status === 'running'
					? '在给每个席位匹配助手'
					: ask.research?.status === 'running'
						? '在网上查资料，查完放上讨论桌'
						: speaking.length
							? `${speaking.join('、')} 在发言`
							: ask.round
								? `第 ${ask.round}/${ask.rounds} 轮`
								: '准备开始'
				: ask.status === 'done'
					? `${seats.length} 个模型讨论了 ${ask.rounds} 轮，${ask.conclusion?.name ?? '主持人'} 写好了结论`
					: '';
	$: failure = (kind === 'answer' ? run?.error : ask?.error) ?? '';
	// stopped or failed: why, in place of what it was doing
	$: nowLine = ended ? failure || chipLabel : kind === 'answer' ? answerLine : discussLine;

	// what the header says under the question
	$: facts = (
		kind === 'answer'
			? [
					label,
					assistant
						? `${assistant.emoji ?? ''}${assistant.name}`
						: run
							? `调度 ${run.planner?.name ?? ''}`
							: '',
					sources ? `${sources} 个来源` : ''
				]
			: [
					label,
					ask ? modeSpec(ask.mode).label : '',
					seats.length ? `${seats.length} 个模型` : '',
					ask?.rounds ? `${ask.rounds} 轮` : '',
					ask?.moderator?.name ? `${ask.moderator.name} 主持` : '',
					ask?.files?.length ? `${ask.files.length} 个文件` : ''
				]
	).filter(Boolean);

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

	// The steps, ending with the result back in this chat. A run that stopped or failed marks the
	// step it stopped at.
	const settle = (steps: Step[], stoppedAt: boolean): Step[] => {
		if (!stoppedAt) return steps;
		let marked = false;
		return steps.map((step) => {
			if (step.state === 'done') return step;
			if (!marked) {
				marked = true;
				return { ...step, state: 'failed' };
			}
			return { ...step, state: 'pending' };
		});
	};
	const partDone = (s: string | undefined) => s === 'done' || s === 'empty' || s === 'error';
	$: answerSteps = ((): Step[] => {
		if (!run) return [];
		const steps: Step[] = [
			{
				key: 'pick',
				label: '挑助手',
				state: assistant ? 'done' : run.status === 'routing' ? 'active' : 'pending',
				note: assistant ? actionSentence(assistant.action, assistant.name) : ''
			}
		];
		if (run.plan?.webSearch || run.research) {
			steps.push({
				key: 'research',
				label: '查资料',
				state: partDone(run.research?.status)
					? 'done'
					: run.status === 'researching'
						? 'active'
						: 'pending',
				note: sources ? `${sources} 个来源` : run.research?.status === 'empty' ? '没查到' : ''
			});
		}
		steps.push({
			key: 'answer',
			label: '作答',
			state: run.answer?.status === 'done' ? 'done' : run.status === 'answering' ? 'active' : 'pending'
		});
		return steps;
	})();
	$: discussSteps = ((): Step[] => {
		if (!ask) return [];
		const steps: Step[] = [];
		const matching = ask.matching?.status;
		const research = ask.research?.status;
		const talked = ask.status === 'concluding' || ask.status === 'done' || ask.conclusion?.status === 'done';
		if (ask.matching) {
			steps.push({
				key: 'match',
				label: '匹配助手',
				state: matching === 'running' ? 'active' : matching === 'waiting' && !talked ? 'pending' : 'done'
			});
		}
		if (ask.research) {
			steps.push({
				key: 'research',
				label: '查资料',
				state: research === 'running' ? 'active' : partDone(research) || talked ? 'done' : 'pending',
				note: sources ? `${sources} 个来源` : ''
			});
		}
		const before = steps.some((s) => s.state === 'active');
		const round = Math.min(ask.round || 0, ask.rounds || 0);
		steps.push({
			key: 'talk',
			label: ask.rounds ? `讨论 ${talked ? ask.rounds : round}/${ask.rounds}` : '讨论',
			state: talked ? 'done' : ask.status === 'running' && !before ? 'active' : 'pending'
		});
		steps.push({
			key: 'conclude',
			label: '写结论',
			state:
				ask.conclusion?.status === 'done' || ask.status === 'done'
					? 'done'
					: ask.status === 'concluding'
						? 'active'
						: 'pending'
		});
		return steps;
	})();
	$: steps = [
		...settle(kind === 'answer' ? answerSteps : discussSteps, ended),
		{
			key: 'report',
			label: '发回对话',
			state: (resultId ? 'done' : done ? 'active' : 'pending') as StepState
		}
	];
	$: activeStep = steps.find((s) => s.state === 'active' || s.state === 'failed') ?? null;
	$: tone = live ? 'moving' : done ? (resultId ? 'done' : 'arriving') : 'ended';
	$: stageLabel = done ? (resultId ? '已发回' : arriving ? '发回中' : '已写好') : ended ? chipLabel : activeStep?.label ?? chipLabel;
	$: spent = live && startedAt ? $now - startedAt / 1000 : null;
	$: took = !live && startedAt && endedAt && endedAt > startedAt ? (endedAt - startedAt) / 1000 : null;

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

	// back on this tab: read again while it works, and after it stopped (it may have been
	// taken up again on its page meanwhile)
	const onVisibility = () => {
		if (document.visibilityState === 'visible' && (!settled || ended)) load();
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

<!-- not-prose: the chat's Markdown typography must not style the card (nor number its steps) -->
<div
	class="md-card not-prose my-2 flex max-w-2xl flex-col gap-2"
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
			<span class="md-tile size-[22px] text-[11px]" data-kind={kind} aria-hidden="true"
				>{kind === 'answer' ? '🎯' : '💬'}</span
			>
			这个{kind === 'answer' ? '精答' : '讨论'}已经删除了；对话和发回来的结果都还在。
		</div>
	{:else}
		<div class="flex min-w-0 items-center gap-2.5">
			{#if kind === 'answer' && assistant}
				<AssistantAvatar
					id={assistant.id}
					name={assistant.name}
					emoji={assistant.emoji ?? ''}
					size={28}
					state={live
						? run?.answer?.thinking
							? 'thinking'
							: run?.status === 'answering'
								? 'streaming'
								: 'waiting'
						: done
							? 'done'
							: 'idle'}
				/>
			{:else}
				<span
					class="md-tile size-[32px] text-[15px] {live ? 'tm-live' : ''}"
					data-kind={kind}
					aria-hidden="true">{kind === 'answer' ? '🎯' : '💬'}</span
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
				<div
					class="flex min-w-0 items-center gap-1.5 text-[11px] text-gray-500 dark:text-gray-400"
					data-mode-dispatch-facts
				>
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
					<span class="truncate">{facts.join(' · ')}</span>
				</div>
			</div>
			<a
				{href}
				class="{ended
					? 'tm-btn-primary !gap-1 !px-2.5 !py-1 !text-xs'
					: 'tm-btn-ghost !text-xs'} shrink-0"
				data-mode-dispatch-open>{live ? '去看看' : ended ? '去重试' : `打开${label}`}</a
			>
		</div>

		{#if status}
			<section
				class="md-stage tm-card px-4 py-3 {live ? 'tm-live' : ''}"
				data-tone={tone}
				data-mode-dispatch-stage
				aria-label="{label}的进度"
			>
				<ol class="md-rail mb-2.5 flex list-none items-center p-0" aria-label="步骤">
					{#each steps as step, i (step.key)}
						<li
							class="md-step flex shrink-0 items-center gap-1.5"
							data-step={step.key}
							data-state={step.state}
							title={step.note || null}
							aria-current={step.state === 'active' ? 'step' : undefined}
						>
							<span class="md-dot grid size-[18px] place-items-center rounded-full" aria-hidden="true">
								{#if step.state === 'done'}
									<svg class="size-2.5" viewBox="0 0 12 12" fill="none"
										><path
											d="m2.5 6.3 2.2 2.2 4.8-5"
											stroke="currentColor"
											stroke-width="1.8"
											stroke-linecap="round"
											stroke-linejoin="round"
										/></svg
									>
								{:else if step.state === 'failed'}
									<svg class="size-2.5" viewBox="0 0 12 12" fill="none"
										><path
											d="m3.5 3.5 5 5m0-5-5 5"
											stroke="currentColor"
											stroke-width="1.8"
											stroke-linecap="round"
										/></svg
									>
								{:else}
									<span class="md-core size-1.5 rounded-full" />
								{/if}
							</span>
							<span class="md-label whitespace-nowrap text-xs">{step.label}</span>
						</li>
						{#if i < steps.length - 1}
							<li
								class="md-bar mx-1.5 h-px min-w-3 flex-1"
								data-state={step.state === 'done' ? 'done' : 'pending'}
								aria-hidden="true"
							/>
						{/if}
					{/each}
				</ol>

				<div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
					<span class="md-kind shrink-0 text-xs font-semibold" data-mode-dispatch-stage-label
						>{stageLabel}</span
					>
					<p
						class="min-w-0 flex-1 basis-48 break-words text-sm text-gray-800 dark:text-gray-100"
						data-mode-dispatch-line
					>
						<span class={live ? 'tm-shimmer' : ''}>{nowLine}</span>
					</p>
					{#if spent !== null || took !== null}
						<span
							class="tm-num shrink-0 text-xs text-gray-500 dark:text-gray-400"
							data-mode-dispatch-clock
							>{spent !== null ? `已用 ${elapsed(spent)}` : `用时 ${elapsed(took ?? 0)}`}</span
						>
					{/if}
				</div>

				{#if kind === 'answer' && live && answerTail}
					<div
						class="md-preview mt-2.5 rounded-xl px-3 py-2 text-xs leading-relaxed text-gray-600 dark:text-gray-300"
						data-mode-dispatch-preview
					>
						<!-- the newest words stay in view: three lines kept from the bottom up -->
						<div class="md-tail"><p>{answerTail}<span class="md-caret" aria-hidden="true" /></p></div>
					</div>
				{/if}

				{#if kind === 'discuss' && seats.length && !done}
					<ul class="mt-2.5 flex list-none flex-wrap gap-1.5 p-0" data-mode-dispatch-seats>
						{#each seats as seat, i (seat.id)}
							{@const state = seatState(seat.id)}
							<li
								class="md-seat inline-flex max-w-full items-center gap-1.5 rounded-full px-2 py-[3px] text-[11px]"
								data-state={state}
								style="--seat-hue: {seatHue(i)}"
							>
								<span class="md-seat-dot size-1.5 shrink-0 rounded-full" aria-hidden="true" />
								<span class="truncate font-medium text-gray-700 dark:text-gray-200">{seat.label}</span>
								{#if seatText(seat.id)}<span class="shrink-0 text-gray-500 dark:text-gray-400"
										>{seatText(seat.id)}</span
									>{/if}
							</li>
						{/each}
						{#if ask?.conclusion?.name || ask?.moderator?.name}
							<li
								class="md-seat inline-flex max-w-full items-center gap-1.5 rounded-full px-2 py-[3px] text-[11px]"
								data-state={moderatorState}
								data-moderator
								style="--seat-hue: 250"
							>
								<span class="md-seat-dot size-1.5 shrink-0 rounded-full" aria-hidden="true" />
								<span class="truncate font-medium text-gray-700 dark:text-gray-200"
									>{ask?.conclusion?.name || ask?.moderator?.name}</span
								>
								<span class="shrink-0 text-gray-500 dark:text-gray-400"
									>{moderatorState === 'streaming' || moderatorState === 'thinking'
										? '在写结论'
										: '主持'}</span
								>
							</li>
						{/if}
					</ul>
				{/if}

				{#if ended}
					<p class="mt-1.5 text-xs text-gray-500 dark:text-gray-400" data-mode-dispatch-failure>
						到{kind === 'answer' ? '精答页' : '讨论台'}可以从停下的地方接着来，结果照样发回这个对话。
					</p>
				{/if}

				{#if done}
					<div
						class="md-foot mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 pt-2.5 text-xs text-gray-600 dark:text-gray-300"
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
							<span class="min-w-0 flex-1 tm-shimmer" data-mode-dispatch-arriving
								>正在发回这个对话…</span
							>
						{:else}
							<span class="min-w-0 flex-1">还没放进这个对话。</span>
							<button
								type="button"
								class="shrink-0 font-medium text-sky-700 hover:underline disabled:opacity-60 dark:text-sky-300"
								disabled={bringing}
								on:click={bring}
								data-mode-dispatch-bring
								>{bringing ? '正在放进来…' : '把结果放进这个对话'}</button
							>
						{/if}
					</div>
				{/if}
			</section>
		{:else if error}
			<div class="text-xs text-amber-700 dark:text-amber-300">读不到{label}的进度：{error}</div>
		{:else}
			<div class="tm-card h-[92px] animate-pulse" aria-busy="true" />
		{/if}
		{#if status && error}
			<div class="text-xs text-amber-700 dark:text-amber-300">读不到{label}的最新进度：{error}</div>
		{/if}
	{/if}
</div>

<style>
	/* the mode's mark where no face stands for it yet: 🎯 精答, 💬 讨论 */
	.md-tile {
		display: inline-grid;
		place-items: center;
		flex: none;
		border-radius: 9999px;
		background: linear-gradient(
			135deg,
			hsl(var(--md-hue) 90% 60% / 0.16),
			hsl(var(--md-hue-2) 90% 55% / 0.1)
		);
		box-shadow: inset 0 0 0 1px hsl(var(--md-hue) 80% 55% / 0.22);
	}
	.md-tile[data-kind='answer'] {
		--md-hue: 24;
		--md-hue-2: 350;
	}
	.md-tile[data-kind='discuss'] {
		--md-hue: 226;
		--md-hue-2: 268;
	}

	.md-stage {
		--md-tone: var(--tm-accent);
	}
	.md-stage[data-tone='done'] {
		--md-tone: var(--tm-done);
	}
	.md-stage[data-tone='arriving'] {
		--md-tone: var(--tm-ok);
	}
	.md-stage[data-tone='ended'] {
		--md-tone: var(--tm-warn);
	}
	/* Wherever it sits (a chat reply's Markdown styles too): steps are not a numbered list. */
	.md-stage :global(li) {
		list-style: none;
	}
	.md-stage li::marker {
		content: none;
	}
	.md-kind {
		color: hsl(var(--md-tone));
	}
	.md-dot {
		border: 1.5px solid hsl(var(--tm-line-strong));
		color: hsl(var(--tm-muted));
	}
	.md-step[data-state='done'] .md-dot {
		border-color: transparent;
		background: hsl(var(--tm-done));
		color: white;
	}
	.md-step[data-state='active'] .md-dot {
		border-color: hsl(var(--md-tone));
		color: hsl(var(--md-tone));
	}
	.md-step[data-state='active'] .md-core {
		background: currentColor;
	}
	.md-stage[data-tone='moving'] .md-step[data-state='active'] .md-core,
	.md-stage[data-tone='arriving'] .md-step[data-state='active'] .md-core {
		animation: md-beat 1.6s var(--tm-ease) infinite;
	}
	.md-step[data-state='failed'] .md-dot {
		border-color: transparent;
		background: hsl(var(--tm-warn));
		color: white;
	}
	.md-label {
		color: hsl(var(--tm-muted));
	}
	.md-step[data-state='active'] .md-label,
	.md-step[data-state='failed'] .md-label {
		color: hsl(var(--tm-ink));
		font-weight: 600;
	}
	.md-step[data-state='done'] .md-label {
		color: hsl(var(--tm-ink) / 0.75);
	}
	.md-bar {
		background: hsl(var(--tm-line-strong));
	}
	.md-bar[data-state='done'] {
		background: hsl(var(--tm-done) / 0.6);
	}

	/* the answer as it streams: a quiet well with a caret at the end */
	.md-preview {
		background: hsl(var(--tm-surface-2));
		border: 1px solid hsl(var(--tm-line));
	}
	.md-tail {
		display: flex;
		flex-direction: column;
		justify-content: flex-end;
		max-height: calc(3 * 1.625em);
		overflow: hidden;
	}
	.md-caret {
		display: inline-block;
		width: 2px;
		height: 0.95em;
		margin-left: 2px;
		vertical-align: -0.12em;
		border-radius: 1px;
		background: hsl(var(--tm-accent));
		animation: md-blink 1s steps(2, start) infinite;
	}

	/* who sits at the table and what each is doing */
	.md-seat {
		background: hsl(var(--tm-surface-2));
		border: 1px solid hsl(var(--tm-line));
	}
	.md-seat-dot {
		background: hsl(var(--tm-line-strong));
	}
	.md-seat[data-state='done'] .md-seat-dot {
		background: hsl(var(--seat-hue) 70% 55% / 0.85);
	}
	.md-seat[data-state='streaming'],
	.md-seat[data-state='thinking'] {
		border-color: hsl(var(--seat-hue) 80% 60% / 0.45);
		background: hsl(var(--seat-hue) 90% 60% / 0.08);
	}
	.md-seat[data-state='streaming'] .md-seat-dot,
	.md-seat[data-state='thinking'] .md-seat-dot {
		background: hsl(var(--seat-hue) 85% 58%);
		animation: md-beat 1.6s var(--tm-ease) infinite;
	}
	.md-seat[data-state='error'] .md-seat-dot {
		background: hsl(var(--tm-bad));
	}

	.md-foot {
		border-top: 1px solid hsl(var(--tm-line));
	}

	@keyframes md-beat {
		50% {
			transform: scale(1.7);
			opacity: 0.55;
		}
	}
	@keyframes md-blink {
		to {
			visibility: hidden;
		}
	}
	@media (max-width: 480px) {
		.md-step:not([data-state='active']):not([data-state='failed']) .md-label {
			display: none;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.md-core,
		.md-seat-dot,
		.md-tail {
		display: flex;
		flex-direction: column;
		justify-content: flex-end;
		max-height: calc(3 * 1.625em);
		overflow: hidden;
	}
	.md-caret {
			animation: none !important;
		}
	}
</style>
