<script lang="ts">
	import type { Writable } from 'svelte/store';
	import { getContext, onMount } from 'svelte';
	import { getSmartSearchUsage, type SmartSearchUsage } from '$lib/apis/retrieval';
	import { translateWithDefault } from '$lib/i18n';

	const i18n: Writable<any> = getContext('i18n');
	const tr = (key: string, defaultValue: string) =>
		translateWithDefault($i18n, key, defaultValue);

	const PROVIDER_NAMES: Record<string, string> = {
		direct: '本机直抓',
		cache: '缓存',
		tavily: 'Tavily',
		firecrawl: 'Firecrawl',
		jina: 'Jina',
		baidu: '百度搜索',
		'baidu-ai': '百度 AI 搜索',
		'baidu-trending': '百度热搜',
		langsearch: 'LangSearch',
		zhipu: '智谱',
		'zhipu-mcp': '智谱 MCP',
		'zhipu-mcp-reader': '智谱 MCP 读页',
		exa: 'Exa',
		context7: 'Context7',
		anysearch: 'AnySearch',
		'xai-responses': '主搜索（模型）'
	};
	// Sources that cost nothing per call.
	const FREE_PROVIDERS = new Set(['direct', 'cache', 'langsearch', 'jina']);
	const ORIGIN_NAMES: Record<string, string> = {
		halowebui: 'HaloWebUI',
		hermes: 'Hermes',
		runner: '终端任务',
		cli: '手动'
	};

	let usage: SmartSearchUsage | null = null;
	let loading = false;
	let error = '';

	const load = async (live = false) => {
		loading = true;
		error = '';
		try {
			usage = await getSmartSearchUsage(localStorage.token, live);
		} catch (err) {
			error = typeof err === 'string' ? err : tr('读取用量失败', 'Could not read usage');
		} finally {
			loading = false;
		}
	};

	$: rows = usage
		? Object.entries(usage.providers)
				.filter(([, entry]) => entry.today || entry.month || entry.window)
				.sort(([, a], [, b]) => (b.window?.calls ?? 0) - (a.window?.calls ?? 0))
		: [];
	$: allowances = usage
		? Object.entries(usage.providers).filter(([, entry]) => entry.free_allowance)
		: [];
	$: freeReads = usage?.free_page_reads ?? {};
	$: origins = Object.entries(usage?.origins ?? {}).sort(([, a], [, b]) => b - a);

	const allowanceUsed = (provider: string, used: number): string => {
		const live = usage?.live?.[provider];
		if (live && typeof live.used === 'number' && typeof live.limit === 'number') {
			return `${live.used} / ${live.limit}（${tr('服务商实时', 'live')}）`;
		}
		return `${tr('本机记账约', 'about')} ${Math.round(used * 10) / 10}`;
	};

	onMount(() => load(false));
</script>

<div class="space-y-2 rounded-xl border border-gray-100 p-3 dark:border-gray-800">
	<div class="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
		<div class="text-xs font-medium text-gray-600 dark:text-gray-300">
			{tr('Smart Search 用量', 'Smart Search usage')}
			{#if usage?.today}
				<span class="font-normal text-gray-400">· {tr('今天', 'today')} {usage.today}（{tr('北京时间', 'Beijing time')}）</span>
			{/if}
		</div>
		<button
			type="button"
			class="shrink-0 text-xs text-gray-500 underline-offset-2 hover:underline disabled:opacity-50 dark:text-gray-400"
			disabled={loading}
			on:click={() => load(true)}
		>
			{loading ? tr('读取中…', 'Loading…') : tr('查服务商剩余额度', 'Check remaining credits')}
		</button>
	</div>

	{#if error}
		<div class="text-xs text-red-500">{error}</div>
	{:else if usage && !usage.available}
		<div class="text-xs text-gray-500">{tr('用量账本不可写，暂时没有记录。', 'The usage ledger is not writable yet.')}</div>
	{:else if usage && rows.length === 0}
		<div class="text-xs text-gray-500">{tr('还没有搜索记录。', 'No searches recorded yet.')}</div>
	{:else if rows.length > 0}
		<div class="overflow-x-auto">
			<table class="w-full text-xs tabular-nums">
				<thead class="whitespace-nowrap text-gray-400">
					<tr>
						<th class="py-1 pr-2 text-left font-normal">{tr('来源', 'Source')}</th>
						<th class="px-1.5 py-1 text-right font-normal">{tr('今天', 'Today')}</th>
						<th class="px-1.5 py-1 text-right font-normal">{tr('本月', 'Month')}</th>
						<th class="hidden px-1.5 py-1 text-right font-normal sm:table-cell">{tr('7天出错', 'Errors 7d')}</th>
						<th class="hidden py-1 pl-1.5 text-right font-normal sm:table-cell">{tr('平均耗时', 'Avg')}</th>
					</tr>
				</thead>
				<tbody class="text-gray-600 dark:text-gray-300">
					{#each rows as [provider, entry] (provider)}
						<tr>
							<td class="py-0.5 pr-2">
								<div class="whitespace-nowrap">{PROVIDER_NAMES[provider] ?? provider}</div>
								{#if FREE_PROVIDERS.has(provider)}
									<div class="text-[11px] leading-tight text-gray-400">{tr('免费', 'free')}</div>
								{:else if entry.paid_unit}
									<div class="text-[11px] leading-tight text-gray-400">{entry.paid_unit}</div>
								{/if}
							</td>
							<td class="whitespace-nowrap px-1.5 py-0.5 text-right">{entry.today?.calls ?? 0}</td>
							<td class="whitespace-nowrap px-1.5 py-0.5 text-right">{entry.month?.calls ?? 0}</td>
							<td class="hidden whitespace-nowrap px-1.5 py-0.5 text-right sm:table-cell">
								{entry.window?.errors ?? 0}
							</td>
							<td class="hidden whitespace-nowrap py-0.5 pl-1.5 text-right sm:table-cell">
								{entry.window?.avg_ms ? `${(entry.window.avg_ms / 1000).toFixed(1)}s` : '—'}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	{#if allowances.length > 0}
		<div class="space-y-0.5 text-xs text-gray-500 dark:text-gray-400">
			{#each allowances as [provider, entry] (provider)}
				{#if entry.free_allowance}
					<div>
						{PROVIDER_NAMES[provider] ?? provider}：{entry.free_allowance.period === 'day'
							? tr('每天', 'per day')
							: tr('每月', 'per month')}
						{tr('免费', 'free')}
						{entry.free_allowance.allowance}，{tr('已用', 'used')}
						{allowanceUsed(provider, entry.free_allowance.used_here)}
					</div>
				{/if}
			{/each}
		</div>
	{/if}

	{#if usage && Object.keys(usage.exhausted ?? {}).length > 0}
		<div class="text-xs text-amber-600 dark:text-amber-400">
			{tr('额度用完、今天先跳过：', 'Out of quota, skipped today: ')}
			{Object.keys(usage.exhausted)
				.map((provider) => PROVIDER_NAMES[provider] ?? provider)
				.join('、')}
		</div>
	{/if}

	{#if (freeReads.direct ?? 0) + (freeReads.cache ?? 0) > 0 || origins.length > 0}
		<div class="text-xs text-gray-400">
			{#if (freeReads.direct ?? 0) + (freeReads.cache ?? 0) > 0}
				{tr('近 7 天免费读到网页', 'Pages read for free (7d)')}
				{(freeReads.direct ?? 0) + (freeReads.cache ?? 0)}
				{tr('页', '')}
			{/if}
			{#if origins.length > 0}
				· {origins.map(([origin, count]) => `${ORIGIN_NAMES[origin] ?? origin} ${count}`).join('，')}
			{/if}
		</div>
	{/if}
</div>
