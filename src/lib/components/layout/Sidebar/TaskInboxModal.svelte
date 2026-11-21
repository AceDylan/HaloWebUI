<script lang="ts">
	import { createEventDispatcher, getContext, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';

	import {
		hermesBackgroundRuns,
		mobile,
		showHermesSessions,
		showSidebar
	} from '$lib/stores';
	import {
		getTaskInbox,
		importHermesSession,
		removeTaskInboxItem,
		type TaskInboxItem,
		type TaskInboxResponse
	} from '$lib/apis/hermes';
	import { refreshHermesActivitySoon } from '$lib/utils/hermes-activity';
	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	dayjs.extend(relativeTime);

	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	export let show = false;

	type TabKey = 'attention' | 'running' | 'ended';
	type SourceFilter = 'all' | 'web' | 'telegram' | 'qqbot' | 'cli';

	const KIND_LABEL: Record<string, string> = {
		hermes: 'Hermes',
		runner: '后台执行',
		team: '协作台',
		answer: '精答',
		discuss: '讨论台',
		video: '视频',
		auto: '自动分流',
		chat: '对话',
		image: '生图',
		session: '会话'
	};

	const SOURCE_LABEL: Record<string, string> = {
		web: '网页',
		telegram: 'Telegram',
		qqbot: 'QQ',
		cli: 'CLI'
	};

	let inbox: TaskInboxResponse | null = null;
	let loading = false;
	let error = '';
	let tab: TabKey = 'attention';
	let tabPickedManually = false;
	let sourceFilter: SourceFilter = 'all';
	let importingId: string | null = null;
	let loaded = false;
	let requestSeq = 0;

	let armedRemoveId: string | null = null;
	let removingId: string | null = null;
	let armTimer: ReturnType<typeof setTimeout> | null = null;

	const clearArm = () => {
		if (armTimer) {
			clearTimeout(armTimer);
			armTimer = null;
		}
		armedRemoveId = null;
	};

	onDestroy(() => {
		clearArm();
	});

	const load = async (autoPickTab = false) => {
		const seq = ++requestSeq;
		loading = true;
		error = '';
		try {
			const data = await getTaskInbox(localStorage.token, 7);
			if (seq !== requestSeq) return;
			inbox = data;
			if (autoPickTab && !tabPickedManually) {
				if (data.attention.length > 0) tab = 'attention';
				else if (data.running.length > 0) tab = 'running';
				else tab = 'ended';
			}
		} catch (e) {
			if (seq !== requestSeq) return;
			error = `${(e as Error)?.message ?? e}`;
		} finally {
			if (seq === requestSeq) loading = false;
		}
	};

	$: if (show && !loaded) {
		loaded = true;
		tabPickedManually = false;
		sourceFilter = 'all';
		void load(true);
	}
	$: if (!show && loaded) {
		loaded = false;
		clearArm();
	}

	$: allItems = inbox ? [...inbox.attention, ...inbox.running, ...inbox.ended] : [];
	$: hasCrossChannel = allItems.some((item) => item.source !== 'web');
	$: availableSources = (['all', 'web', 'telegram', 'qqbot', 'cli'] as SourceFilter[]).filter(
		(src) => src === 'all' || allItems.some((item) => item.source === src)
	);

	const filterSource = (items: TaskInboxItem[], filter: SourceFilter) =>
		filter === 'all' ? items : items.filter((item) => item.source === filter);

	$: attentionItems = filterSource(inbox?.attention ?? [], sourceFilter);
	$: runningItems = filterSource(inbox?.running ?? [], sourceFilter);
	$: endedItems = filterSource(inbox?.ended ?? [], sourceFilter);
	$: visibleItems =
		tab === 'attention' ? attentionItems : tab === 'running' ? runningItems : endedItems;

	const when = (ts: number) => {
		if (!ts) return '';
		const d = dayjs.unix(ts);
		return d.isValid() ? d.fromNow() : '';
	};

	const recoveryHint = (item: TaskInboxItem) => {
		if (item.recovery === 'continue') return '可继续原任务';
		if (item.recovery === 'restart') return '需重新发起';
		return '';
	};

	const dotClass = (item: TaskInboxItem) => {
		if (item.bucket === 'attention') return 'bg-amber-500';
		if (item.bucket === 'running') return 'bg-blue-500';
		if (item.unread) return 'bg-emerald-500';
		if (item.status === 'failed') return 'bg-red-500';
		if (item.status === 'stopped') return 'bg-gray-400';
		return 'bg-emerald-500/75';
	};

	const statusPillClass = (item: TaskInboxItem) => {
		if (item.bucket === 'attention')
			return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300';
		if (item.bucket === 'running')
			return 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300';
		if (item.unread)
			return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300';
		if (item.status === 'failed')
			return 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300';
		if (item.status === 'stopped')
			return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300';
		return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300';
	};

	const openItem = async (item: TaskInboxItem) => {
		if (importingId) return;
		if (item.href) {
			show = false;
			if ($mobile) showSidebar.set(false);
			await goto(item.href);
			return;
		}
		if (item.session_id) {
			importingId = item.id;
			try {
				const result = await importHermesSession(localStorage.token, item.session_id);
				if (result?.created) dispatch('change');
				show = false;
				if ($mobile) showSidebar.set(false);
				await goto(`/c/${result.chat_id}`);
			} catch (e) {
				toast.error(`${e}`);
			} finally {
				importingId = null;
			}
			return;
		}
		// Non-web runner run without a direct chat link: open Hermes Sessions so user can pick the TG/QQ thread
		show = false;
		showHermesSessions.set(true);
	};

	const removeItem = async (item: TaskInboxItem) => {
		if (removingId) return;
		if (armedRemoveId !== item.id) {
			clearArm();
			armedRemoveId = item.id;
			armTimer = setTimeout(() => {
				armedRemoveId = null;
				armTimer = null;
			}, 5000);
			return;
		}
		clearArm();
		removingId = item.id;
		try {
			const res = await removeTaskInboxItem(localStorage.token, item);
			if (inbox) {
				const drop = (list: TaskInboxItem[]) =>
					list.filter(
						(entry) =>
							entry.id !== item.id &&
							!(item.run_id && entry.run_id && entry.run_id === item.run_id)
					);
				const attention = drop(inbox.attention);
				const running = drop(inbox.running);
				const ended = drop(inbox.ended);
				inbox = {
					...inbox,
					attention,
					running,
					ended,
					counts: {
						attention: attention.length,
						running: running.length,
						ended: ended.length
					}
				};
			}
			if (item.run_id) {
				hermesBackgroundRuns.update((runs) => runs.filter((r) => r.run_id !== item.run_id));
			}
			refreshHermesActivitySoon(100);
			if (res.stopped) {
				toast.success('已停止并删除该任务');
			} else if (res.cross_channel) {
				toast.success('已从列表清理（跨端后台任务如需终止请在发起端执行 /stop）');
			} else {
				toast.success(item.bucket === 'running' ? '已从进行中删除' : '已从列表清理');
			}
		} catch (e) {
			toast.error(`没能删除：${(e as Error)?.message ?? e}`);
		} finally {
			removingId = null;
		}
	};
</script>

<Modal size="lg" bind:show>
	<div class="flex flex-col" data-halo-task-inbox-modal>
		<div class="flex items-center justify-between px-5 pt-4 pb-2 dark:text-gray-200">
			<div class="min-w-0">
				<div class="text-base font-semibold text-gray-900 dark:text-gray-100">任务收件箱</div>
				<div class="text-xs text-gray-500 dark:text-gray-400">
					汇总最近 7 天网页各工作台与 Telegram / QQ 的待处理、进行中与已结束任务
				</div>
			</div>
			<div class="flex shrink-0 items-center gap-1.5">
				<button
					type="button"
					class="rounded-full px-2.5 py-1 text-xs font-medium text-gray-500 transition hover:bg-gray-100 hover:text-gray-900 disabled:opacity-50 dark:text-gray-400 dark:hover:bg-gray-850 dark:hover:text-gray-100"
					disabled={loading}
					on:click={() => load(false)}
					data-halo-task-inbox-refresh
				>
					{$i18n.t('Refresh')}
				</button>
				<button
					type="button"
					class="rounded-full p-1 text-gray-400 transition hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-850 dark:hover:text-gray-200"
					aria-label={$i18n.t('Close')}
					on:click={() => {
						show = false;
					}}
				>
					<XMark className="size-5" />
				</button>
			</div>
		</div>

		<!-- Bucket tabs -->
		<div class="flex flex-wrap items-center gap-1.5 px-5 pb-2">
			<button
				type="button"
				class="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition {tab ===
				'attention'
					? 'bg-amber-500/15 text-amber-800 ring-1 ring-inset ring-amber-500/30 dark:text-amber-300'
					: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-850 dark:text-gray-300 dark:hover:bg-gray-800'}"
				aria-pressed={tab === 'attention'}
				data-halo-task-inbox-tab="attention"
				on:click={() => {
					tab = 'attention';
					tabPickedManually = true;
				}}
			>
				<span>等我处理</span>
				{#if attentionItems.length > 0}
					<span
						class="rounded-full bg-amber-500 px-1.5 py-0.2 text-2xs font-semibold text-white"
						>{attentionItems.length}</span
					>
				{/if}
			</button>

			<button
				type="button"
				class="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition {tab ===
				'running'
					? 'bg-blue-500/15 text-blue-700 ring-1 ring-inset ring-blue-500/30 dark:text-blue-300'
					: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-850 dark:text-gray-300 dark:hover:bg-gray-800'}"
				aria-pressed={tab === 'running'}
				data-halo-task-inbox-tab="running"
				on:click={() => {
					tab = 'running';
					tabPickedManually = true;
				}}
			>
				<span>进行中</span>
				{#if runningItems.length > 0}
					<span class="rounded-full bg-blue-500 px-1.5 py-0.2 text-2xs font-semibold text-white"
						>{runningItems.length}</span
					>
				{/if}
			</button>

			<button
				type="button"
				class="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition {tab ===
				'ended'
					? 'bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-fg)]'
					: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-850 dark:text-gray-300 dark:hover:bg-gray-800'}"
				aria-pressed={tab === 'ended'}
				data-halo-task-inbox-tab="ended"
				on:click={() => {
					tab = 'ended';
					tabPickedManually = true;
				}}
			>
				<span>已结束</span>
				{#if endedItems.length > 0}
					<span
						class="rounded-full bg-gray-400/25 px-1.5 py-0.2 text-2xs font-semibold text-current"
						>{endedItems.length}</span
					>
				{/if}
			</button>

			{#if hasCrossChannel && availableSources.length > 2}
				<div class="ml-auto flex flex-wrap items-center gap-1">
					{#each availableSources as src (src)}
						<button
							type="button"
							class="rounded-full px-2 py-0.5 text-2xs font-medium transition {sourceFilter === src
								? 'bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900'
								: 'text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-850'}"
							aria-pressed={sourceFilter === src}
							data-halo-task-inbox-source={src}
							on:click={() => {
								sourceFilter = src;
							}}
						>
							{src === 'all' ? '全部来源' : SOURCE_LABEL[src] ?? src}
						</button>
					{/each}
				</div>
			{/if}
		</div>

		<hr class="border-gray-100 dark:border-gray-850" />

		<div class="max-h-[60vh] overflow-y-auto px-3 py-2.5 scrollbar-hidden dark:text-gray-200">
			{#if loading && !inbox}
				<div class="flex justify-center py-10"><Spinner className="size-5" /></div>
			{:else if error}
				<div class="flex flex-col items-center gap-2 py-10 text-sm text-gray-500">
					<div class="max-w-full truncate">{error}</div>
					<button
						type="button"
						class="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800"
						on:click={() => load(false)}
					>
						重新加载
					</button>
				</div>
			{:else if visibleItems.length === 0}
				<div class="py-10 text-center text-sm text-gray-500 dark:text-gray-400" data-halo-task-inbox-empty>
					{#if tab === 'attention'}
						目前没有等你处理的任务
					{:else if tab === 'running'}
						当前没有进行中的任务
					{:else}
						最近 7 天没有已结束的任务记录
					{/if}
				</div>
			{:else}
				<div class="flex flex-col gap-1">
					{#each visibleItems as item (item.id)}
						<div
							class="group flex items-center gap-2 rounded-xl px-2.5 py-2 transition hover:bg-gray-50 dark:hover:bg-gray-850"
							data-halo-task-inbox-item={item.id}
							data-halo-task-inbox-bucket={item.bucket}
						>
							<button
								type="button"
								class="flex min-w-0 flex-1 items-start gap-2.5 text-left disabled:cursor-wait"
								disabled={importingId !== null}
								on:click={() => openItem(item)}
							>
								<span class="relative mt-1.5 flex h-2 w-2 shrink-0">
									{#if item.bucket === 'running' || item.bucket === 'attention'}
										<span
											class="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 {dotClass(
												item
											)}"
										></span>
									{/if}
									<span class="relative inline-flex h-2 w-2 rounded-full {dotClass(item)}"></span>
								</span>

								<div class="min-w-0 flex-1">
									<div class="flex flex-wrap items-center gap-1.5">
										<span class="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
											{item.title}
										</span>
										<span
											class="shrink-0 rounded px-1.5 py-0.5 text-2xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300"
										>
											{KIND_LABEL[item.kind] ?? item.kind}
										</span>
										{#if item.source !== 'web'}
											<span
												class="shrink-0 rounded px-1.5 py-0.5 text-2xs font-medium bg-sky-500/10 text-sky-700 dark:bg-sky-400/15 dark:text-sky-300"
												data-halo-task-inbox-source-badge={item.source}
											>
												{SOURCE_LABEL[item.source] ?? item.source}
											</span>
										{/if}
										<span
											class="shrink-0 rounded-full px-1.5 py-0.5 text-2xs font-medium {statusPillClass(
												item
											)}"
										>
											{item.status_label}
										</span>
									</div>

									<div
										class="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-gray-500 dark:text-gray-400"
									>
										{#if when(item.timestamp)}
											<span class="shrink-0">{when(item.timestamp)}</span>
										{/if}
										{#if recoveryHint(item)}
											<span
												class="shrink-0 font-medium {item.recovery === 'continue'
													? 'text-sky-700 dark:text-sky-300'
													: 'text-amber-700 dark:text-amber-300'}"
												data-halo-task-inbox-recovery={item.recovery}
											>
												· {recoveryHint(item)}
											</span>
										{/if}
										{#if item.summary}
											<span class="min-w-0 truncate">· {item.summary}</span>
										{/if}
									</div>
								</div>

								<span class="mt-0.5 shrink-0 text-xs text-gray-400 dark:text-gray-500">
									{#if importingId === item.id}
										<Spinner className="size-3.5" />
									{:else if item.session_id && !item.imported}
										导入并打开 →
									{:else if item.href}
										打开 →
									{:else}
										去会话查看 →
									{/if}
								</span>
							</button>

							{#if item.bucket === 'running' || item.bucket === 'attention'}
								<button
									type="button"
									class="shrink-0 rounded-md px-2 py-1 text-2xs font-medium transition disabled:opacity-50 {armedRemoveId ===
									item.id
										? 'bg-red-50 text-red-600 dark:bg-red-950/40 dark:text-red-400'
										: 'text-gray-400 hover:bg-gray-100 hover:text-red-600 dark:hover:bg-gray-800 dark:hover:text-red-400'}"
									disabled={removingId === item.id}
									on:click|stopPropagation={() => removeItem(item)}
									data-halo-task-inbox-remove={item.id}
									aria-label={armedRemoveId === item.id
										? `确认删除 ${item.title}`
										: `删除 ${item.title}`}
								>
									{#if removingId === item.id}
										删除中…
									{:else if armedRemoveId === item.id}
										{item.bucket === 'running' ? '确认删除' : '确认清理'}
									{:else}
										{item.bucket === 'running' ? '删除' : '清理'}
									{/if}
								</button>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
		</div>
	</div>
</Modal>
