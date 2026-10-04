<script lang="ts">
	import { onDestroy, onMount, tick } from 'svelte';
	import { goto, replaceState } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import '$lib/components/teams/teams.css';
	import './discuss.css';
	import { config, mobile, models, showSidebar } from '$lib/stores';
	import {
		createDiscussion,
		deleteDiscussion,
		listDiscussions,
		type DiscussMode,
		type DiscussionSummary
	} from '$lib/apis/discussions';
	import { isHermesAgentModel } from '$lib/utils/hermes';
	import { isDedicatedImageGenerationModel } from '$lib/utils/model-capabilities';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import { now, timeAgo } from '$lib/components/teams/clock';
	import SeatAvatar from './SeatAvatar.svelte';
	import SeatPicker from './SeatPicker.svelte';
	import {
		isLive,
		MAX_ROUNDS,
		MAX_SEATS,
		MIN_SEATS,
		MODES,
		modeSpec,
		modelById,
		modelRef,
		seatHue,
		STATUS_LABEL,
		type SeatDraft
	} from './model';

	const LAST_KEY = 'halo.discuss.last';

	let question = '';
	let mode: DiscussMode = 'roundtable';
	let seats: SeatDraft[] = [];
	let rounds = 2;
	let moderator = '';
	let creating = false;
	let composer: HTMLTextAreaElement;
	let isMac = false;

	let items: DiscussionSummary[] = [];
	let loaded = false;
	let loadError = '';
	let filter: 'all' | 'live' | 'ended' = 'all';
	let query = '';
	let pendingDelete: DiscussionSummary | null = null;
	let showDelete = false;
	let timer: ReturnType<typeof setInterval> | null = null;

	// Text models that can sit at the table: not Hermes (an agent: minutes per turn, writes its
	// own memory), not image models, not hidden ones.
	$: choices = (($models ?? []) as any[]).filter(
		(m) =>
			m?.id &&
			!m?.info?.meta?.hidden &&
			m?.owned_by !== 'arena' &&
			!isHermesAgentModel(m, $config?.hermes_agent_model_ids) &&
			!isDedicatedImageGenerationModel(m.id)
	);
	$: spec = modeSpec(mode);
	$: if (spec.fixedRounds) rounds = spec.rounds;
	$: seatsValid = seats.length >= MIN_SEATS && seats.length <= MAX_SEATS && seats.every((s) => modelById(choices, s.model));
	$: canStart = !creating && !!question.trim() && seatsValid && !!moderator;
	$: moderatorChoices = choices;

	const pickDefaults = () => {
		if (!choices.length) return;
		let saved: any = null;
		try {
			saved = JSON.parse(localStorage.getItem(LAST_KEY) || 'null');
		} catch {
			saved = null;
		}
		const params = new URLSearchParams(window.location.search);
		const fromUrl = (params.get('models') || '')
			.split(',')
			.map((s) => s.trim())
			.filter((ref) => ref && modelById(choices, ref));
		const savedSeats: SeatDraft[] = Array.isArray(saved?.seats)
			? saved.seats.filter((s: any) => s?.model && modelById(choices, s.model))
			: [];
		if (fromUrl.length >= MIN_SEATS) {
			seats = fromUrl.slice(0, MAX_SEATS).map((ref) => ({ model: modelRef(modelById(choices, ref)!), role: '' }));
		} else if (savedSeats.length >= MIN_SEATS) {
			seats = savedSeats.slice(0, MAX_SEATS).map((s) => ({ model: s.model, role: String(s.role || '') }));
		} else {
			seats = choices.slice(0, Math.min(3, choices.length)).map((m) => ({ model: modelRef(m), role: '' }));
		}
		if (saved?.mode && MODES.some((m) => m.value === saved.mode)) mode = saved.mode;
		if (Number.isInteger(saved?.rounds)) rounds = Math.max(1, Math.min(MAX_ROUNDS, saved.rounds));
		else rounds = modeSpec(mode).rounds;
		const strong = choices.find((m) => /claude|gpt/i.test(m.name ?? m.id));
		moderator =
			saved?.moderator && modelById(choices, saved.moderator)
				? saved.moderator
				: strong
					? modelRef(strong)
					: seats[0]?.model ?? '';
		const q = params.get('q');
		if (q && !question) question = q.slice(0, 8000);
		// read once: a reload or a later visit starts from the saved setup, not these
		if (params.has('q') || params.has('models')) {
			try {
				replaceState('/discuss', {});
			} catch {
				// before the router is ready: harmless, the parameters are only read here
			}
		}
	};
	let defaultsPicked = false;
	$: if (!defaultsPicked && choices.length) {
		defaultsPicked = true;
		pickDefaults();
	}

	const setMode = (value: DiscussMode) => {
		mode = value;
		rounds = modeSpec(value).rounds;
	};

	const resize = () => {
		if (!composer) return;
		composer.style.height = 'auto';
		composer.style.height = `${Math.min(composer.scrollHeight, 320)}px`;
	};

	const start = async () => {
		if (!canStart) return;
		creating = true;
		try {
			const res = await createDiscussion(localStorage.token, {
				question: question.trim(),
				mode,
				seats: seats.map((s) => ({ model: s.model, role: s.role.trim() })),
				rounds,
				moderator
			});
			try {
				localStorage.setItem(LAST_KEY, JSON.stringify({ mode, seats, rounds, moderator }));
			} catch {
				// storage unavailable: defaults next time
			}
			await goto(`/discuss/${res.id}`);
		} catch (e: any) {
			toast.error(e?.message || '没能开始讨论');
		} finally {
			creating = false;
		}
	};

	const QUICK = [
		{ mode: 'roundtable' as DiscussMode, title: '技术选型', text: '5 个人的团队做内部工具，后端数据库用 Postgres 还是 MongoDB？' },
		{ mode: 'review' as DiscussMode, title: '方案评审', text: '帮我评审这个方案，指出最大的风险和缺口：\n\n（把方案贴在这里）' },
		{ mode: 'debate' as DiscussMode, title: '正反辩论', text: 'AI 编程助手会让初级程序员成长得更慢吗？' },
		{ mode: 'brainstorm' as DiscussMode, title: '头脑风暴', text: '一个面向大学生的记账 App，怎样让人坚持用下去？' }
	];
	const useQuick = async (q: (typeof QUICK)[number]) => {
		setMode(q.mode);
		question = q.text;
		await tick();
		resize();
		composer?.focus();
	};

	const load = async () => {
		try {
			items = await listDiscussions(localStorage.token);
			loadError = '';
		} catch (e: any) {
			loadError = e?.message || '加载失败';
		} finally {
			loaded = true;
		}
	};

	const FILTERS = [
		{ value: 'all', label: '全部' },
		{ value: 'live', label: '进行中' },
		{ value: 'ended', label: '已结束' }
	] as const;
	$: needle = query.trim().toLowerCase();
	$: shown = items.filter(
		(d) =>
			(filter === 'all' || (filter === 'live' ? isLive(d.status) || d.running : !(isLive(d.status) || d.running))) &&
			(!needle || `${d.title}\n${d.question}\n${d.preview}`.toLowerCase().includes(needle))
	);
	$: liveCount = items.filter((d) => isLive(d.status) || d.running).length;

	const askDelete = (d: DiscussionSummary) => {
		pendingDelete = d;
		showDelete = true;
	};
	const confirmDelete = async () => {
		const d = pendingDelete;
		pendingDelete = null;
		if (!d) return;
		try {
			await deleteDiscussion(localStorage.token, d.id);
			items = items.filter((x) => x.id !== d.id);
			toast.success('已删除');
		} catch (e: any) {
			toast.error(e?.message || '删除失败');
		}
	};

	onMount(() => {
		isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
		load();
		timer = setInterval(() => {
			if (!document.hidden && items.some((d) => isLive(d.status) || d.running)) load();
		}, 4000);
		tick().then(resize);
	});
	onDestroy(() => {
		if (timer) clearInterval(timer);
	});
</script>

<div class="tm-ambient relative flex h-screen max-h-[100dvh] w-full flex-col" data-teams-ui data-discuss-ui data-discuss-home>
	<nav class="flex items-center gap-2 px-3 pt-2 pb-1">
		<div class="{$mobile ? '' : 'hidden'} flex flex-none items-center">
			<button
				class="rounded-xl p-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
				on:click={() => showSidebar.set(!$showSidebar)}
				aria-label="切换侧栏"><MenuLines /></button
			>
		</div>
		<h1 class="halo-crumb px-1">讨论台</h1>
	</nav>

	<div class="tm-scroll flex-1 overflow-y-auto px-4 pb-16">
		<div class="mx-auto flex max-w-3xl flex-col pt-6 sm:pt-14">
			<header class="tm-rise mb-6 flex flex-col gap-3">
				<div class="flex items-center gap-2">
					<span class="tm-eyebrow">Halo Roundtable</span>
					<span class="h-3 w-px bg-gray-300 dark:bg-gray-700" aria-hidden="true" />
					<span class="text-xs text-gray-500 dark:text-gray-400">多模型讨论</span>
				</div>
				<h2 class="tm-display text-[28px] font-semibold leading-[1.15] text-gray-950 sm:text-[36px] dark:text-white">
					让几个模型把问题讨论透
				</h2>
				<p class="max-w-xl text-sm leading-relaxed text-gray-500 dark:text-gray-400">
					选两到五个模型，按圆桌、辩论、评审或头脑风暴的方式讨论：同一轮里大家同时发言、能看到彼此的观点，最后由主持人给出结论，并把共识和分歧分开列出来。
				</p>
			</header>

			<form class="tm-rise composer tm-card relative flex flex-col" style="--i:1" on:submit|preventDefault={start} data-discuss-composer>
				<label for="discuss-question" class="sr-only">要讨论的问题</label>
				<textarea
					id="discuss-question"
					bind:this={composer}
					bind:value={question}
					rows="3"
					maxlength="8000"
					class="tm-scroll w-full resize-none bg-transparent px-5 pt-4 pb-2 text-[15px] leading-relaxed text-gray-900 outline-none placeholder:text-gray-400 dark:text-gray-100 dark:placeholder:text-gray-500"
					placeholder="写下要讨论的问题，比如：小团队的内部工具，后端用 Postgres 还是 MongoDB？"
					on:input={resize}
					on:keydown={(e) => {
						if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
							e.preventDefault();
							start();
						}
					}}
				/>

				<div class="flex flex-col gap-3 border-t border-gray-100 px-4 pt-3 pb-3 dark:border-gray-800/70">
					<div class="tm-scroll tm-fade-x -mx-1 flex items-center gap-1.5 overflow-x-auto px-1" role="radiogroup" aria-label="讨论方式">
						{#each MODES as m}
							<button
								type="button"
								class="dc-chip shrink-0"
								role="radio"
								aria-checked={mode === m.value}
								data-on={mode === m.value}
								title={m.hint}
								on:click={() => setMode(m.value)}
								data-discuss-mode={m.value}>{m.label}</button
							>
						{/each}
						<span class="hidden shrink-0 pl-1 text-[11px] text-gray-400 sm:inline dark:text-gray-500">{spec.hint}</span>
					</div>

					<SeatPicker bind:seats {choices} mode={spec} />

					<div class="flex flex-wrap items-center gap-2">
						<div class="dc-chip !pr-1 !pl-2.5" data-discuss-rounds>
							<span>轮数</span>
							<button
								type="button"
								class="grid size-5 place-items-center rounded-full hover:bg-gray-500/10 disabled:opacity-30"
								disabled={spec.fixedRounds || rounds <= 1}
								on:click={() => (rounds = Math.max(1, rounds - 1))}
								aria-label="少一轮">−</button
							>
							<b class="tm-num w-3 text-center text-gray-800 dark:text-gray-100">{rounds}</b>
							<button
								type="button"
								class="grid size-5 place-items-center rounded-full hover:bg-gray-500/10 disabled:opacity-30"
								disabled={spec.fixedRounds || rounds >= MAX_ROUNDS}
								on:click={() => (rounds = Math.min(MAX_ROUNDS, rounds + 1))}
								aria-label="多一轮">+</button
							>
						</div>
						<label class="dc-chip !py-1 !pr-1.5" title="主持人：所有人发言后写结论，列出共识与分歧" data-discuss-moderator>
							<span>主持人</span>
							<select bind:value={moderator} class="dc-select max-w-[9rem] truncate">
								{#each moderatorChoices as m (m.id)}
									<option value={modelRef(m)}>{m.name ?? m.id}</option>
								{/each}
							</select>
						</label>
						<div class="ml-auto flex items-center gap-2">
							<kbd class="hidden rounded-md px-1.5 py-0.5 font-mono text-[11px] text-gray-400 sm:inline-block">{isMac ? '⌘' : 'Ctrl'} ↵</kbd>
							<button type="submit" class="tm-btn-primary" disabled={!canStart} data-discuss-start>
								{#if creating}
									<span class="size-3.5 animate-spin rounded-full border-2 border-current border-r-transparent" aria-hidden="true" />开始中…
								{:else}
									开始讨论
									<svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
										><path d="M3 8h9.5M8.5 4l4 4-4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" /></svg
									>
								{/if}
							</button>
						</div>
					</div>
				</div>
			</form>
			<p class="mt-2 px-1 text-[11px] leading-relaxed text-gray-400 dark:text-gray-500">
				每轮每位参与者调用一次模型，最后主持人再调用一次（{seats.length} 位 × {rounds} 轮 + 1 = 约 {seats.length * rounds + 1} 次）。Hermes 不参加讨论——它是要跑工具的代理；讨论结束后可以把结论「交给 Hermes」去核查或执行。
			</p>

			<section class="tm-rise mt-6" style="--i:2" aria-label="快速开始">
				<div class="mb-2"><span class="tm-eyebrow">快速开始</span></div>
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
								<span class="text-[11.5px] text-gray-500 dark:text-gray-400">{modeSpec(q.mode).label} · {modeSpec(q.mode).hint}</span>
							</button>
						</li>
					{/each}
				</ul>
			</section>

			<section class="tm-rise mt-10" style="--i:3" aria-label="我的讨论">
				<div class="mb-3 flex flex-wrap items-center gap-3">
					<h3 class="tm-display text-lg font-semibold text-gray-900 dark:text-gray-50">我的讨论</h3>
					<span class="tm-num text-sm text-gray-400">{items.length}</span>
					<input
						type="search"
						bind:value={query}
						placeholder="搜索标题或问题"
						class="ml-auto w-full rounded-full border border-gray-200/70 bg-transparent px-3.5 py-1.5 text-xs outline-none focus:border-blue-400/60 sm:w-56 dark:border-gray-800"
					/>
				</div>
				<div class="tm-segment mb-3 w-fit" role="tablist">
					{#each FILTERS as f}
						<button type="button" role="tab" aria-selected={filter === f.value} on:click={() => (filter = f.value)}
							>{f.label}{#if f.value === 'live' && liveCount}<span class="tm-num ml-1 opacity-60">{liveCount}</span>{/if}</button
						>
					{/each}
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
						{items.length ? '没有符合条件的讨论' : '还没有讨论。写下一个问题，让几个模型一起想。'}
					</div>
				{:else}
					<ul class="flex flex-col gap-2" data-discuss-list>
						{#each shown as d (d.id)}
							{@const live = isLive(d.status) || d.running}
							<li class="group tm-card tm-hover relative flex items-center gap-3 px-4 py-3" data-discuss-row={d.id}>
								<div class="flex shrink-0 -space-x-2">
									{#each (d.seats ?? []).slice(0, 4) as seat, i}
										<SeatAvatar model={seat.model} name={seat.label} hue={seatHue(i)} state={live ? 'streaming' : 'idle'} size={22} />
									{/each}
								</div>
								<a href="/discuss/{d.id}" class="min-w-0 flex-1 after:absolute after:inset-0" data-sveltekit-preload-data="off">
									<div class="flex min-w-0 items-center gap-2">
										<span class="truncate text-[14px] font-medium text-gray-900 dark:text-gray-100">{d.title}</span>
									</div>
									<div class="mt-0.5 truncate text-xs text-gray-500 dark:text-gray-400">
										{d.preview || d.question}
									</div>
									<div class="mt-1 flex items-center gap-1.5 text-[11px] text-gray-400 dark:text-gray-500">
										<span>{modeSpec(d.mode).label}</span>
										<span aria-hidden="true">·</span>
										<span>{d.seats?.length ?? 0} 位</span>
										{#if d.asks > 1}<span aria-hidden="true">·</span><span>{d.asks} 问</span>{/if}
										<span aria-hidden="true">·</span>
										<span>{timeAgo(d.updated_at, $now)}</span>
									</div>
								</a>
								<span
									class="relative shrink-0 rounded-full px-2 py-0.5 text-[11px] {live
										? 'bg-blue-500/10 text-blue-600 dark:text-blue-300'
										: d.status === 'error'
											? 'bg-red-500/10 text-red-600 dark:text-red-300'
											: 'bg-gray-500/10 text-gray-500 dark:text-gray-400'}"
									>{live ? (d.status === 'concluding' ? '总结中' : '讨论中') : STATUS_LABEL[d.status] ?? d.status}</span
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
	title="删除这个讨论？"
	message={`「${pendingDelete?.title ?? ''}」和其中所有发言、结论都会删除（它也是一个对话，会一起从侧栏消失）。`}
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
