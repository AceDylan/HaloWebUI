<script lang="ts">
	// 版本记录: an assistant's versions newest first (what made each one, and the run when a
	// workbench did), the settings of the one picked with a line diff against the current, and
	// 「恢复到这一版」 for those who may edit it.
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';

	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import {
		getAssistantVersions,
		restoreAssistantVersion,
		type AssistantVersions
	} from '$lib/apis/assistant-library';
	import { changeSourceLabel, runHref, versionTimeline, type VersionEntry } from '$lib/utils/assistant-library';
	import { diffStats, lineDiff } from '$lib/utils/line-diff';
	import { translateWithDefault } from '$lib/i18n';

	const i18n: any = getContext('i18n');
	const tr = (zh: string, en: string, options: Record<string, any> = {}) =>
		translateWithDefault($i18n, zh, en, options);

	export let show = false;
	/** The workspace model id of the assistant. */
	export let modelId: string | null = null;
	export let onRestored: (() => void) | null = null;

	let data: AssistantVersions | null = null;
	let loading = false;
	let error = '';
	let restoring = false;
	let selectedVersion: number | null = null;
	let loadedFor: string | null = null;

	const load = async (id: string) => {
		loading = true;
		error = '';
		try {
			data = await getAssistantVersions(localStorage.token, id);
			selectedVersion = data.current.version;
		} catch (e: any) {
			data = null;
			error = e?.message ?? String(e);
		} finally {
			loading = false;
		}
	};

	$: if (show && modelId && loadedFor !== modelId) {
		loadedFor = modelId;
		load(modelId);
	}
	$: if (!show) loadedFor = null;

	$: entries = versionTimeline(data);
	$: currentEntry = entries[0] ?? null;
	$: selected = entries.find((e) => e.version === selectedVersion) ?? currentEntry;
	$: diff = selected && currentEntry && !selected.current ? lineDiff(selected.system, currentEntry.system) : [];
	$: stats = diffStats(diff);

	const when = (at: number | null) => (at ? dayjs(at).format('YYYY-MM-DD HH:mm') : '');

	const restore = async (entry: VersionEntry) => {
		if (!modelId || restoring) return;
		restoring = true;
		try {
			data = await restoreAssistantVersion(localStorage.token, modelId, entry.version);
			selectedVersion = data.current.version;
			toast.success(tr('已恢复到第 {{version}} 版', 'Restored version {{version}}', { version: entry.version }));
			onRestored?.();
		} catch (e: any) {
			toast.error(e?.message ?? String(e));
		} finally {
			restoring = false;
		}
	};
</script>

<Modal bind:show size="lg">
	<div class="flex max-h-[85dvh] flex-col overflow-hidden" data-assistant-versions>
		<div class="flex items-center justify-between gap-3 border-b border-gray-100 px-5 py-4 dark:border-gray-800">
			<div class="min-w-0">
				<div class="truncate text-lg font-semibold text-gray-900 dark:text-gray-100">
					{tr('版本记录', 'Version history')}{data ? ` · ${data.name}` : ''}
				</div>
				<div class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
					{tr('名称、描述或设定每改一次记一个版本；最多保留最近 20 个旧版本。', 'Each change of name, description or prompt is a version; the last 20 are kept.')}
				</div>
			</div>
			<button
				class="rounded-xl p-2 text-gray-500 transition hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
				on:click={() => (show = false)}
				aria-label={tr('关闭', 'Close')}
			>
				<XMark className="size-4" />
			</button>
		</div>

		{#if loading}
			<div class="flex justify-center py-16"><Spinner /></div>
		{:else if error}
			<div class="px-5 py-10 text-center text-sm text-red-600 dark:text-red-400">{error}</div>
		{:else if data}
			<div class="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 py-4 md:flex-row md:overflow-hidden">
				<ol class="flex shrink-0 flex-col gap-1 md:w-64 md:overflow-y-auto md:pr-1" aria-label={tr('版本', 'Versions')}>
					{#each entries as entry (entry.version)}
						<li
							class="rounded-xl transition {selected?.version === entry.version
								? 'bg-gray-900/[0.06] dark:bg-white/[0.08]'
								: 'hover:bg-gray-900/[0.04] dark:hover:bg-white/[0.05]'}"
						>
							<button
								type="button"
								class="w-full px-3 pt-2 text-left {runHref(entry.runRef) ? 'pb-0.5' : 'pb-2'}"
								aria-current={selected?.version === entry.version ? 'true' : undefined}
								data-version={entry.version}
								on:click={() => (selectedVersion = entry.version)}
							>
								<div class="flex items-center gap-1.5 text-sm font-medium text-gray-900 dark:text-gray-100">
									<span class="tabular-nums">v{entry.version}</span>
									{#if entry.current}
										<span class="halo-chip">{tr('当前', 'Current')}</span>
									{/if}
									{#if entry.source}
										<span class="halo-chip">{changeSourceLabel(entry.source)}</span>
									{/if}
								</div>
								{#if entry.change || entry.at}
									<div class="mt-0.5 line-clamp-2 text-xs text-gray-500 dark:text-gray-400">
										{[when(entry.at), entry.change].filter(Boolean).join(' · ')}
									</div>
								{/if}
							</button>
							{#if runHref(entry.runRef)}
								<a
									class="mx-3 mb-2 inline-block text-xs text-primary-600 hover:underline dark:text-primary-400"
									href={runHref(entry.runRef)}
								>
									{tr('查看那次运行', 'Open that run')}
								</a>
							{/if}
						</li>
					{/each}
				</ol>

				{#if selected}
					<section class="flex min-w-0 flex-1 flex-col gap-3 md:overflow-y-auto">
						<div class="flex flex-wrap items-center justify-between gap-2">
							<div class="text-sm font-medium text-gray-800 dark:text-gray-200">
								{selected.current
									? tr('当前设定', 'Current prompt')
									: tr('第 {{version}} 版与当前版本对比', 'Version {{version}} against the current one', { version: selected.version })}
								{#if !selected.current}
									<span class="ml-1 text-xs font-normal text-gray-500 dark:text-gray-400" data-diff-stats>
										−{stats.removed} +{stats.added}
									</span>
								{/if}
							</div>
							{#if data.editable && !selected.current}
								<button
									type="button"
									class="workspace-secondary-button !py-1.5 text-xs"
									disabled={restoring}
									data-restore-version={selected.version}
									on:click={() => restore(selected)}
								>
									{restoring ? tr('恢复中…', 'Restoring…') : tr('恢复到这一版', 'Restore this version')}
								</button>
							{/if}
						</div>

						{#if selected.name && selected.name !== currentEntry?.name}
							<div class="text-xs text-gray-500 dark:text-gray-400">
								{tr('当时的名称：{{name}}', 'Name then: {{name}}', { name: selected.name })}
							</div>
						{/if}
						{#if selected.description}
							<div class="text-xs text-gray-500 dark:text-gray-400">{selected.description}</div>
						{/if}

						{#if selected.current}
							<pre class="max-h-[50dvh] overflow-auto whitespace-pre-wrap break-words rounded-xl bg-gray-50 p-3 font-mono text-xs leading-relaxed text-gray-700 dark:bg-gray-850 dark:text-gray-300">{selected.system || tr('（没有设定）', '(empty)')}</pre>
						{:else if diff.length === 0}
							<div class="rounded-xl bg-gray-50 p-3 text-xs text-gray-500 dark:bg-gray-850 dark:text-gray-400">
								{tr('两版设定都为空。', 'Both prompts are empty.')}
							</div>
						{:else}
							<div class="text-2xs text-gray-400 dark:text-gray-500">
								<span class="text-red-600 dark:text-red-400">− {tr('只在这一版', 'only in this version')}</span>
								<span class="ml-3 text-emerald-600 dark:text-emerald-400">+ {tr('只在当前版本', 'only in the current one')}</span>
							</div>
							<div class="max-h-[50dvh] overflow-auto rounded-xl bg-gray-50 py-2 font-mono text-xs leading-relaxed dark:bg-gray-850" data-diff>{#each diff as line}<div
										class="whitespace-pre-wrap break-words px-3 {line.type === 'del'
											? 'bg-red-500/10 text-red-700 dark:text-red-300'
											: line.type === 'add'
												? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
												: 'text-gray-600 dark:text-gray-400'}"
										data-diff-line={line.type}>{line.type === 'del' ? '− ' : line.type === 'add' ? '+ ' : '  '}{line.text || ' '}</div>{/each}</div>
						{/if}
					</section>
				{/if}
			</div>
		{/if}
	</div>
</Modal>
