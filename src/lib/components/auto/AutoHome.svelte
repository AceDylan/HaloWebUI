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
	import ModeDock from '$lib/components/scifi/ModeDock.svelte';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import HandoffBack from '$lib/components/common/HandoffBack.svelte';
	import '$lib/components/teams/teams.css';

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

	async function loadHistory(append = false) {
		if (loading) return;
		loading = true;
		try {
			const res = await listAutoRoutes(localStorage.token, append ? items.length : 0);
			items = append
				? [...items, ...res.items.filter((row) => !items.some((old) => old.id === row.id))]
				: res.items;
			more = res.more;
			historyError = '';
		} catch (e: any) {
			historyError = e.message || '历史读取失败';
		} finally {
			loading = false;
		}
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

<div class="h-full w-full overflow-y-auto text-gray-900 dark:text-gray-100" data-auto-home>
	<div class="mx-auto max-w-4xl px-4 py-6 sm:px-8 sm:py-10">
		<div class="mb-7 flex items-center gap-3">
			{#if $mobile}<button aria-label="打开侧栏" on:click={() => showSidebar.set(!$showSidebar)}
					><MenuLines /></button
				>{/if}
			<ModeDock current="auto" />
		</div>
		<h1 class="text-2xl font-semibold tracking-tight sm:text-3xl">自动分流工作台</h1>
		<p class="mt-3 text-sm leading-6 text-gray-500 dark:text-gray-400">
			描述问题或任务，自动选择精答、多模型讨论或协作台。
		</p>
		{#if origin}<div class="mt-3"><HandoffBack {origin} /></div>{/if}
		<form
			class="mt-7 rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-gray-800 dark:bg-gray-900"
			on:submit|preventDefault={start}
			on:dragover|preventDefault
			on:drop|preventDefault={(e) => attach(e.dataTransfer?.files ?? null)}
		>
			<textarea
				aria-label="问题或任务"
				maxlength="8000"
				rows="6"
				bind:value={question}
				disabled={busy}
				class="w-full resize-y rounded-t-2xl bg-transparent p-5 text-base outline-none"
				placeholder="你想了解什么，或希望完成什么？"
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
			{#if attachments.length}<div class="flex flex-wrap gap-2 px-5 pb-3">
					{#each attachments as file (file.key)}<div
							class="max-w-full rounded-lg bg-gray-100 px-3 py-2 text-xs dark:bg-gray-800"
						>
							<span class="break-all">{file.name}</span>
							{file.error || (!file.id ? `${file.progress}%` : '')}
							<button
								type="button"
								class="ml-2"
								aria-label={`移除 ${file.name}`}
								disabled={busy || (!file.id && !file.error)}
								on:click={() => (attachments = attachments.filter((f) => f.key !== file.key))}
								>×</button
							>
						</div>{/each}
				</div>{/if}
			<div
				class="flex flex-wrap items-center gap-3 border-t border-gray-100 p-4 dark:border-gray-800"
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
					class="rounded-lg bg-gray-100 px-3 py-2 text-sm dark:bg-gray-800"
					disabled={busy || uploading || attachments.length >= 4}
					on:click={() => fileInput.click()}>附件</button
				>
				<label class="text-sm"
					>处理方式 <select
						aria-label="处理方式"
						bind:value={mode}
						disabled={busy}
						class="rounded-lg border-0 bg-gray-100 text-sm dark:bg-gray-800"
					>
						<option value="auto">自动选择</option><option value="answer">精答</option><option
							value="discuss">讨论</option
						>{#if teamsEnabled}<option value="team">协作台</option>{/if}
					</select></label
				>
				<button
					type="submit"
					class="tm-btn-primary ml-auto"
					disabled={busy || uploading || failedUpload || !question.trim()}
					>{busy ? '正在处理…' : '开始处理'}</button
				>
			</div>
		</form>
		<details class="mt-4 text-sm text-gray-600 dark:text-gray-400">
			<summary class="cursor-pointer">处理偏好与背景{context ? ' · 已带入背景' : ''}</summary>
			<div class="mt-3 flex flex-wrap items-center gap-4">
				<label
					>讨论预算 <select
						aria-label="讨论预算"
						bind:value={preference}
						disabled={busy}
						class="rounded-lg border-0 bg-gray-100 text-sm dark:bg-gray-800"
						><option value="standard">标准 · 最多 3 个席位</option><option value="economy"
							>精简 · 2 个席位</option
						></select
					></label
				>
				{#if webEnabled}<label class="flex items-center gap-2"
						><input type="checkbox" bind:checked={research} disabled={busy} />按需联网</label
					>{/if}
				{#if teamsEnabled}<label class="flex items-center gap-2"
						><input
							type="checkbox"
							bind:checked={autoStart}
							disabled={busy}
						/>协作计划后直接开始</label
					>{/if}
			</div>
			<p class="mt-2 text-xs leading-5">
				讨论先进行一轮并汇总结论；协作默认先出计划。“只分析、不执行”等要求优先。关闭联网时，协作任务也会带上禁止联网的要求。
			</p>
			<textarea
				aria-label="背景信息"
				bind:value={context}
				disabled={busy}
				maxlength="12000"
				rows="3"
				placeholder="可选：补充背景、约束和已有结论"
				class="mt-3 w-full rounded-xl border border-gray-200 bg-transparent p-3 dark:border-gray-700"
			/>
		</details>
		{#if error}<p role="alert" class="mt-4 text-sm text-red-500">{error}</p>{/if}
		{#if active}<section
				class="mt-6 rounded-2xl border border-cyan-500/25 bg-cyan-500/5 p-5"
				aria-live="polite"
				data-auto-active
			>
				<div class="flex flex-wrap justify-between gap-2">
					<strong
						>{active.mode ? `自动分流 → ${MODE_LABEL[active.mode]}` : '正在选择处理方式'}</strong
					><span class="text-sm">{routeStatus(active)}</span>
				</div>
				<p class="mt-2 text-sm text-gray-500">
					{active.reason || '正在理解你的目标，选择合适的处理方式…'}
				</p>
				{#if active.error}<p class="mt-2 text-sm text-red-500">{active.error}</p>{/if}
				<div class="mt-4 flex gap-4 text-sm">
					{#if active.href && active.target_status !== 'deleted'}<a
							href={active.href}
							class="text-cyan-600 dark:text-cyan-300 underline"
							>打开{active.mode ? MODE_LABEL[active.mode] : '任务'}</a
						>{/if}
					{#if active.status === 'routing'}<button on:click={cancel}>取消分流</button>{/if}
					{#if !routePending(active)}<button on:click={reset}>开始另一次分流</button>{/if}
				</div>
			</section>{/if}
		<section class="mt-10 pb-8">
			<div class="flex items-center justify-between">
				<h2 class="text-base font-semibold">最近处理</h2>
				<button class="text-sm text-gray-500" disabled={loading} on:click={() => loadHistory()}
					>刷新</button
				>
			</div>
			{#if historyError}<p role="alert" class="mt-3 text-sm text-red-500">{historyError}</p>{/if}
			{#if !items.length && !loading}<p class="mt-5 text-sm text-gray-400">
					提交第一个问题，处理记录会保存在这里。
				</p>{/if}
			<div class="mt-4 divide-y divide-gray-100 dark:divide-gray-800">
				{#each items as row (row.id)}<a
						href={row.target_status === 'deleted'
							? `/auto?request=${row.id}`
							: row.href || `/auto?request=${row.id}`}
						class="flex flex-wrap items-center gap-3 py-4 hover:text-cyan-600"
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
						<span class="min-w-0 flex-1 truncate text-sm">{row.question}</span>
						<span class="text-xs text-gray-500"
							>{row.mode ? `自动 → ${MODE_LABEL[row.mode]}` : '自动分流'}</span
						>
						<span class="text-xs text-gray-400">{routeStatus(row)}</span>
					</a>{/each}
			</div>
			{#if more}<button
					class="mt-4 w-full rounded-xl border border-gray-200 py-2 text-sm dark:border-gray-700"
					disabled={loading}
					on:click={() => loadHistory(true)}>加载更多</button
				>{/if}
		</section>
	</div>
</div>
