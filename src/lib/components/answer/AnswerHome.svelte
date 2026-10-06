<script lang="ts">
	import { onDestroy, onMount, tick } from 'svelte';
	import { goto, replaceState } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { v4 as uuidv4 } from 'uuid';

	import '$lib/components/teams/teams.css';
	import '$lib/components/discuss/discuss.css';
	import './answer.css';
	import { config, mobile, models, showSidebar } from '$lib/stores';
	import {
		AnswerApiError,
		createAnswer,
		deleteAnswer,
		listAnswerAssistants,
		listAnswers,
		type AnswerDetail,
		type AnswerSummary,
		type LibraryAssistant
	} from '$lib/apis/answers';
	import { discussionSeatModels } from '$lib/utils/discussion-seats';
	import { originLabel, takeHandoff, type HandoffOrigin } from '$lib/utils/handoff';
	import HandoffBack from '$lib/components/common/HandoffBack.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import ModeEmblem from '$lib/components/scifi/ModeEmblem.svelte';
	import { warp } from '$lib/components/scifi/scifi';
	import { now, timeAgo } from '$lib/components/teams/clock';
	import { modelById, modelRef } from '$lib/components/discuss/model';
	import AssistantAvatar from './AssistantAvatar.svelte';
	import { ACTION_LABEL, isLive, QUICK, STATUS_LABEL } from './model';

	const LAST_KEY = 'halo.answer.last';

	let question = '';
	let planner = '';
	let research = true;
	let creating = false;
	let origin: HandoffOrigin | null = null;
	// Handed over from a chat: the conversation as background, and the way back.
	let background = '';
	let composer: HTMLTextAreaElement;
	let isMac = false;

	let items: AnswerSummary[] = [];
	let library: LibraryAssistant[] = [];
	let mayCreate = true;
	let loaded = false;
	let loadError = '';
	let query = '';
	let pendingDelete: AnswerSummary | null = null;
	let showDelete = false;
	let showAllAssistants = false;
	let timer: ReturnType<typeof setInterval> | null = null;

	// the dispatcher: any text model the discussion room would seat (not Hermes, not image models)
	$: choices = discussionSeatModels(($models ?? []) as any[], $config?.hermes_agent_model_ids).filter(
		(m: any) => !m?.info?.base_model_id
	);
	$: canStart = !creating && !!question.trim() && !!planner;
	$: webSearchEnabled = $config?.features?.enable_web_search !== false;
	$: shownAssistants = showAllAssistants ? library : library.slice(0, 10);
	$: needle = query.trim().toLowerCase();
	$: shown = items.filter(
		(d) => !needle || `${d.title}\n${d.question}\n${d.preview}\n${d.assistant?.name ?? ''}`.toLowerCase().includes(needle)
	);
	$: liveCount = items.filter((d) => isLive(d.status) || d.running).length;

	const pickDefaults = () => {
		let saved: any = null;
		try {
			saved = JSON.parse(localStorage.getItem(LAST_KEY) || 'null');
		} catch {
			saved = null;
		}
		const strong = choices.find((m: any) => /claude|gpt/i.test(m.name ?? m.id)) ?? choices[0];
		planner = saved?.planner && modelById(choices, saved.planner) ? saved.planner : strong ? modelRef(strong) : '';
		research = saved?.research !== false;
		const incoming = takeHandoff(typeof sessionStorage === 'undefined' ? null : sessionStorage, 'answer');
		if (incoming) {
			question = incoming.text;
			background = incoming.context;
			origin = incoming.from;
		}
		const params = new URLSearchParams(window.location.search);
		const q = params.get('q');
		if (q && !question) question = q.slice(0, 8000);
		if (params.has('q')) {
			try {
				replaceState('/answer', {});
			} catch {
				// before the router is ready: harmless, the parameter is only read here
			}
		}
		tick().then(resize);
	};
	let defaultsPicked = false;
	$: if (!defaultsPicked && choices.length) {
		defaultsPicked = true;
		pickDefaults();
	}

	const resize = () => {
		if (!composer) return;
		composer.style.height = 'auto';
		composer.style.height = `${Math.min(composer.scrollHeight, 320)}px`;
	};

	// One key per question as sent: a retry after a lost response gets the same run back.
	let attempt: { payload: string; key: string } | null = null;
	const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

	const start = async () => {
		if (creating || !question.trim() || !planner) return;
		creating = true;
		const form = {
			question: question.trim(),
			planner,
			research: webSearchEnabled && research,
			context: background
				? { text: background, title: origin?.title ?? '', chat_id: origin?.kind === 'chat' ? origin.id : null }
				: null
		};
		const payload = JSON.stringify(form);
		if (attempt?.payload !== payload) attempt = { payload, key: uuidv4() };
		try {
			const key = attempt.key;
			const send = async (tries: number): Promise<AnswerDetail> => {
				try {
					return await createAnswer(localStorage.token, { ...form, client_key: key });
				} catch (e: any) {
					if (e instanceof AnswerApiError || tries >= 2) throw e;
					await sleep(1500 * (tries + 1));
					return send(tries + 1);
				}
			};
			const res = await send(0);
			attempt = null;
			if (res.deduplicated) toast.info('这个问题刚刚已经在答了，直接打开它');
			try {
				localStorage.setItem(LAST_KEY, JSON.stringify({ planner, research }));
			} catch {
				// storage unavailable: defaults next time
			}
			await goto(`/answer/${res.id}`);
		} catch (e: any) {
			toast.error(e instanceof AnswerApiError ? e.message || '没能开始' : '网络不稳，没能开始；再点一次不会重复创建');
		} finally {
			creating = false;
		}
	};

	const useQuick = async (q: (typeof QUICK)[number]) => {
		question = q.text;
		await tick();
		resize();
		composer?.focus();
	};

	const load = async () => {
		try {
			items = await listAnswers(localStorage.token);
			loadError = '';
		} catch (e: any) {
			loadError = e?.message || '加载失败';
		} finally {
			loaded = true;
		}
	};
	const loadLibrary = async () => {
		try {
			const res = await listAnswerAssistants(localStorage.token);
			library = res.assistants;
			mayCreate = res.may_create;
		} catch {
			// the strip is a hint; the desk works without it
		}
	};

	const askDelete = (d: AnswerSummary) => {
		pendingDelete = d;
		showDelete = true;
	};
	const confirmDelete = async () => {
		const d = pendingDelete;
		pendingDelete = null;
		if (!d) return;
		try {
			await deleteAnswer(localStorage.token, d.id);
			items = items.filter((x) => x.id !== d.id);
			toast.success('已删除');
		} catch (e: any) {
			toast.error(e?.message || '删除失败');
		}
	};

	onMount(() => {
		isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
		warp(520);
		load();
		loadLibrary();
		timer = setInterval(() => {
			if (!document.hidden && items.some((d) => isLive(d.status) || d.running)) load();
		}, 4000);
		tick().then(resize);
	});
	onDestroy(() => {
		if (timer) clearInterval(timer);
	});
</script>

<div class="tm-ambient relative flex h-screen max-h-[100dvh] w-full flex-col" data-teams-ui data-discuss-ui data-answer-ui data-answer-home>
	<nav class="flex items-center gap-2 px-3 pt-2 pb-1">
		<div class="{$mobile ? '' : 'hidden'} flex flex-none items-center">
			<button
				class="rounded-xl p-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
				on:click={() => showSidebar.set(!$showSidebar)}
				aria-label="切换侧栏"><MenuLines /></button
			>
		</div>
		<h1 class="halo-crumb px-1">精答</h1>
		{#if origin}
			<HandoffBack {origin} />
		{/if}
	</nav>

	<div class="tm-scroll flex-1 overflow-y-auto px-4 pb-16">
		<div class="mx-auto flex max-w-3xl flex-col pt-6 sm:pt-14">
			<header class="halo-mode-hero tm-rise relative mb-6 flex flex-col gap-3">
				<ModeEmblem mode="answer" stats={[{ k: 'ASSISTANTS', v: library.length }, { k: 'ANSWERS', v: items.length }]} />
				<div class="flex items-center gap-2">
					<span class="tm-eyebrow halo-mode-eyebrow">Halo Precision</span>
					<span class="h-3 w-px bg-gray-300 dark:bg-gray-700" aria-hidden="true" />
					<span class="text-xs text-gray-500 dark:text-gray-400">按问题挑助手</span>
				</div>
				<h2 class="halo-mode-title tm-display text-[28px] font-semibold leading-[1.15] text-gray-950 sm:text-[36px] dark:text-white">
					每个问题，交给最合适的助手
				</h2>
				<p class="max-w-xl text-sm leading-relaxed text-gray-500 dark:text-gray-400">
					先读一遍你的助手库：有合适的就直接用；领域对但缺本事的，就把它升级一下；都不合适，就按这类问题新建一位专家。需要最新信息时先联网查资料，再由选中的助手作答。答完它就是一个普通对话，自动起标题、归进合适的分组，可以接着追问。
				</p>
			</header>

			<form
				class="tm-rise composer tm-card relative flex flex-col"
				style="--i:1"
				on:submit|preventDefault={start}
				data-answer-composer
				data-scifi-conduit
			>
				<label for="answer-question" class="sr-only">要问的问题</label>
				<textarea
					id="answer-question"
					bind:this={composer}
					bind:value={question}
					rows="3"
					maxlength="8000"
					class="tm-scroll w-full resize-none bg-transparent px-5 pt-4 pb-2 text-[15px] leading-relaxed text-gray-900 outline-none placeholder:text-gray-400 dark:text-gray-100 dark:placeholder:text-gray-500"
					placeholder="问任何问题，比如：租房合同里这条押金条款对我有什么风险？"
					on:input={resize}
					on:keydown={(e) => {
						if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
							e.preventDefault();
							start();
						}
					}}
					data-answer-input
				/>
				{#if background}
					<div class="px-4 pb-2" data-answer-context>
						<span class="dc-chip relative max-w-full !pr-6" title={background.slice(0, 600)}>
							<svg class="size-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
								><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg
							>
							<span class="truncate">带上{origin ? originLabel(origin) : '之前的对话'}作背景</span>
							<span class="tm-num shrink-0 text-gray-400">{background.length} 字</span>
							<button
								type="button"
								class="absolute right-1 top-1/2 grid size-4 -translate-y-1/2 place-items-center rounded-full text-gray-400 hover:bg-gray-500/15 hover:text-gray-700 dark:hover:text-gray-200"
								aria-label="不带对话背景"
								on:click={() => (background = '')}
								data-answer-context-remove>×</button
							>
						</span>
					</div>
				{/if}
				<div class="flex flex-wrap items-center gap-2 border-t border-gray-100 px-4 pt-3 pb-3 dark:border-gray-800/70">
					<label class="dc-chip !py-1 !pr-1.5" title="由谁读助手库、挑选或编写助手" data-answer-planner>
						<span>调度</span>
						<select bind:value={planner} class="dc-select max-w-[9rem] truncate">
							{#each choices as m (m.id)}
								<option value={modelRef(m)}>{m.name ?? m.id}</option>
							{/each}
						</select>
					</label>
					{#if webSearchEnabled}
						<button
							type="button"
							class="dc-chip"
							aria-pressed={research}
							title="允许联网：问题需要最新信息时先查资料，回答标注引用 [n]；关掉则只凭模型自己的知识"
							on:click={() => (research = !research)}
							data-answer-research-toggle
						>
							<svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
								><circle cx="8" cy="8" r="6.2" stroke="currentColor" stroke-width="1.3" /><path
									d="M1.8 8h12.4M8 1.8c1.8 2 1.8 10.4 0 12.4M8 1.8c-1.8 2-1.8 10.4 0 12.4"
									stroke="currentColor"
									stroke-width="1.1"
								/></svg
							>
							按需联网
						</button>
					{/if}
					<div class="ml-auto flex items-center gap-2">
						<kbd class="hidden rounded-md px-1.5 py-0.5 font-mono text-[11px] text-gray-400 sm:inline-block">{isMac ? '⌘' : 'Ctrl'} ↵</kbd>
						<button type="submit" class="tm-btn-primary" disabled={!canStart} data-answer-start>
							{#if creating}
								<span class="size-3.5 animate-spin rounded-full border-2 border-current border-r-transparent" aria-hidden="true" />开始中…
							{:else}
								精答
								<svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
									><path d="M3 8h9.5M8.5 4l4 4-4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" /></svg
								>
							{/if}
						</button>
					</div>
				</div>
			</form>
			<p class="mt-2 px-1 text-[11px] leading-relaxed text-gray-400 dark:text-gray-500">
				{mayCreate
					? '新建和升级的助手会保存到工作空间「助手」里（标签「精答」），之后在对话的模型菜单里也能直接选；升级前的设定会留着，可以一键撤销。'
					: '你没有新建助手的权限：没有合适的助手时，会临时按问题组一个助手回答，但不会保存。'}
			</p>

			<section class="tm-rise mt-6" style="--i:2" aria-label="助手库" data-answer-library>
				<div class="mb-2 flex items-center gap-2">
					<span class="tm-eyebrow">助手库</span>
					<span class="tm-num text-[11px] text-gray-400">{library.length}</span>
					<a href="/workspace/models" class="ml-auto text-[11px] text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">管理助手 →</a>
				</div>
				{#if library.length}
					<div class="flex flex-wrap gap-1.5">
						{#each shownAssistants as a (a.id)}
							<span class="ad-lib-chip" title="{a.name}{a.description ? `：${a.description}` : ''} · {a.baseName}" data-answer-library-item={a.id}>
								<AssistantAvatar id={a.id} name={a.name} emoji={a.emoji} size={20} />
								<span class="truncate text-gray-800 dark:text-gray-100">{a.name}</span>
								{#if a.byDesk}<span class="shrink-0 text-[10px] text-gray-400">精答</span>{/if}
							</span>
						{/each}
						{#if library.length > 10}
							<button type="button" class="dc-chip" on:click={() => (showAllAssistants = !showAllAssistants)}
								>{showAllAssistants ? '收起' : `全部 ${library.length} 位`}</button
							>
						{/if}
					</div>
				{:else}
					<p class="text-xs leading-relaxed text-gray-400 dark:text-gray-500">
						还没有助手。第一次提问时，会按问题的类型新建一位专家助手，以后同类问题都交给它。
					</p>
				{/if}
			</section>

			<section class="tm-rise mt-6" style="--i:3" aria-label="试一试">
				<div class="mb-2"><span class="tm-eyebrow">试一试</span></div>
				<ul class="grid grid-cols-2 gap-2 sm:grid-cols-4">
					{#each QUICK as q}
						<li>
							<button
								type="button"
								class="tm-card-quiet tm-hover flex h-full w-full flex-col items-start gap-1 px-3 py-2.5 text-left"
								on:click={() => useQuick(q)}
								title={q.text}
							>
								<span class="text-[13px] font-medium text-gray-900 dark:text-gray-100">{q.title}</span>
								<span class="text-[11.5px] text-gray-500 dark:text-gray-400">{q.hint}</span>
							</button>
						</li>
					{/each}
				</ul>
			</section>

			<section class="tm-rise mt-10" style="--i:4" aria-label="我的精答">
				<div class="mb-3 flex flex-wrap items-center gap-3">
					<h3 class="tm-display text-lg font-semibold text-gray-900 dark:text-gray-50">我的精答</h3>
					<span class="tm-num text-sm text-gray-400">{items.length}</span>
					{#if liveCount}<span class="rounded-full bg-blue-500/10 px-2 py-0.5 text-[11px] text-blue-600 dark:text-blue-300">{liveCount} 个进行中</span>{/if}
					<input
						type="search"
						bind:value={query}
						placeholder="搜索问题或助手"
						class="ml-auto w-full rounded-full border border-gray-200/70 bg-transparent px-3.5 py-1.5 text-xs outline-none focus:border-blue-400/60 sm:w-56 dark:border-gray-800"
					/>
				</div>

				{#if !loaded}
					<div class="flex flex-col gap-2">
						{#each [0, 1, 2] as i}
							<div class="tm-card h-[4.5rem] animate-pulse opacity-60" style="animation-delay: {i * 120}ms" />
						{/each}
					</div>
				{:else if loadError}
					<p class="text-sm text-red-600 dark:text-red-300">{loadError}</p>
				{:else if !shown.length}
					<div class="flex flex-col items-center gap-2 py-12 text-center text-sm text-gray-400 dark:text-gray-500">
						{items.length ? '没有符合条件的精答' : '还没有精答。写下一个问题试试。'}
					</div>
				{:else}
					<ul class="flex flex-col gap-2" data-answer-list>
						{#each shown as d (d.id)}
							{@const live = isLive(d.status) || d.running}
							<li class="group tm-card tm-hover relative flex items-center gap-3 px-4 py-3" data-answer-row={d.id}>
								<AssistantAvatar
									id={d.assistant?.id ?? ''}
									name={d.assistant?.name ?? '精答'}
									emoji={d.assistant?.emoji || (d.assistant ? '' : '✦')}
									size={26}
									state={live ? 'streaming' : 'idle'}
								/>
								<a href="/answer/{d.id}" class="min-w-0 flex-1 after:absolute after:inset-0" data-sveltekit-preload-data="off">
									<div class="truncate text-[14px] font-medium text-gray-900 dark:text-gray-100">{d.title}</div>
									<div class="mt-0.5 truncate text-xs text-gray-500 dark:text-gray-400">{d.preview || d.question}</div>
									<div class="mt-1 flex items-center gap-1.5 text-[11px] text-gray-400 dark:text-gray-500">
										{#if d.assistant}
											<span class="truncate">{ACTION_LABEL[d.assistant.action] ?? ''} · {d.assistant.name}</span>
											<span aria-hidden="true">·</span>
										{/if}
										{#if d.research}<span>联网</span><span aria-hidden="true">·</span>{/if}
										<span class="shrink-0">{timeAgo(d.updated_at, $now)}</span>
									</div>
								</a>
								<span
									class="relative shrink-0 rounded-full px-2 py-0.5 text-[11px] {live
										? 'bg-blue-500/10 text-blue-600 dark:text-blue-300'
										: d.status === 'error'
											? 'bg-red-500/10 text-red-600 dark:text-red-300'
											: 'bg-gray-500/10 text-gray-500 dark:text-gray-400'}">{STATUS_LABEL[d.status] ?? d.status}</span
								>
								<button
									type="button"
									class="relative shrink-0 rounded-lg p-1.5 text-gray-400 opacity-60 hover:bg-red-500/10 hover:text-red-600 group-hover:opacity-100 max-sm:opacity-100"
									aria-label="删除「{d.title}」"
									on:click={() => askDelete(d)}
									><svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
										><path d="M3 4.5h10M6.5 4.5V3h3v1.5M5 4.5l.5 8.5h5l.5-8.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" /></svg
									></button
								>
							</li>
						{/each}
					</ul>
				{/if}
			</section>
		</div>
	</div>
</div>

<ConfirmDialog
	bind:show={showDelete}
	title="删除这条精答？"
	message={`「${pendingDelete?.title ?? ''}」和之后在对话里的追问都会删除（它也是一个对话，会一起从侧栏消失）。用到的助手不受影响。`}
	confirmLabel="删除"
	on:confirm={confirmDelete}
/>

<style>
	.composer {
		border-radius: 1.4rem;
		transition:
			box-shadow 0.3s var(--tm-ease),
			border-color 0.3s ease;
	}
	.composer:focus-within {
		border-color: hsl(var(--tm-accent) / 0.45);
		box-shadow:
			0 0 0 4px hsl(var(--tm-accent) / 0.1),
			var(--tm-shadow-lift);
	}
</style>
