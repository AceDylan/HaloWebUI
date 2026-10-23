<script lang="ts">
	// 辅助决策模型: the user's own, kept on the server (every device, every entry); saved on change.
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import HaloSelect from '$lib/components/common/HaloSelect.svelte';
	import {
		getDecisionModel,
		setDecisionModel,
		type DecisionModelCandidate,
		type DecisionModelState
	} from '$lib/apis/decision-model';

	const DEFAULT = '';

	let state: DecisionModelState | null = null;
	let value = DEFAULT;
	let saving = false;
	let loadError = '';

	const label = (c: DecisionModelCandidate) =>
		c.name +
		(c.connection ? ` · ${c.connection}` : '') +
		(c.kind === 'system_one' ? '（判断模型）' : '');

	$: options = [
		{ value: DEFAULT, label: '沿用现有逻辑（默认）' },
		// a stored model that is gone stays listed, so the user sees what is set
		...(state?.model && !state.candidates.some((c) => c.id === state?.model)
			? [{ value: state.model, label: `${state.name ?? state.model}（已不可用）` }]
			: []),
		...(state?.candidates ?? []).map((c) => ({ value: c.id, label: label(c) }))
	];

	const load = async () => {
		try {
			state = await getDecisionModel(localStorage.token);
			value = state.model ?? DEFAULT;
			loadError = '';
		} catch (error) {
			loadError = `${error instanceof Error ? error.message : error}`;
		}
	};

	const save = async (next: string) => {
		if (saving || !state || next === (state.model ?? DEFAULT)) return;
		saving = true;
		try {
			state = await setDecisionModel(localStorage.token, next || null);
			value = state.model ?? DEFAULT;
			toast.success(
				next ? `辅助决策模型改为 ${state.name ?? next}` : '已恢复默认：沿用各模块现有逻辑'
			);
		} catch (error) {
			value = state.model ?? DEFAULT;
			toast.error(`${error instanceof Error ? error.message : error}`);
		} finally {
			saving = false;
		}
	};

	onMount(load);
</script>

<div class="glass-item p-4 space-y-3" data-decision-model-setting>
	<div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
		<div class="space-y-1">
			<div class="text-sm font-medium">辅助决策模型</div>
			<div class="text-xs leading-5 text-gray-500 dark:text-gray-400">
				自动分流、精答、讨论、协作里仍为「自动」的选择（处理方式、助手、模型、轮次、执行器）先交给它判断；你手动指定的不变，它失败时自动回退原来的逻辑。正文回答、成员执行和总结仍由各自的模型完成。
			</div>
		</div>
		<div class="flex shrink-0 items-center gap-2 self-start">
			<HaloSelect
				bind:value
				{options}
				className="w-full sm:w-72"
				searchEnabled={true}
				searchPlaceholder="搜索模型"
				noResultsText="没有可用的模型"
				disabled={saving || !state}
				on:change={(event) => save(event.detail.value)}
			/>
			{#if state?.model}
				<button
					type="button"
					class="shrink-0 rounded-lg px-2 py-1 text-xs text-gray-500 hover:bg-gray-500/10 hover:text-gray-800 disabled:opacity-50 dark:text-gray-400 dark:hover:text-gray-100"
					disabled={saving}
					data-decision-model-reset
					on:click={() => save(DEFAULT)}>恢复默认</button
				>
			{/if}
		</div>
	</div>
	{#if state?.model && state.available === false}
		<p class="text-xs text-amber-600 dark:text-amber-400" data-decision-model-unavailable>
			已设置的模型现在不可用（被删除、停用或没有权限），各模块会按原来的逻辑决定；请换一个或恢复默认。
		</p>
	{/if}
	{#if loadError}
		<p class="text-xs text-amber-600 dark:text-amber-400">读取设置失败：{loadError}</p>
	{/if}
</div>
