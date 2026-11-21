<script lang="ts">
	import { afterUpdate, onDestroy, onMount, tick } from 'svelte';
	import { goto, replaceState } from '$app/navigation';
	import { v4 as uuidv4 } from 'uuid';
	import { config, mobile, showSidebar } from '$lib/stores';
	import {
		createAutoRoute,
		getAutoRoute,
		listAutoRoutes,
		cancelAutoRoute,
		MODE_LABEL,
		routePending,
		routeStatus,
		routeTarget,
		type AutoInput,
		type AutoRoute
	} from '$lib/apis/auto';
	import { uploadFileReliably, uploadErrorText } from '$lib/utils/reliable-upload';
	import { takeHandoff, type HandoffOrigin } from '$lib/utils/handoff';
	import { setModeDraft, clearModeDraft } from '$lib/components/scifi/mode-relay';
	import { warp } from '$lib/components/scifi/scifi';
	import ModeEmblem from '$lib/components/scifi/ModeEmblem.svelte';
	import ModeFlow from '$lib/components/scifi/ModeFlow.svelte';
	import ModeDock from '$lib/components/scifi/ModeDock.svelte';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import HandoffBack from '$lib/components/common/HandoffBack.svelte';
	import '$lib/components/teams/teams.css';
	import '$lib/components/discuss/discuss.css';

	type Attachment = {
		key: string;
		id?: string;
		name: string;
		type: 'file' | 'image';
		progress: number;
		error?: string;
	};
	const DRAFT_KEY = 'halo.auto.draft';
	let question = '';
	let context = '';
	let origin: HandoffOrigin | null = null;
	let research = true;
	let preference: AutoInput['preference'] = 'standard';
	let mode: AutoInput['mode'] = 'auto';
	let autoStart = false;
	let attachments: Attachment[] = [];
	let fileInput: HTMLInputElement;
	let composer: HTMLTextAreaElement;
	let isMac = false;
	let active: AutoRoute | null = null;
	let items: AutoRoute[] = [];
	let more = false;
	let next: string | null = null;
	let pages: (string | null)[] = [null];
	let pageIndex = 0;
	let search = '';
	let historyMode = '';
	let historyQuery = { q: '', mode: '' };
	let loading = false;
	let submitting = false;
	let error = '';
	let historyError = '';
	let ready = false;
	let destroyed = false;
	let follow = false;
	let timer: ReturnType<typeof setTimeout> | undefined;
	let attempt: { payload: string; key: string } | null = null;
	$: uploading = attachments.some((f) => !f.id && !f.error);
	$: busy = submitting || (!!active && routePending(active));
	$: teamsEnabled = !!$config?.features?.enable_agent_teams;
	$: webEnabled = $config?.features?.enable_web_search !== false;
	$: failedUpload = attachments.some((f) => f.error);

	const QUICK = [
		{
			badge: '精答型',
			title: '精准拆解复杂问题',
			hint: '挑最合适专家直接答透',
			text: '帮我逐条审查这份 SaaS 采购合同里的隐藏风险、自动续费陷阱和违约责任条款，并给出可谈判的修改建议。'
		},
		{
			badge: '讨论型',
			title: '多方权衡技术选型',
			hint: '多模型交锋并汇总共识',
			text: '我们是一个 6 人全栈团队，准备做一套内部知识库与自动化工作流平台，从长期维护成本、扩展性和 AI 集成角度权衡自建还是基于开源方案二开。'
		},
		{
			badge: '协作型',
			title: '调研并交付完整成果',
			hint: '拆计划、并行执行与验收',
			text: '调研当前主流的三款开源向量数据库（Qdrant、Milvus、pgvector），从部署资源占用、召回精度和运维复杂度整理一份结构化对比报告。'
		}
	];

	const HISTORY_MODES = [
		{ value: '', label: '全部' },
		{ value: 'answer', label: '精答' },
		{ value: 'discuss', label: '讨论' },
		{ value: 'team', label: '协作' }
	] as const;

	const modeTone = (m: string | null | undefined) =>
		m === 'answer'
			? 'bg-cyan-500/12 text-cyan-700 dark:bg-cyan-400/15 dark:text-cyan-300'
			: m === 'discuss'
				? 'bg-violet-500/12 text-violet-700 dark:bg-violet-400/15 dark:text-violet-300'
				: m === 'team'
					? 'bg-emerald-500/12 text-emerald-700 dark:bg-emerald-400/15 dark:text-emerald-300'
					: 'bg-gray-500/10 text-gray-600 dark:text-gray-300';

	const resize = () => {
		if (!composer) return;
		composer.style.height = 'auto';
		composer.style.height = `${Math.min(composer.scrollHeight, 320)}px`;
	};

	const useQuick = async (text: string) => {
		question = text;
		await tick();
		resize();
		composer?.focus();
	};

	function draft() {
		return {
			question,
			context,
			research,
			preference,
			mode,
			autoStart,
			origin,
			attachments: attachments.filter((f) => f.id),
			attempt
		};
	}
	afterUpdate(() => {
		setModeDraft('auto', question, {
			context,
			from: origin,
			files: attachments.filter((f) => f.id).map((f) => ({ id: f.id!, name: f.name, type: f.type }))
		});
		if (ready) {
			try {
				sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft()));
			} catch {}
		}
	});

	async function attach(files: FileList | File[] | null) {
		if (busy) return;
		const added = Array.from(files ?? []).slice(0, 4 - attachments.length);
		if (Array.from(files ?? []).length > added.length) error = '最多携带 4 个附件';
		// Register the whole batch first; upload sequentially to bound memory and requests.
		const pending = added.map((f) => ({
			key: uuidv4(),
			name: f.name,
			type: f.type.startsWith('image/') ? ('image' as const) : ('file' as const),
			progress: 0
		}));
		attachments = [...attachments, ...pending];
		for (let i = 0; i < added.length; i++) {
			const item: Attachment = pending[i];
			try {
				const { file } = await uploadFileReliably(localStorage.token, added[i], {
					...(item.type === 'image' ? { process: false } : {}),
					onProgress: ({ percent }) => {
						item.progress = percent;
						attachments = [...attachments];
					}
				});
				if (!file?.id) throw new Error('上传失败');
				item.id = file.id;
			} catch (e: any) {
				item.error = uploadErrorText(e);
			}
			attachments = [...attachments];
		}
	}

	async function loadHistory(index = 0, reset = false) {
		if (loading) return;
		loading = true;
		const query = reset ? { q: search, mode: historyMode } : historyQuery;
		try {
			const before = reset ? null : pages[index];
			const res = await listAutoRoutes(localStorage.token, { ...query, before });
			if (destroyed) return;
			items = res.items;
			more = res.more;
			next = res.next;
			pageIndex = index;
			historyQuery = query;
			if (reset) pages = [null];
			historyError = '';
		} catch (e: any) {
			historyError = e.message || '历史读取失败';
		} finally {
			loading = false;
		}
	}
	function nextPage() {
		if (!next || loading) return;
		pages = [...pages.slice(0, pageIndex + 1), next];
		loadHistory(pageIndex + 1);
	}

	async function poll() {
		clearTimeout(timer);
		if (!active || destroyed) return;
		try {
			active = await getAutoRoute(localStorage.token, active.id);
			error = '';
			if (
				active.status === 'dispatched' &&
				active.href &&
				follow &&
				active.target_status !== 'deleted'
			) {
				follow = false;
				await goto(active.href);
				return;
			}
			if (!routePending(active)) {
				await loadHistory();
				return;
			}
		} catch (e: any) {
			error = e.message || '连接暂时中断，正在恢复';
		}
		if (!destroyed) timer = setTimeout(poll, document.hidden ? 15000 : 1800);
	}

	async function start() {
		if (busy || uploading || failedUpload || !question.trim()) return;
		submitting = true;
		error = '';
		const input = {
			question: question.trim(),
			context,
			files: attachments.filter((f) => f.id).map((f) => f.id!),
			research: webEnabled && research,
			preference,
			mode,
			auto_start: teamsEnabled && autoStart
		};
		const payload = JSON.stringify(input);
		if (attempt?.payload !== payload) attempt = { payload, key: uuidv4() };
		try {
			// Persist the key before the request, including when the response is lost.
			sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft()));
		} catch {}
		try {
			active = await createAutoRoute(localStorage.token, { ...input, client_key: attempt.key });
			follow = true;
			replaceState(`/auto?request=${encodeURIComponent(active.id)}`, {});
			await poll();
		} catch (e: any) {
			error = `${e.message || '连接失败'}；再次提交会复用本次请求`;
		} finally {
			submitting = false;
		}
	}
	async function cancel() {
		if (!active) return;
		try {
			active = await cancelAutoRoute(localStorage.token, active.id);
			follow = false;
			await loadHistory();
		} catch (e: any) {
			error = e.message;
		}
	}
	function reset() {
		active = null;
		attempt = null;
		error = '';
		follow = false;
		clearTimeout(timer);
		replaceState('/auto', {});
	}

	onMount(() => {
		try {
			const saved = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || 'null');
			if (saved) {
				question = typeof saved.question === 'string' ? saved.question.slice(0, 8000) : '';
				context = typeof saved.context === 'string' ? saved.context.slice(0, 12000) : '';
				research = saved.research !== false;
				preference = saved.preference === 'economy' ? 'economy' : 'standard';
				mode = ['auto', 'answer', 'discuss', 'team'].includes(saved.mode) ? saved.mode : 'auto';
				autoStart = saved.autoStart === true;
				attachments = Array.isArray(saved.attachments)
					? saved.attachments.filter((f: any) => f.id).slice(0, 4)
					: [];
				origin = saved.origin ?? null;
				attempt = saved.attempt ?? null;
			}
		} catch {}
		const incoming = takeHandoff(sessionStorage, 'auto');
		if (incoming) {
			question = incoming.text;
			context = incoming.context;
			origin = incoming.from;
			attempt = null;
			attachments = incoming.files.map((f) => ({ ...f, key: uuidv4(), progress: 100 }));
		}
		ready = true;
		isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
		warp(520);
		loadHistory();
		tick().then(resize);
		const id = new URLSearchParams(window.location.search).get('request');
		if (id) {
			getAutoRoute(localStorage.token, id)
				.then((row) => {
					if (destroyed) return;
					active = row;
					follow = routePending(row);
					poll();
				})
				.catch((e) => (error = e.message));
		}
	});
	onDestroy(() => {
		destroyed = true;
		clearTimeout(timer);
		clearModeDraft('auto');
	});
</script>

<div
	class="tm-ambient relative flex h-screen max-h-[100dvh] w-full flex-col"
	data-teams-ui
	data-discuss-ui
	data-auto-home
>
	<nav class="halo-mode-nav flex flex-wrap items-center gap-2 px-3 py-2">
		{#if $mobile}<button
				class="rounded-xl p-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
				aria-label="打开侧栏"
				on:click={() => showSidebar.set(!$showSidebar)}><MenuLines /></button
			>{/if}
		<h1 class="sr-only">自动分流工作台</h1>
		<ModeDock current="auto" />
		{#if origin}<HandoffBack {origin} />{/if}
	</nav>
	<div class="tm-scroll flex-1 overflow-y-auto px-4 pb-16">
		<div class="mx-auto flex max-w-3xl flex-col pt-3 sm:pt-7">
			<header class="halo-mode-hero tm-rise relative mb-4 flex flex-col gap-2.5">
				<ModeEmblem mode="auto" stats={[{ k: 'ROUTES', v: teamsEnabled ? 3 : 2 }]} />
				<div class="flex items-center gap-2">
					<span class="tm-eyebrow halo-mode-eyebrow">Halo Auto</span><span
						class="h-3 w-px bg-gray-300 dark:bg-gray-700"
						aria-hidden="true"
					/><span class="text-xs text-gray-500 dark:text-gray-400">按目标智能分流</span>
				</div>
				<h2
					class="halo-mode-title tm-display text-[26px] font-semibold leading-[1.15] text-gray-950 sm:text-[32px] dark:text-white"
				>
					一个入口，找到合适的解法
				</h2>
				<ModeFlow
					label="自动分流怎么处理"
					steps={['理解目标与约束', '精答 · 讨论 · 协作', '查看结果，接着追问']}
				/>
				<p class="hidden max-w-xl text-xs leading-relaxed text-gray-500 sm:block dark:text-gray-400">
					直接提问交给精答；多方权衡展开讨论；动手交付交给协作台，依据与进度全程可查。
				</p>
			</header>
			<form
				class="tm-rise composer tm-card relative flex flex-col"
				style="--i:1"
				data-scifi-conduit
				on:submit|preventDefault={start}
				on:dragover|preventDefault
				on:drop|preventDefault={(e) => attach(e.dataTransfer?.files ?? null)}
			>
				<textarea
					bind:this={composer}
					aria-label="问题或任务"
					maxlength="8000"
					rows="3"
					bind:value={question}
					disabled={busy}
					on:input={resize}
					class="tm-scroll w-full resize-none rounded-t-2xl bg-transparent px-5 pt-4 pb-2 text-[15px] leading-relaxed text-gray-900 outline-none placeholder:text-gray-400 dark:text-gray-100 dark:placeholder:text-gray-500"
					placeholder="你想了解什么，或希望完成什么？附件可以粘贴或拖进来"
					on:paste={(e) => {
						if (e.clipboardData?.files.length) {
							e.preventDefault();
							attach(e.clipboardData.files);
						}
					}}
					on:keydown={(e) => {
						if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
							e.preventDefault();
							start();
						}
					}}
				/>
				{#if attachments.length}<ul
						class="flex list-none flex-wrap gap-2 px-5 pb-3"
						aria-label="附件"
						data-auto-attachments
					>
						{#each attachments as file (file.key)}<li
								class="dc-chip relative max-w-[16rem] !pr-1 {file.error
									? '!border-red-300 !text-red-600 dark:!border-red-500/40 dark:!text-red-400'
									: ''}"
								title={file.error || file.name}
							>
								<span class="truncate">{file.name}</span>
								{#if file.error}<span class="shrink-0">· 上传失败</span>
								{:else if !file.id}<span class="tm-num shrink-0 text-gray-400"
										>{file.progress < 100 ? `${file.progress}%` : '处理中'}</span
									>{/if}
								<button
									type="button"
									class="grid size-5 shrink-0 place-items-center rounded-full hover:bg-gray-500/15 disabled:opacity-40"
									aria-label={`移除 ${file.name}`}
									disabled={busy || (!file.id && !file.error)}
									on:click={() => (attachments = attachments.filter((f) => f.key !== file.key))}
									>×</button
								>
							</li>{/each}
					</ul>{/if}
				<div
					class="flex flex-wrap items-center gap-2 border-t border-gray-100 px-4 py-3 dark:border-gray-800/70"
				>
					<input
						type="file"
						multiple
						bind:this={fileInput}
						class="hidden"
						on:change={(e) => {
							attach(e.currentTarget.files);
							e.currentTarget.value = '';
						}}
					/>
					<button
						type="button"
						class="dc-chip"
						title="附带文件或图片，也可以粘贴或拖进来（最多 4 个）"
						disabled={busy || uploading || attachments.length >= 4}
						on:click={() => fileInput.click()}
						><svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
							><path
								d="M10.5 4.5 5.4 9.6a1.6 1.6 0 0 0 2.3 2.3l5.2-5.2a3 3 0 0 0-4.3-4.3L3.4 7.6a4.4 4.4 0 0 0 6.2 6.2l4-4"
								stroke="currentColor"
								stroke-width="1.3"
								stroke-linecap="round"
								stroke-linejoin="round"
							/></svg
						>附件{attachments.length ? ` ${attachments.length}/4` : ''}</button
					>
					<label
						class="dc-chip !py-1 !pr-1.5"
						data-on={mode !== 'auto'}
						title="自动选择，或直接指定交给谁"
						><span>交给</span><select
							aria-label="处理方式"
							bind:value={mode}
							disabled={busy}
							class="dc-select"
						>
							<option value="auto">自动选择</option><option value="answer">精答</option><option
								value="discuss">讨论</option
							>{#if teamsEnabled}<option value="team">协作台</option>{/if}
						</select></label
					>
					{#if webEnabled}<button
							type="button"
							class="dc-chip"
							aria-pressed={research}
							title="需要最新信息时先查资料；关掉则只凭模型自己的知识，协作任务也会带上不联网的要求"
							disabled={busy}
							on:click={() => (research = !research)}
							><svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
								><circle cx="8" cy="8" r="6.2" stroke="currentColor" stroke-width="1.3" /><path
									d="M1.8 8h12.4M8 1.8c1.8 2 1.8 10.4 0 12.4M8 1.8c-1.8 2-1.8 10.4 0 12.4"
									stroke="currentColor"
									stroke-width="1.1"
								/></svg
							>按需联网</button
						>{/if}
					{#if question.trim() && !busy}
						<button
							type="button"
							class="dc-chip"
							on:click={() => {
								question = '';
								tick().then(() => {
									resize();
									composer?.focus();
								});
							}}>清空</button
						>
					{/if}
					<div class="ml-auto flex items-center gap-2">
						<kbd
							class="hidden rounded-md px-1.5 py-0.5 font-mono text-[11px] text-gray-400 sm:inline-block"
							>{isMac ? '⌘' : 'Ctrl'} ↵</kbd
						>
						<button
							type="submit"
							class="tm-btn-primary"
							disabled={busy || uploading || failedUpload || !question.trim()}
							>{#if busy}<span
									class="size-3.5 animate-spin rounded-full border-2 border-current border-r-transparent"
									aria-hidden="true"
								/>正在处理…{:else}开始处理<svg
									class="size-3.5"
									viewBox="0 0 16 16"
									fill="none"
									aria-hidden="true"
									><path
										d="M3 8h9.5M8.5 4l4 4-4 4"
										stroke="currentColor"
										stroke-width="1.7"
										stroke-linecap="round"
										stroke-linejoin="round"
									/></svg
								>{/if}</button
						>
					</div>
				</div>
			</form>
			<details class="auto-more group mt-2.5 text-sm text-gray-600 dark:text-gray-400" data-auto-more>
				<summary
					class="inline-flex cursor-pointer select-none items-center gap-1.5 rounded-lg px-1 py-1 text-xs font-medium text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200"
				>
					<svg
						class="size-3 transition-transform group-open:rotate-90"
						viewBox="0 0 12 12"
						fill="none"
						aria-hidden="true"
						><path
							d="m4.5 3 3 3-3 3"
							stroke="currentColor"
							stroke-width="1.5"
							stroke-linecap="round"
							stroke-linejoin="round"
						/></svg
					>
					更多设置：讨论席位、协作启动、补充背景{preference === 'economy'
						? ' · 精简 2 席'
						: ''}{autoStart ? ' · 直接开始' : ''}{context ? ' · 已带入背景' : ''}
				</summary>
				<div class="tm-card-quiet mt-2 flex flex-col gap-3 p-4">
					<div class="flex flex-wrap items-center gap-2">
						<label class="dc-chip !py-1 !pr-1.5"
							><span>讨论席位</span><select
								aria-label="讨论预算"
								bind:value={preference}
								disabled={busy}
								class="dc-select"
								><option value="standard">标准 · 最多 3 个</option><option value="economy"
									>精简 · 2 个</option
								></select
							></label
						>
						{#if teamsEnabled}<button
								type="button"
								class="dc-chip"
								aria-pressed={autoStart}
								title="协作计划出来后不等批准直接开始（每位成员都有可用执行者时）"
								disabled={busy}
								on:click={() => (autoStart = !autoStart)}>协作计划后直接开始</button
							>{/if}
					</div>
					<p class="text-xs leading-5 text-gray-500 dark:text-gray-400">
						讨论进行一轮并汇总结论；协作默认先出计划，等你批准再开始。「只分析、不执行」等要求优先于自动选择。
					</p>
					<textarea
						aria-label="背景信息"
						bind:value={context}
						disabled={busy}
						maxlength="12000"
						rows="3"
						placeholder="可选：补充背景、约束和已有结论"
						class="w-full resize-y rounded-xl border border-gray-200 bg-transparent p-3 text-sm outline-none transition focus:border-sky-400 dark:border-gray-700"
					/>
				</div>
			</details>
			{#if error}<p role="alert" class="mt-4 text-sm text-red-500">{error}</p>{/if}
			{#if active}<section
					class="tm-card mt-5 p-5 {routePending(active) ? 'tm-live' : ''}"
					aria-live="polite"
					data-auto-active
				>
					<div class="flex flex-wrap items-center justify-between gap-2">
						<strong class="text-sm font-semibold text-gray-900 dark:text-gray-100"
							>{active.mode ? `自动分流 → ${routeTarget(active)}` : '正在选择处理方式'}</strong
						><span class="flex items-center gap-2"
							>{#if active.degraded}<span
									class="rounded-full bg-amber-500/10 px-2 py-0.5 text-xs text-amber-700 dark:text-amber-400"
									data-auto-degraded>临时改用</span
								>{/if}<span
								class="rounded-full px-2 py-0.5 text-xs {active.blocked
									? 'bg-amber-500/10 text-amber-700 dark:text-amber-400'
									: active.status === 'error' || active.status === 'interrupted'
										? 'bg-red-500/10 text-red-600 dark:text-red-400'
										: 'bg-cyan-500/10 text-cyan-700 dark:text-cyan-300'}"
								>{routeStatus(active)}</span
							></span
						>
					</div>
					<p
						class="mt-2 text-sm leading-relaxed text-gray-600 dark:text-gray-300 {routePending(
							active
						) && !active.reason
							? 'tm-shimmer'
							: ''}"
					>
						{active.reason || '正在理解你的目标，选择合适的处理方式…'}
					</p>
					{#if active.error}<p class="mt-2 text-sm text-red-500">{active.error}</p>{/if}
					<div class="mt-4 flex flex-wrap items-center gap-2">
						{#if active.href && active.target_status !== 'deleted'}<a
								href={active.href}
								class="tm-btn-primary !px-3 !py-1.5 !text-xs"
								>打开{active.mode ? MODE_LABEL[active.mode] : '任务'} →</a
							>{/if}
						{#if active.status === 'routing'}<button class="tm-btn-ghost !text-xs" on:click={cancel}
								>取消分流</button
							>{/if}
						{#if !routePending(active)}<button class="tm-btn-ghost !text-xs" on:click={reset}
								>开始另一次分流</button
							>{/if}
					</div>
				</section>{/if}
			{#if !active}
				<section class="tm-rise mt-5" style="--i:2" aria-label="试一试" data-auto-quick>
					<div class="mb-2"><span class="tm-eyebrow">典型场景</span></div>
					<ul class="grid grid-cols-1 gap-2 sm:grid-cols-3">
						{#each QUICK as q}
							<li>
								<button
									type="button"
									class="tm-card-quiet tm-hover flex h-full w-full flex-col items-start gap-1 px-3.5 py-2.5 text-left"
									disabled={busy}
									on:click={() => useQuick(q.text)}
									title={q.text}
								>
									<span class="flex w-full items-center justify-between gap-2">
										<span class="text-[13px] font-medium text-gray-900 dark:text-gray-100">{q.title}</span>
										<span class="shrink-0 rounded-full bg-cyan-500/10 px-1.5 py-0.5 text-[10px] font-medium text-cyan-700 dark:text-cyan-300">{q.badge}</span>
									</span>
									<span class="text-[11.5px] text-gray-500 dark:text-gray-400">{q.hint}</span>
								</button>
							</li>
						{/each}
					</ul>
				</section>
			{/if}
			<section class="tm-rise mt-8 pb-8" style="--i:3">
				<div class="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2">
					<h2 class="tm-display text-base font-semibold text-gray-900 dark:text-gray-50">最近处理</h2>
					<div class="tm-segment" role="tablist" aria-label="按处理方式筛选">
						{#each HISTORY_MODES as hm}
							<button
								type="button"
								role="tab"
								aria-selected={historyMode === hm.value}
								disabled={loading}
								on:click={() => {
									historyMode = hm.value;
									loadHistory(0, true);
								}}>{hm.label}</button
							>
						{/each}
					</div>
					<form
						class="ml-auto flex min-w-0 flex-1 items-center justify-end gap-2 sm:flex-initial"
						on:submit|preventDefault={() => loadHistory(0, true)}
					>
						<label class="halo-wb-search min-w-0 flex-1 sm:w-52 sm:flex-initial">
							<svg class="size-3.5 shrink-0 text-gray-400" viewBox="0 0 16 16" fill="none" aria-hidden="true"
								><circle cx="7" cy="7" r="4.5" stroke="currentColor" stroke-width="1.5" /><path
									d="m10.5 10.5 3 3"
									stroke="currentColor"
									stroke-width="1.5"
									stroke-linecap="round"
								/></svg
							>
							<input
								aria-label="搜索处理记录"
								bind:value={search}
								maxlength="200"
								placeholder="搜索问题或任务"
								class="w-full min-w-0 bg-transparent text-xs outline-none placeholder:text-gray-400"
								disabled={loading}
							/>
						</label>
						<button type="submit" class="tm-btn-ghost shrink-0" disabled={loading}>搜索</button>
						<button
							type="button"
							class="tm-btn-ghost shrink-0"
							disabled={loading}
							on:click={() => loadHistory(0, true)}>刷新</button
						>
					</form>
				</div>
				{#if historyError}<p role="alert" class="mt-3 text-sm text-red-500">{historyError}</p>{/if}
				{#if !items.length && !loading}<p class="mt-6 text-center text-sm text-gray-400">
						{historyQuery.q || historyQuery.mode
							? '没有匹配的处理记录。'
							: '提交第一个问题，处理记录会保存在这里。'}
					</p>{/if}
				<ul class="mt-3 flex flex-col gap-2">
					{#each items as row (row.id)}
						{@const live = routePending(row)}
						{@const isErr = ['error', 'interrupted', 'failed', 'plan_failed'].includes(
							row.status === 'dispatched' ? (row.target_status ?? '') : row.status
						)}
						<li
							class="tm-card tm-hover relative {live ? 'tm-live' : ''}"
							data-auto-row={row.id}
						>
							<a
								href={row.target_status === 'deleted'
									? `/auto?request=${row.id}`
									: row.href || `/auto?request=${row.id}`}
								class="flex flex-wrap items-center gap-3 px-4 py-3"
								on:click={(e) => {
									if (!row.href || row.target_status === 'deleted') {
										e.preventDefault();
										active = row;
										follow = false;
										replaceState(`/auto?request=${row.id}`, {});
										poll();
									}
								}}
							>
								<span class="min-w-0 flex-1"
									><span class="block truncate text-[14px] font-medium text-gray-900 dark:text-gray-100"
										>{row.title || row.question}</span
									><span class="mt-0.5 block truncate text-xs text-gray-500 dark:text-gray-400"
										>{row.reason || row.question}</span
									></span
								>
								<span
									class="shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-medium {modeTone(row.mode)}"
									>{row.mode ? MODE_LABEL[row.mode] : '分流中'}</span
								>
								<span
									class="min-w-[3.75rem] shrink-0 text-right text-xs {isErr
										? 'text-red-500'
										: live
											? 'text-cyan-600 dark:text-cyan-300'
											: 'text-gray-400'}">{routeStatus(row)}</span
								>
							</a>
						</li>
					{/each}
				</ul>
				{#if pageIndex > 0 || more}
					<div class="mt-4 flex items-center justify-between gap-3" aria-label="历史分页">
						<button
							class="tm-btn-ghost"
							disabled={loading || pageIndex === 0}
							on:click={() => loadHistory(pageIndex - 1)}>上一页</button
						>
						<span class="text-xs text-gray-500">第 {pageIndex + 1} 页 · 每页最多 30 条</span>
						<button class="tm-btn-ghost" disabled={loading || !more || !next} on:click={nextPage}
							>下一页</button
						>
					</div>
				{/if}
			</section>
		</div>
	</div>
</div>

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
	/* the disclosure draws its own chevron */
	.auto-more > summary {
		list-style: none;
	}
	.auto-more > summary::-webkit-details-marker {
		display: none;
	}
</style>
