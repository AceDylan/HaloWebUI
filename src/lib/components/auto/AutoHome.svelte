<script lang="ts">
	import { afterUpdate, onDestroy, onMount } from 'svelte';
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
		type AutoInput,
		type AutoRoute
	} from '$lib/apis/auto';
	import { uploadFileReliably, uploadErrorText } from '$lib/utils/reliable-upload';
	import { takeHandoff, type HandoffOrigin } from '$lib/utils/handoff';
	import { setModeDraft, clearModeDraft } from '$lib/components/scifi/mode-relay';
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
		loadHistory();
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
	<nav class="flex flex-wrap items-center gap-2 px-3 pt-2 pb-1">
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
		<div class="mx-auto flex max-w-3xl flex-col pt-6 sm:pt-14">
			<header class="halo-mode-hero tm-rise relative mb-6 flex flex-col gap-3">
				<ModeEmblem mode="auto" stats={[{ k: 'ROUTES', v: teamsEnabled ? 3 : 2 }]} />
				<div class="flex items-center gap-2">
					<span class="tm-eyebrow halo-mode-eyebrow">Halo Auto</span><span
						class="h-3 w-px bg-gray-300 dark:bg-gray-700"
						aria-hidden="true"
					/><span class="text-xs text-gray-500">按目标选择处理方式</span>
				</div>
				<h2
					class="halo-mode-title tm-display text-[28px] font-semibold leading-[1.15] text-gray-950 sm:text-[36px] dark:text-white"
				>
					一个入口，找到合适的解法
				</h2>
				<ModeFlow
					label="自动分流怎么处理"
					steps={['理解目标与约束', '精答 · 讨论 · 协作', '查看结果，接着追问']}
				/>
				<p class="max-w-xl text-sm leading-relaxed text-gray-500 dark:text-gray-400">
					直接提问交给精答；需要多方权衡就展开讨论；需要动手完成任务则交给协作台。选择依据和处理进度都能查看。
				</p>
			</header>
			<form
				class="tm-rise tm-card relative flex flex-col"
				data-scifi-conduit
				on:submit|preventDefault={start}
				on:dragover|preventDefault
				on:drop|preventDefault={(e) => attach(e.dataTransfer?.files ?? null)}
			>
				<textarea
					aria-label="问题或任务"
					maxlength="8000"
					rows="5"
					bind:value={question}
					disabled={busy}
					class="w-full resize-none rounded-t-2xl bg-transparent px-5 pt-5 pb-3 text-base leading-relaxed outline-none"
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
						>附件{attachments.length ? ` ${attachments.length}/4` : ''}</button
					>
					<label class="dc-chip !py-1 !pr-1.5" title="自动选择，或直接指定交给谁"
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
							on:click={() => (research = !research)}>按需联网</button
						>{/if}
					<div class="ml-auto flex items-center gap-2">
						<kbd
							class="hidden rounded-md px-1.5 py-0.5 font-mono text-[11px] text-gray-400 sm:inline-block"
							>Ctrl ↵</kbd
						>
						<button
							type="submit"
							class="tm-btn-primary"
							disabled={busy || uploading || failedUpload || !question.trim()}
							>{busy ? '正在处理…' : '开始处理'}</button
						>
					</div>
				</div>
			</form>
			<details class="auto-more group mt-3 text-sm text-gray-600 dark:text-gray-400" data-auto-more>
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
					更多设置：讨论席位、协作启动、补充背景{context ? ' · 已带入背景' : ''}
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
					class="tm-card mt-6 p-5 {routePending(active) ? 'tm-live' : ''}"
					aria-live="polite"
					data-auto-active
				>
					<div class="flex flex-wrap items-center justify-between gap-2">
						<strong class="text-sm font-semibold text-gray-900 dark:text-gray-100"
							>{active.mode ? `自动分流 → ${MODE_LABEL[active.mode]}` : '正在选择处理方式'}</strong
						><span
							class="rounded-full px-2 py-0.5 text-xs {active.status === 'error' ||
							active.status === 'interrupted'
								? 'bg-red-500/10 text-red-600 dark:text-red-400'
								: 'bg-gray-500/10 text-gray-600 dark:text-gray-300'}">{routeStatus(active)}</span
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
			<section class="mt-10 pb-8">
				<div class="flex items-center justify-between">
					<h2 class="text-base font-semibold">最近处理</h2>
					<button
						class="rounded-lg px-2 py-1 text-xs text-gray-500 hover:bg-gray-500/10 hover:text-gray-800 disabled:opacity-50 dark:hover:text-gray-200"
						disabled={loading}
						on:click={() => loadHistory(0, true)}>刷新</button
					>
				</div>
				<form
					class="mt-4 flex flex-wrap gap-2"
					on:submit|preventDefault={() => loadHistory(0, true)}
				>
					<input
						aria-label="搜索处理记录"
						bind:value={search}
						maxlength="200"
						placeholder="搜索问题或任务"
						class="tm-card min-w-0 flex-1 px-3 py-2 text-sm"
						disabled={loading}
					/>
					<select
						aria-label="筛选处理方式"
						bind:value={historyMode}
						class="tm-card px-3 py-2 text-sm"
						disabled={loading}
					>
						<option value="">全部方式</option><option value="answer">精答</option><option
							value="discuss">讨论</option
						><option value="team">协作</option>
					</select>
					<button class="tm-btn-ghost" disabled={loading}>搜索</button>
				</form>
				{#if historyError}<p role="alert" class="mt-3 text-sm text-red-500">{historyError}</p>{/if}
				{#if !items.length && !loading}<p class="mt-5 text-sm text-gray-400">
						{historyQuery.q || historyQuery.mode
							? '没有匹配的处理记录。'
							: '提交第一个问题，处理记录会保存在这里。'}
					</p>{/if}
				<div class="mt-4 divide-y divide-gray-100 dark:divide-gray-800">
					{#each items as row (row.id)}<a
							href={row.target_status === 'deleted'
								? `/auto?request=${row.id}`
								: row.href || `/auto?request=${row.id}`}
							class="flex flex-wrap items-center gap-3 rounded-xl px-3 py-4 hover:bg-gray-500/5"
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
								><span class="block truncate text-sm font-medium">{row.title || row.question}</span
								><span class="mt-1 block truncate text-xs text-gray-500"
									>{row.reason || row.question}</span
								></span
							>
							<span
								class="shrink-0 rounded-full bg-cyan-500/10 px-2 py-0.5 text-[11px] font-medium text-cyan-700 dark:text-cyan-300"
								>{row.mode ? MODE_LABEL[row.mode] : '分流中'}</span
							>
							<span
								class="min-w-[4rem] shrink-0 text-right text-xs {[
									'error',
									'interrupted',
									'failed',
									'plan_failed'
								].includes(row.status === 'dispatched' ? (row.target_status ?? '') : row.status)
									? 'text-red-500'
									: 'text-gray-400'}">{routeStatus(row)}</span
							>
						</a>{/each}
				</div>
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
	/* the disclosure draws its own chevron */
	.auto-more > summary {
		list-style: none;
	}
	.auto-more > summary::-webkit-details-marker {
		display: none;
	}
</style>
