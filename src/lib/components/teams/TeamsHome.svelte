<script lang="ts">
	import { onDestroy, onMount, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { slide } from 'svelte/transition';
	import { toast } from 'svelte-sonner';

	import './teams.css';
	import { mobile, showSidebar } from '$lib/stores';
	import {
		checkRunners,
		createTeam,
		deleteTeam,
		getTeamsMeta,
		listTeams,
		type Team,
		type TeamsMeta
	} from '$lib/apis/teams';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import ModeEmblem from '$lib/components/scifi/ModeEmblem.svelte';
	import { warp } from '$lib/components/scifi/scifi';
	import RunnerStatus from './RunnerStatus.svelte';
	import StatusChip from './StatusChip.svelte';
	import TeamAvatar from './TeamAvatar.svelte';
	import { uploadFile } from '$lib/apis/files';
	import { listLibrary } from '$lib/apis/assistant-library';
	import { goalWithBackground, originLabel, takeHandoff, type HandoffOrigin } from '$lib/utils/handoff';
	import HandoffBack from '$lib/components/common/HandoffBack.svelte';
	import { now, timeAgo } from './clock';
	import { avatarKind, etaSentence, formatEta, PHASE_LABEL, runnerLabel } from './model';

	// Stages a list row describes in words (what happens now, how long is left) instead of its facts.
	const LIST_STAGES = new Set([
		'planning',
		'approval',
		'starting',
		'running',
		'attention',
		'paused',
		'concluding',
		'illustrating',
		'checking'
	]);

	/** Your collaboration tasks (only yours) and a box to start a new one. */
	let teams: Team[] = [];
	let loaded = false;
	let error = '';
	let goal = '';
	let creating = false;
	let chatId: string | null = null;
	let meta: TeamsMeta | null = null;
	let metaError = '';
	let checking = false;
	let leadModel = '';
	// Where the team works: "" = the project the goal names (if any), "none" = a fresh directory,
	// a path = that git repository (the team gets its own branch there).
	let project = '';
	// 「直接开始」: the plan starts as soon as it is ready (remembered on this device).
	const AUTO_START_KEY = 'halo.teams.autoStart';
	let autoStart = false;
	const toggleAutoStart = () => {
		autoStart = !autoStart;
		try {
			localStorage.setItem(AUTO_START_KEY, autoStart ? '1' : '0');
		} catch {
			// storage unavailable: the choice holds for this page only
		}
	};
	let showRunners = false;
	let filter: 'all' | 'active' | 'review' | 'done' | 'ended' = 'all';
	let query = '';
	let composer: HTMLTextAreaElement;
	let pendingDelete: Team | null = null;
	let showDelete = false;
	let refreshTimer: ReturnType<typeof setInterval> | null = null;
	let isMac = false;

	// The lead follows Hermes' default model unless this team picks another configured one.
	$: defaultModel = meta?.lead_model?.choices?.[0] ?? meta?.lead_model?.model ?? '';
	$: modelChoices = (meta?.lead_model?.choices ?? []).filter((m) => m !== defaultModel);
	$: runners = meta?.registry?.runners ?? [];
	$: runnersUp = runners.filter((r) => r.available).length;

	$: chatTeams = chatId ? teams.filter((t) => t.chat_id === chatId) : [];

	const statusOf = (t: Team) => (t.status === 'running' ? (t.phase ?? 'running') : t.status);
	const chipOf = (s: string) =>
		({
			planning: 'running',
			plan_ready: 'waiting_user',
			plan_failed: 'failed',
			starting: 'queued',
			start_failed: 'failed',
			cancelled: 'stopped',
			running: 'running',
			attention: 'waiting_user',
			paused: 'paused',
			stopped: 'stopped',
			completed: 'done'
		})[s] ?? 'queued';
	const bucketOf = (t: Team): typeof filter => {
		const s = statusOf(t);
		if (s === 'plan_ready') return 'review';
		if (s === 'completed') return 'done';
		if (['cancelled', 'plan_failed', 'start_failed', 'stopped'].includes(s)) return 'ended';
		return 'active';
	};

	const FILTERS: { value: typeof filter; label: string }[] = [
		{ value: 'all', label: '全部' },
		{ value: 'active', label: '进行中' },
		{ value: 'review', label: '待批准' },
		{ value: 'done', label: '已完成' },
		{ value: 'ended', label: '已结束' }
	];
	$: counts = teams.reduce((acc, t) => ({ ...acc, [bucketOf(t)]: (acc[bucketOf(t)] ?? 0) + 1 }), {
		all: teams.length
	} as Record<string, number>);
	$: needle = query.trim().toLowerCase();
	$: shown = teams.filter(
		(t) =>
			(filter === 'all' || bucketOf(t) === filter) &&
			(!needle || `${t.title}\n${t.goal}`.toLowerCase().includes(needle))
	);
	$: activeCount = counts.active ?? 0;
	// A team that just finished is still moving while the lead writes and checks its result.
	$: settling = teams.some(
		(t) => t.stage && ['concluding', 'illustrating', 'checking'].includes(t.stage.key)
	);

	const QUICK_STARTS = [
		{
			icon: 'research',
			desc: '多方调研 → 对比报告 → 评审核对',
			title: '调研对比',
			text: '调研 3 个主流的开源看板工具，对比功能、活跃度、部署难度和上手成本，写一份带推荐结论的报告；最后由评审成员核对事实和出处。'
		},
		{
			icon: 'build',
			desc: '后端与测试、前端页面、说明文档',
			title: '功能开发',
			text: '在工作目录实现一个命令行待办工具：后端成员写核心逻辑和单元测试并跑通，前端成员做一个单文件网页界面，最后写 README 说明用法和测试结果。'
		},
		{
			icon: 'review',
			desc: '正确性 / 性能 / 安全三路并查',
			title: '代码审查',
			text: '审查 /root/项目路径 最近的改动：分别从正确性、性能、安全三个角度找问题，按严重程度列出并给出修改建议，最后汇总成一份审查报告。'
		},
		{
			icon: 'doc',
			desc: '方案初稿与架构图，评审后修订',
			title: '方案撰写',
			text: '为「团队知识库」写一份技术方案：背景与目标、架构图（Mermaid）、数据模型、里程碑和风险；写完由评审成员挑错并修订。'
		}
	];

	const useQuickStart = async (text: string) => {
		goal = text;
		await tick();
		resize();
		composer?.focus();
	};

	const resize = () => {
		if (!composer) return;
		composer.style.height = 'auto';
		composer.style.height = `${Math.min(composer.scrollHeight, 320)}px`;
	};

	const load = async () => {
		try {
			teams = (await listTeams(localStorage.token)).teams;
			error = '';
		} catch (e) {
			error = `${e?.message ?? e}`;
		} finally {
			loaded = true;
		}
	};

	const loadMeta = async () => {
		try {
			meta = await getTeamsMeta(localStorage.token);
			metaError = '';
		} catch (e) {
			metaError = `${e?.message ?? e}`;
		}
	};

	const recheck = async () => {
		if (checking) return;
		checking = true;
		try {
			const registry = await checkRunners(localStorage.token);
			meta = meta ? { ...meta, registry } : meta;
			if (!meta) await loadMeta();
			metaError = '';
		} catch (e) {
			metaError = `${e?.message ?? e}`;
		} finally {
			checking = false;
		}
	};

	// Handed over from a chat or a discussion: the conversation (or conclusion) as background
	// written under the goal, and the way back.
	let background = '';
	let origin: HandoffOrigin | null = null;

	// Files given with the goal (uploaded first, then handed to the team by id).
	let attached: { id: string | null; name: string; size: number; error?: string }[] = [];
	let fileInput: HTMLInputElement;
	$: uploading = attached.some((f) => !f.id && !f.error);
	const ATTACH_MAX = 20;
	const ATTACH_MAX_BYTES = 50 * 1024 * 1024;

	const attach = async (files: FileList | File[] | null) => {
		for (const file of Array.from(files ?? [])) {
			if (attached.length >= ATTACH_MAX) {
				toast.error(`最多带 ${ATTACH_MAX} 个文件`);
				break;
			}
			if (file.size > ATTACH_MAX_BYTES) {
				toast.error(`「${file.name}」超过 50 MB`);
				continue;
			}
			const entry = { id: null as string | null, name: file.name, size: file.size };
			attached = [...attached, entry];
			try {
				const res = await uploadFile(localStorage.token, file, { process: false });
				entry.id = res?.id ?? null;
				if (!entry.id) throw new Error('上传没有返回文件');
			} catch (e) {
				(entry as any).error = `${(e as any)?.message ?? e}`;
				toast.error(`「${file.name}」上传失败`);
			}
			attached = [...attached];
		}
		if (fileInput) fileInput.value = '';
	};
	const detach = (i: number) => (attached = attached.filter((_, j) => j !== i));

	// 「用于协作」 from the assistant library (/teams?assistant=<ref>): the lead staffs at least one
	// member with it. The name comes from the library (model:<id>) or the templates (builtin:<id>).
	let preferred: { ref: string; name: string; emoji: string } | null = null;
	const loadPreferred = async (ref: string) => {
		if (!/^(model|builtin):.+/.test(ref)) return;
		preferred = { ref, name: '', emoji: '' };
		let found: { name: string; emoji: string } | null = null;
		try {
			if (ref.startsWith('builtin:')) {
				const { default: agents } = await import('$lib/data/agents-zh.json');
				const id = ref.slice('builtin:'.length);
				const hit = (agents as { id: string | number; name: string; emoji?: string }[]).find(
					(a) => String(a.id) === id
				);
				if (hit) found = { name: hit.name, emoji: hit.emoji ?? '' };
			} else {
				const hit = (await listLibrary(localStorage.token)).assistants.find((a) => a.ref === ref);
				if (hit) found = { name: hit.name, emoji: hit.emoji ?? '' };
			}
		} catch {
			// the library could not be read now: keep the pick, the server checks it
			found = { name: ref.replace(/^(model|builtin):/, ''), emoji: '' };
		}
		if (preferred?.ref !== ref) return; // removed (or replaced) meanwhile
		if (found) {
			preferred = { ref, ...found };
		} else {
			preferred = null;
			toast.error('找不到要指定的助手（可能已删除或归档）');
		}
	};

	const create = async () => {
		const text = goal.trim() ? goalWithBackground(goal, background, origin) : '';
		if (!text || creating || uploading) return;
		creating = true;
		try {
			const team = await createTeam(
				localStorage.token,
				text,
				chatId,
				leadModel || null,
				project,
				autoStart,
				attached.filter((f) => f.id).map((f) => f.id as string),
				preferred ? [preferred.ref] : []
			);
			goto(`/teams/${team.id}`);
		} catch (e) {
			toast.error(`${e?.message ?? e}`);
		} finally {
			creating = false;
		}
	};

	const again = async (team: Team) => {
		goal = team.goal;
		await tick();
		resize();
		composer?.focus();
		composer?.scrollIntoView({ behavior: 'smooth', block: 'center' });
	};

	const askDelete = (team: Team) => {
		pendingDelete = team;
		showDelete = true;
	};
	const confirmDelete = async () => {
		const team = pendingDelete;
		if (!team) return;
		try {
			await deleteTeam(localStorage.token, team.id);
			teams = teams.filter((t) => t.id !== team.id);
			toast.success('已删除');
		} catch (e) {
			toast.error(`${e?.message ?? e}`);
		} finally {
			pendingDelete = null;
		}
	};

	// Teams at work move on their own: refresh the list while any is active and the page is seen.
	const startRefresh = () => {
		if (refreshTimer) return;
		refreshTimer = setInterval(() => {
			if (document.visibilityState === 'visible' && (activeCount > 0 || settling)) load();
		}, 15000);
	};

	onMount(() => {
		warp(520);
		try {
			autoStart = localStorage.getItem(AUTO_START_KEY) === '1';
		} catch {
			autoStart = false;
		}
		// "发起协作任务" from a chat links here with ?chat=<id> (and an optional ?goal=).
		const params = new URLSearchParams(window.location.search);
		chatId = params.get('chat');
		goal = params.get('goal') ?? '';
		const assistantRef = params.get('assistant');
		if (assistantRef) loadPreferred(assistantRef);
		const incoming = takeHandoff(typeof sessionStorage === 'undefined' ? null : sessionStorage, 'teams');
		if (incoming) {
			if (incoming.text) goal = incoming.text;
			origin = incoming.from;
			// a team started from a chat belongs to it: its conclusion comes back there
			if (incoming.from?.kind === 'chat') chatId = incoming.from.id;
			background = incoming.context;
			attached = incoming.files.map((f) => ({ id: f.id, name: f.name, size: 0 }));
		}
		isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
		load();
		loadMeta();
		startRefresh();
		tick().then(resize);
	});
	onDestroy(() => {
		if (refreshTimer) clearInterval(refreshTimer);
	});
</script>

<div
	class="tm-ambient relative flex h-screen max-h-[100dvh] w-full flex-col"
	data-teams-home
	data-teams-ui
>
	<nav class="flex items-center gap-2 px-3 pt-2 pb-1">
		<div class="{$mobile ? '' : 'hidden'} flex flex-none items-center">
			<button
				class="rounded-xl p-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
				on:click={() => showSidebar.set(!$showSidebar)}
				aria-label="切换侧栏"><MenuLines /></button
			>
		</div>
		<h1 class="halo-crumb px-1">协作台</h1>
		{#if origin}
			<HandoffBack {origin} />
		{:else if chatId}
			<a
				href="/c/{chatId}"
				class="ml-auto rounded-xl px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-850"
				>← 返回对话</a
			>
		{/if}
	</nav>

	<div class="tm-scroll flex-1 overflow-y-auto px-4 pb-16">
		<div class="mx-auto flex max-w-3xl flex-col pt-6 sm:pt-14">
			<!-- hero -->
			<header class="halo-mode-hero tm-rise relative mb-6 flex flex-col gap-3">
				<ModeEmblem mode="teams" stats={[{ k: 'MISSIONS', v: teams.length }, { k: 'ACTIVE', v: activeCount }]} />
				<div class="flex items-center gap-2">
					<span class="tm-eyebrow halo-mode-eyebrow">Halo Teams</span>
					<span class="h-3 w-px bg-gray-300 dark:bg-gray-700" aria-hidden="true" />
					<span class="text-xs text-gray-500 dark:text-gray-400">多代理协作</span>
				</div>
				<h2
					class="halo-mode-title tm-display text-[28px] font-semibold leading-[1.15] text-gray-950 sm:text-[36px] dark:text-white"
				>
					把目标交给一支 AI 团队
				</h2>
				<p class="max-w-xl text-sm leading-relaxed text-gray-500 dark:text-gray-400">
					负责人拆分任务、为每位成员挑选最合适的代理并按依赖并行推进；你批准计划后才开工，结束时交付完整结果——完整的答案、文档和图片。在对话的「+」菜单、回答的「⋯」或讨论结论下，也能直接交给协作台。
				</p>
				<p
					class="max-w-xl text-xs leading-relaxed text-gray-400 dark:text-gray-500"
					data-teams-tg-hint
				>
					不在电脑前也行：在 Telegram 给 Hermes 发 <code
						class="rounded bg-gray-100 px-1 py-0.5 font-mono text-[11px] text-gray-600 dark:bg-gray-800 dark:text-gray-300"
						>/team 目标</code
					>
					就能发起；计划、成员提问和完成结论都会推送到 Telegram，直接点按钮或回复即可。
				</p>
			</header>

			<!-- composer -->
			<form
				class="tm-rise composer tm-card relative flex flex-col"
				style="--i:1"
				on:submit|preventDefault={create}
				on:dragover|preventDefault
				on:drop|preventDefault={(e) => attach(e.dataTransfer?.files ?? null)}
				data-team-composer
				data-scifi-conduit
			>
				<label for="team-goal" class="sr-only">要协作完成的目标</label>
				<textarea
					id="team-goal"
					bind:this={composer}
					bind:value={goal}
					rows="3"
					maxlength="8000"
					class="tm-scroll w-full resize-none bg-transparent px-5 pt-4 pb-2 text-[15px] leading-relaxed text-gray-900 outline-none placeholder:text-gray-400 dark:text-gray-100 dark:placeholder:text-gray-500"
					placeholder="描述你想完成的事，比如：调研三个开源看板工具并写一份对比报告，最后由评审成员检查结论"
					on:input={resize}
					on:paste={(e) => {
						const files = e.clipboardData?.files;
						if (files?.length) {
							e.preventDefault();
							attach(files);
						}
					}}
					on:keydown={(e) => {
						if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
							e.preventDefault();
							create();
						}
					}}
				/>
				{#if chatId}
					<div class="px-5 pb-1 text-xs text-sky-700 dark:text-sky-300">会关联到你刚才的对话</div>
				{/if}
				{#if background}
					<div class="px-4 pb-1.5" data-team-context>
						<span class="pill relative inline-flex max-w-full items-center gap-1.5 rounded-full py-0.5 pr-6 pl-2.5 text-xs" title={background.slice(0, 600)}>
							<svg class="size-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
								><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg
							>
							<span class="truncate">带上{origin ? originLabel(origin) : '之前的对话'}作背景</span>
							<span class="tm-num shrink-0 text-gray-400">{background.length} 字</span>
							<button
								type="button"
								class="absolute right-1 top-1/2 grid size-4 -translate-y-1/2 place-items-center rounded-full text-gray-400 hover:bg-gray-500/15 hover:text-gray-700 dark:hover:text-gray-200"
								aria-label="不带背景"
								on:click={() => (background = '')}
								data-team-context-remove>×</button
							>
						</span>
					</div>
				{/if}
				{#if preferred}
					<div class="px-4 pb-1.5" data-team-assistant={preferred.ref}>
						<span
							class="pill relative inline-flex max-w-full items-center gap-1.5 rounded-full py-0.5 pr-6 pl-2.5 text-xs"
							title="负责人会安排至少一位成员用这个助手"
						>
							<span class="shrink-0" aria-hidden="true">{preferred.emoji || '✦'}</span>
							<span class="truncate">指定成员助手：{preferred.name || '读取中…'}</span>
							<button
								type="button"
								class="absolute right-1 top-1/2 grid size-4 -translate-y-1/2 place-items-center rounded-full text-gray-400 hover:bg-gray-500/15 hover:text-gray-700 dark:hover:text-gray-200"
								aria-label="不指定助手"
								on:click={() => (preferred = null)}
								data-team-assistant-remove>×</button
							>
						</span>
					</div>
				{/if}
				{#if attached.length}
					<ul class="flex flex-wrap gap-1.5 px-4 pb-1.5" aria-label="附带的文件" data-team-attachments>
						{#each attached as f, i (f.name + i)}
							<li
								class="pill flex max-w-[16rem] items-center gap-1.5 rounded-full py-0.5 pr-1 pl-2.5 text-xs {f.error
									? '!border-red-400/50 text-red-700 dark:text-red-300'
									: ''}"
								data-attachment-state={f.error ? 'failed' : f.id ? 'ready' : 'uploading'}
							>
								{#if !f.id && !f.error}
									<span
										class="size-3 shrink-0 animate-spin rounded-full border-2 border-current border-r-transparent"
										aria-hidden="true"
									/>
								{/if}
								<span class="min-w-0 truncate" title={f.error ?? f.name}>{f.name}</span>
								<button
									type="button"
									class="grid size-4 shrink-0 place-items-center rounded-full text-gray-400 hover:bg-gray-500/10 hover:text-gray-700 dark:hover:text-gray-200"
									aria-label="去掉 {f.name}"
									on:click={() => detach(i)}>×</button
								>
							</li>
						{/each}
					</ul>
				{/if}
				<div class="flex items-center gap-2 px-3 pt-1 pb-3">
					<input
						bind:this={fileInput}
						type="file"
						multiple
						class="hidden"
						on:change={(e) => attach(e.currentTarget.files)}
						data-team-file-input
					/>
					<button
						type="button"
						class="pill grid size-7 shrink-0 place-items-center rounded-full text-gray-600 dark:text-gray-300"
						title="附带文件或图片：团队开工时会放进工作目录的 inputs/，成员都能读"
						aria-label="附带文件"
						on:click={() => fileInput?.click()}
						data-team-attach
						><svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
							><path
								d="M10.5 4.5 5.4 9.6a1.6 1.6 0 0 0 2.3 2.3l5.2-5.2a3 3 0 0 0-4.3-4.3L3.4 7.6a4.4 4.4 0 0 0 6.2 6.2l4-4"
								stroke="currentColor"
								stroke-width="1.3"
								stroke-linecap="round"
								stroke-linejoin="round"
							/></svg
						></button
					>
					<div class="tm-scroll tm-fade-x flex min-w-0 flex-1 items-center gap-2 overflow-x-auto">
						<label
							class="pill flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full py-1 pr-1 pl-2.5 text-xs"
							data-lead-model
							title="负责人做计划、写结论用的模型；默认跟随 Hermes 当前的默认模型"
						>
							<TeamAvatar kind="lead" size={16} />
							<span class="shrink-0 text-gray-500 dark:text-gray-400">负责人</span>
							<select
								bind:value={leadModel}
								class="compact-select min-w-0 max-w-[9rem] truncate sm:max-w-[12rem]"
							>
								<option value=""
									>{meta?.lead_model?.model
										? `默认 · ${defaultModel}`
										: 'Hermes 默认'}</option
								>
								{#each modelChoices as model}
									<option value={model}>{model}</option>
								{/each}
							</select>
						</label>
						<label
							class="pill flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full py-1 pr-1 pl-2.5 text-xs"
							data-team-project
							title="团队在哪干活：自动 = 目标里点名了项目就在项目里，否则新目录；项目 = 在这个 git 仓库的独立分支上改（合并、推送由你在协作台决定）；新目录 = 一个空的工作目录"
						>
							<svg
								class="size-3.5 shrink-0 text-gray-400"
								viewBox="0 0 16 16"
								fill="none"
								aria-hidden="true"
								><path
									d="M2 4.5A1.5 1.5 0 0 1 3.5 3h2.6l1.4 1.5h5A1.5 1.5 0 0 1 14 6v5.5a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 11.5v-7Z"
									stroke="currentColor"
									stroke-width="1.3"
									stroke-linejoin="round"
								/></svg
							>
							<span class="shrink-0 text-gray-500 dark:text-gray-400">在哪做</span>
							<select
								bind:value={project}
								class="compact-select min-w-0 max-w-[9rem] truncate sm:max-w-[12rem]"
							>
								<option value="" title="目标里点名了项目就在项目里，否则用新目录">自动</option>
								<option value="none">新目录</option>
								{#each meta?.projects ?? [] as p (p.path)}
									<option value={p.path}>项目 · {p.name}</option>
								{/each}
							</select>
						</label>
						<button
							type="button"
							class="pill inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs text-gray-600 dark:text-gray-300"
							aria-expanded={showRunners}
							on:click={() => (showRunners = !showRunners)}
							data-runner-summary
						>
							<span class="flex -space-x-0.5" aria-hidden="true">
								{#each runners.slice(0, 6) as r}
									<span
										class="size-1.5 rounded-full ring-2 ring-white dark:ring-gray-900 {r.available
											? 'bg-emerald-500'
											: r.state === 'not_configured'
												? 'bg-gray-300 dark:bg-gray-600'
												: 'bg-red-500'}"
									/>
								{/each}
							</span>
							{#if !meta && !metaError}
								检测执行来源…
							{:else if metaError}
								执行来源检测失败
							{:else}
								执行来源 <b class="tm-num font-semibold">{runnersUp}/{runners.length}</b> 可用
							{/if}
							<svg
								class="size-3 transition-transform {showRunners ? 'rotate-180' : ''}"
								viewBox="0 0 12 12"
								fill="none"
								aria-hidden="true"
								><path
									d="m3 4.5 3 3 3-3"
									stroke="currentColor"
									stroke-width="1.4"
									stroke-linecap="round"
									stroke-linejoin="round"
								/></svg
							>
						</button>
					</div>
					<div class="ml-auto flex shrink-0 items-center gap-2">
						<button
							type="button"
							class="pill inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs {autoStart
								? 'pill-on'
								: 'text-gray-600 dark:text-gray-300'}"
							aria-pressed={autoStart}
							on:click={toggleAutoStart}
							title="打开后，负责人做好计划就直接开始，不用你批准（有成员没有可用的执行来源时仍会等你）。计划照样能在工作台里看，运行中也能对负责人说要改什么。"
							data-auto-start
						>
							<svg class="size-3.5 shrink-0" viewBox="0 0 16 16" fill="none" aria-hidden="true"
								><path
									d="M9 1.75 3.75 9h3.5L6.5 14.25 12.25 6.75h-3.5L9 1.75Z"
									stroke="currentColor"
									stroke-width="1.3"
									stroke-linejoin="round"
									fill={autoStart ? 'currentColor' : 'none'}
								/></svg
							>
							直接开始
						</button>
						<kbd
							class="hidden rounded-md px-1.5 py-0.5 font-mono text-[11px] text-gray-400 sm:inline-block"
							title="快捷键提交">{isMac ? '⌘' : 'Ctrl'} ↵</kbd
						>
						<button
							type="submit"
							class="tm-btn-primary max-sm:!px-2.5"
							disabled={creating || uploading || !goal.trim()}
							aria-label="让负责人做计划"
							data-create-team
						>
							{#if creating}
								<span
									class="size-3.5 animate-spin rounded-full border-2 border-current border-r-transparent"
									aria-hidden="true"
								/>提交中…
							{:else}
								<span class="max-sm:sr-only">让负责人做计划</span>
								<svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
									><path
										d="M3 8h9.5M8.5 4l4 4-4 4"
										stroke="currentColor"
										stroke-width="1.7"
										stroke-linecap="round"
										stroke-linejoin="round"
									/></svg
								>
							{/if}
						</button>
					</div>
				</div>
			</form>
			<p class="mt-2 px-1 text-[11px] text-gray-400 dark:text-gray-500">
				做计划只调用一次模型，不会启动任何成员；计划要你批准才会执行。
			</p>

			{#if showRunners}
				<div class="mt-3" transition:slide={{ duration: 220 }}>
					<RunnerStatus
						registry={meta?.registry ?? null}
						{checking}
						error={metaError}
						on:check={recheck}
					/>
				</div>
			{/if}

			<!-- quick starts -->
			<section class="tm-rise mt-6" style="--i:2" aria-label="快速开始">
				<div class="mb-2 flex items-center gap-2">
					<span class="tm-eyebrow">快速开始</span>
				</div>
				<ul class="grid grid-cols-2 gap-2 sm:grid-cols-4">
					{#each QUICK_STARTS as q}
						<li>
							<button
								type="button"
								class="quick tm-card-quiet tm-hover flex h-full w-full flex-col items-start gap-2 px-3 py-2.5 text-left"
								on:click={() => useQuickStart(q.text)}
								title={q.text}
							>
								<span class="quick-icon grid h-7 w-[3.25rem] shrink-0 place-items-center rounded-lg">
									<!-- the team's shape, not a generic icon: chain / fan-out / three-way check / draft ⇄ review -->
									<svg class="h-5 w-11" viewBox="0 0 44 20" fill="none" aria-hidden="true">
										{#if q.icon === 'research'}
											<path d="M7 10h30" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.3" />
											<circle cx="6" cy="10" r="3" fill="currentColor" />
											<circle cx="22" cy="10" r="3" fill="currentColor" fill-opacity="0.55" />
											<circle cx="38" cy="10" r="3" stroke="currentColor" stroke-width="1.4" fill="none" />
										{:else if q.icon === 'build'}
											<path d="M9 10C20 10 22 3.5 35 3.5M9 10h26M9 10c11 0 13 6.5 26 6.5" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.3" />
											<circle cx="6" cy="10" r="3" fill="currentColor" />
											<circle cx="38" cy="3.5" r="2.4" fill="currentColor" fill-opacity="0.55" />
											<circle cx="38" cy="10" r="2.4" fill="currentColor" fill-opacity="0.55" />
											<circle cx="38" cy="16.5" r="2.4" fill="currentColor" fill-opacity="0.55" />
										{:else if q.icon === 'review'}
											<path d="M8 10c7 0 7-6.5 14-6.5S29 10 36 10M8 10h28M8 10c7 0 7 6.5 14 6.5S29 10 36 10" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.3" />
											<circle cx="6" cy="10" r="2.6" fill="currentColor" fill-opacity="0.55" />
											<circle cx="22" cy="3.5" r="2.4" fill="currentColor" fill-opacity="0.55" />
											<circle cx="22" cy="10" r="2.4" fill="currentColor" fill-opacity="0.55" />
											<circle cx="22" cy="16.5" r="2.4" fill="currentColor" fill-opacity="0.55" />
											<circle cx="38" cy="10" r="3" fill="currentColor" />
										{:else}
											<path d="M14 7.5c4-3.5 12-3.5 16 0M30 12.5c-4 3.5-12 3.5-16 0" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.3" stroke-linecap="round" />
											<path d="m27.5 4.8 2.7 2.8-3.6 1" stroke="currentColor" stroke-opacity="0.6" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" />
											<circle cx="11" cy="10" r="3.2" fill="currentColor" />
											<circle cx="33" cy="10" r="3.2" stroke="currentColor" stroke-width="1.4" fill="none" />
										{/if}
									</svg>
								</span>
								<span class="flex flex-col gap-0.5">
									<span class="text-[13px] font-medium text-gray-800 dark:text-gray-100"
										>{q.title}</span
									>
									<span class="text-[11px] leading-snug text-gray-500 dark:text-gray-400"
										>{q.desc}</span
									>
								</span>
							</button>
						</li>
					{/each}
				</ul>
			</section>

			{#if chatId && chatTeams.length}
				<section class="mt-8" aria-label="这个对话的协作任务">
					<h3 class="mb-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
						这个对话的协作任务
					</h3>
					<ul class="flex flex-col gap-2">
						{#each chatTeams as team (team.id)}
							<li>
								<a
									href="/teams/{team.id}"
									class="tm-card tm-hover flex items-center gap-3 px-4 py-3"
								>
									<span class="min-w-0 flex-1 truncate text-sm font-medium">{team.title}</span>
									<StatusChip
										status={chipOf(statusOf(team))}
										label={PHASE_LABEL[statusOf(team)] ?? statusOf(team)}
									/>
									<span class="text-xs text-sky-700 dark:text-sky-300">打开 →</span>
								</a>
							</li>
						{/each}
					</ul>
				</section>
			{/if}

			<!-- the list -->
			<section class="mt-10" aria-label="我的协作任务">
				<div class="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2">
					<h3 class="tm-display text-base font-semibold text-gray-900 dark:text-gray-100">
						我的协作
					</h3>
					{#if teams.length}
						<span class="tm-num text-xs text-gray-400">{teams.length}</span>
					{/if}
					<label class="search ml-auto flex min-w-0 items-center gap-1.5 rounded-xl px-2.5 py-1.5">
						<svg
							class="size-3.5 shrink-0 text-gray-400"
							viewBox="0 0 16 16"
							fill="none"
							aria-hidden="true"
							><circle cx="7" cy="7" r="4.5" stroke="currentColor" stroke-width="1.5" /><path
								d="m10.5 10.5 3 3"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
							/></svg
						>
						<span class="sr-only">搜索协作任务</span>
						<input
							type="search"
							bind:value={query}
							placeholder="搜索标题或目标"
							class="w-36 min-w-0 bg-transparent text-xs outline-none placeholder:text-gray-400 sm:w-44"
						/>
					</label>
				</div>
				{#if teams.length}
					<div class="tm-scroll tm-fade-x mb-3 overflow-x-auto pb-1">
						<div class="tm-segment" role="tablist" aria-label="按状态筛选">
							{#each FILTERS as f}
								<button
									type="button"
									role="tab"
									aria-selected={filter === f.value}
									class="whitespace-nowrap"
									on:click={() => (filter = f.value)}
									data-filter={f.value}
									>{f.label}{#if counts[f.value]}<span class="tm-num ml-1 opacity-60"
											>{counts[f.value]}</span
										>{/if}</button
								>
							{/each}
						</div>
					</div>
				{/if}

				{#if !loaded}
					<ul class="flex flex-col gap-2" aria-busy="true">
						{#each [0, 1, 2] as i}
							<li class="skeleton tm-card-quiet h-[72px]" style="--i:{i}" />
						{/each}
					</ul>
				{:else if error}
					<div class="text-sm text-red-600" role="alert">{error}</div>
				{:else if teams.length === 0}
					<div class="tm-card-quiet flex flex-col gap-4 px-5 py-6" data-teams-empty>
						<div class="text-sm font-medium text-gray-800 dark:text-gray-100">
							还没有协作任务 · 三步走完一次
						</div>
						<ol class="grid gap-3 sm:grid-cols-3">
							{#each [['描述目标', '在上面写下要完成的事，或点一个快速开始'], ['批准计划', '负责人给出成员分工和任务依赖，你可以改执行来源或要求重做'], ['收结论', '成员并行执行、自动兜底，完成后负责人交付完整结果']] as [title, text], i}
								<li class="flex gap-3">
									<span
										class="tm-num grid size-6 shrink-0 place-items-center rounded-full border text-[11px] font-semibold text-gray-500 tm-hairline"
										>{i + 1}</span
									>
									<div>
										<div class="text-[13px] font-medium text-gray-800 dark:text-gray-100">
											{title}
										</div>
										<div class="text-xs leading-relaxed text-gray-500 dark:text-gray-400">
											{text}
										</div>
									</div>
								</li>
							{/each}
						</ol>
					</div>
				{:else if shown.length === 0}
					<div class="py-10 text-center text-sm text-gray-400">没有符合条件的协作任务</div>
				{:else}
					<ul class="flex flex-col gap-2" data-team-list>
						{#each shown as team, i (team.id)}
							{@const s = statusOf(team)}
							{@const bucket = bucketOf(team)}
							{@const p = team.progress}
							{@const total = p?.total || team.task_count || 0}
							{@const done = s === 'completed' ? total : (p?.done ?? 0)}
							{@const running = bucket === 'active' ? (p?.running ?? 0) : 0}
							{@const attention = bucket === 'active' ? (p?.attention ?? 0) : 0}
							<li
								class="row tm-card tm-hover tm-rise relative flex items-center gap-3 px-4 py-3 {bucket ===
									'active' && s !== 'paused'
									? 'tm-live'
									: ''}"
								style="--i:{Math.min(i, 8)}"
								data-team-row={team.id}
								data-bucket={bucket}
							>
								<a
									href="/teams/{team.id}"
									class="min-w-0 flex-1 after:absolute after:inset-0 after:rounded-[1.125rem] focus:outline-none focus-visible:after:ring-2 focus-visible:after:ring-sky-400"
								>
									<div class="flex min-w-0 items-center gap-2">
										<span
											class="min-w-0 truncate text-sm font-medium text-gray-900 dark:text-gray-100"
											>{team.title}</span
										>
									</div>
									{#if team.stage && LIST_STAGES.has(team.stage.key)}
										{@const st = team.stage}
										{@const etaText =
											st.key === 'approval'
												? st.after_approval
													? `批准后${formatEta(st.after_approval, st.after_approval_high)}出结果`
													: ''
												: etaSentence({ seconds: st.eta, high: st.eta_high, overtime: st.overtime }, st.at, $now)}
										<div
											class="mt-1 flex min-w-0 items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400"
											data-team-stage={st.key}
										>
											<span class="stage-label shrink-0 font-medium" data-tone={st.key}>{st.label ?? ''}</span>
											{#if st.now}
												<span aria-hidden="true">·</span>
												<span class="min-w-0 truncate text-gray-600 dark:text-gray-300">{st.now}</span>
											{/if}
											{#if etaText}
												<span aria-hidden="true">·</span>
												<span class="tm-num shrink-0" data-team-eta>{etaText.replace('预计', '')}</span>
											{/if}
										</div>
									{:else}
									<div
									class="mt-1 flex min-w-0 items-center gap-1.5 truncate text-xs text-gray-500 dark:text-gray-400"
									>
									<span class="shrink-0">{timeAgo(team.updated_at, $now)}</span>
										{#if team.origin === 'telegram'}
											<span aria-hidden="true">·</span>
											<span
												class="shrink-0 text-sky-600 dark:text-sky-400"
												title="在 Telegram 用 /team 发起，计划、提问和完成会推送到那里"
												data-team-origin="telegram">Telegram</span
											>
										{/if}
										{#if team.task_count}
											<span aria-hidden="true">·</span>
											<span class="shrink-0">{team.member_count} 位成员</span>
										{/if}
										{#if team.executors?.length}
											<span aria-hidden="true">·</span>
											<span class="truncate font-mono text-[11px]"
												>{team.executors.map(runnerLabel).join(' + ')}</span
												>
												{/if}
												</div>
												{/if}
												</a>
								<span
									class="hidden w-[7.5rem] shrink-0 items-center justify-end -space-x-1.5 md:flex"
									aria-hidden="true"
								>
									{#if team.roster?.length}
										<span class="stack"><TeamAvatar kind="lead" size={22} /></span>
										{#each team.roster.slice(0, 4) as m}
											<span class="stack"><TeamAvatar kind={avatarKind(m)} size={22} /></span>
										{/each}
										{#if team.roster.length > 4}
											<span
												class="stack tm-num grid size-[22px] place-items-center rounded-full bg-gray-100 text-[10px] text-gray-500 dark:bg-gray-800"
												>+{team.roster.length - 4}</span
											>
										{/if}
									{/if}
								</span>
								<span class="hidden w-20 shrink-0 sm:block">
									{#if total && (bucket === 'active' || bucket === 'done' || s === 'stopped')}
										<span
											class="flex flex-col gap-1"
											title="{done}/{total} 个任务完成{running
												? `，${running} 个执行中`
												: ''}{attention ? `，${attention} 个需要你处理` : ''}"
											data-team-bar
										>
											<span class="tm-num text-right text-[11px] text-gray-500"
												>{done}<span class="opacity-50">/{total}</span></span
											>
											<span
												class="flex h-1 gap-px overflow-hidden rounded-full bg-gray-900/[0.06] dark:bg-white/[0.08]"
											>
												<span
													class="h-full bg-gray-400 transition-[width] duration-700 dark:bg-gray-500"
													style="width:{Math.round((done / total) * 100)}%"
												/>
												{#if running}
													<span
														class="bar-run h-full transition-[width] duration-700"
														style="width:{Math.round((running / total) * 100)}%"
													/>
												{/if}
												{#if attention}
													<span
														class="h-full bg-violet-500 transition-[width] duration-700"
														style="width:{Math.round((attention / total) * 100)}%"
													/>
												{/if}
											</span>
										</span>
									{/if}
								</span>
								<span class="flex shrink-0 justify-end sm:w-[6.5rem]">
									<StatusChip status={chipOf(s)} label={PHASE_LABEL[s] ?? s} />
								</span>
								<span
									class="actions relative z-10 flex shrink-0 items-center justify-end gap-0.5 sm:w-[5.75rem]"
								>
									{#if s === 'completed' || s === 'stopped'}
										<a
											href="/teams/{team.id}/conclusion"
											class="icon-btn text-[hsl(var(--tm-accent))]"
											title="阅读结论"
											aria-label="阅读「{team.title}」的结论"
											><svg class="size-4" viewBox="0 0 16 16" fill="none" aria-hidden="true"
												><path
													d="M4 1.8h5.2L12.5 5v9.2H4V1.8Z"
													stroke="currentColor"
													stroke-width="1.4"
													stroke-linejoin="round"
												/><path
													d="M6 8h4.5M6 10.8h3"
													stroke="currentColor"
													stroke-width="1.4"
													stroke-linecap="round"
												/></svg
											></a
										>
									{/if}
									<button
										type="button"
										class="icon-btn reveal"
										title="用相同目标再发起一次"
										aria-label="用「{team.title}」的目标再发起一次"
										on:click={() => again(team)}
										><svg class="size-4" viewBox="0 0 16 16" fill="none" aria-hidden="true"
											><path
												d="M13 8a5 5 0 1 1-1.5-3.6M13 2.5v3h-3"
												stroke="currentColor"
												stroke-width="1.4"
												stroke-linecap="round"
												stroke-linejoin="round"
											/></svg
										></button
									>
									{#if team.deletable}
										<button
											type="button"
											class="icon-btn reveal hover:!text-red-600"
											title="删除"
											aria-label="删除「{team.title}」"
											on:click={() => askDelete(team)}
											data-delete-team
											><svg class="size-4" viewBox="0 0 16 16" fill="none" aria-hidden="true"
												><path
													d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.6c.05.8.7 1.4 1.5 1.4h2.8c.8 0 1.45-.6 1.5-1.4l.6-8.6"
													stroke="currentColor"
													stroke-width="1.4"
													stroke-linecap="round"
													stroke-linejoin="round"
												/></svg
											></button
										>
									{/if}
								</span>
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
	title="删除这个协作任务？"
	message={`「${pendingDelete?.title ?? ''}」会从你的列表里移除，计划、通讯记录入口和结论入口都不再显示。成员写在工作目录里的文件保留在 Hermes 上。`}
	confirmLabel="删除"
	on:confirm={confirmDelete}
/>

<style>
	.stage-label {
		color: hsl(214 90% 44%);
	}
	.stage-label[data-tone='attention'] {
		color: hsl(262 70% 52%);
	}
	.stage-label[data-tone='approval'],
	.stage-label[data-tone='paused'] {
		color: hsl(30 90% 38%);
	}
	:global(.dark) .stage-label {
		color: hsl(var(--tm-accent));
	}
	:global(.dark) .stage-label[data-tone='attention'] {
		color: hsl(var(--tm-violet));
	}
	:global(.dark) .stage-label[data-tone='approval'],
	:global(.dark) .stage-label[data-tone='paused'] {
		color: hsl(var(--tm-warn));
	}
	/* Tasks running now: a blue segment with light flowing through it. */
	.bar-run {
		background:
			linear-gradient(90deg, transparent 0%, hsl(0 0% 100% / 0.55) 50%, transparent 100%) 0 0 / 200%
				100%,
			rgb(14 165 233);
		animation: bar-run 1.6s linear infinite;
	}
	@keyframes bar-run {
		from {
			background-position:
				150% 0,
				0 0;
		}
		to {
			background-position:
				-50% 0,
				0 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.bar-run {
			animation: none;
		}
	}
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
	.pill {
		border: 1px solid hsl(var(--tm-line));
		background: hsl(var(--tm-surface-2));
		transition:
			border-color 0.15s ease,
			background 0.15s ease;
	}
	.pill:hover {
		border-color: hsl(var(--tm-line-strong));
	}
	.pill-on {
		color: hsl(var(--tm-accent));
		border-color: hsl(var(--tm-accent) / 0.4);
		background: hsl(var(--tm-accent) / 0.1);
	}
	/* The app's global `select` rule (unlayered) outranks Tailwind's utilities: size these here. */
	.compact-select {
		font-size: 0.75rem;
		line-height: 1rem;
		padding: 0.15rem 1.5rem 0.15rem 0.2rem;
		background-color: transparent;
		background-size: 1em 1em;
		border: 0;
		color: inherit;
		box-shadow: none;
		font-weight: 500;
	}
	.quick-icon {
		color: hsl(var(--tm-accent));
		background: hsl(var(--tm-accent) / 0.09);
		box-shadow: inset 0 0 0 1px hsl(var(--tm-accent) / 0.14);
	}
	.search {
		border: 1px solid hsl(var(--tm-line));
		background: hsl(var(--tm-surface) / 0.7);
	}
	.search:focus-within {
		border-color: hsl(var(--tm-accent) / 0.45);
	}
	.stack {
		border-radius: 9999px;
		box-shadow: 0 0 0 2px hsl(var(--tm-surface));
	}
	.icon-btn {
		display: grid;
		place-items: center;
		width: 1.85rem;
		height: 1.85rem;
		border-radius: 0.6rem;
		color: hsl(var(--tm-muted));
		transition:
			background 0.15s ease,
			color 0.15s ease,
			opacity 0.2s ease;
	}
	.icon-btn:hover {
		background: hsl(var(--tm-line));
		color: hsl(var(--tm-ink));
	}
	@media (hover: hover) {
		.row .actions .reveal {
			opacity: 0;
		}
		.row:hover .actions .reveal,
		.row:focus-within .actions .reveal {
			opacity: 1;
		}
	}
	.skeleton {
		position: relative;
		overflow: hidden;
	}
	.skeleton::after {
		content: '';
		position: absolute;
		inset: 0;
		background: linear-gradient(90deg, transparent, hsl(var(--tm-line)), transparent);
		animation: skeleton 1.4s ease-in-out infinite;
		animation-delay: calc(var(--i) * 120ms);
	}
	@keyframes skeleton {
		from {
			transform: translateX(-100%);
		}
		to {
			transform: translateX(100%);
		}
	}
</style>
