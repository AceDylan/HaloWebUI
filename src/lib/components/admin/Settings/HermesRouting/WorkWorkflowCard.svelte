<script lang="ts">
	import type { HermesWorkConfigResponse, WorkStepKey, WorkWorkflowConfig } from '$lib/apis/hermes';
	import {
		chainCandidates,
		chainMove,
		chainRemove,
		runnerLabel,
		setWorkStepRunner,
		workConfigEquals,
		workDraftFrom,
		workFlowSummary
	} from '$lib/utils/hermes-routing';

	export let response: HermesWorkConfigResponse | null = null;
	export let draft: WorkWorkflowConfig | null = null;
	export let error = '';
	export let disabled = false;
	export let retry: () => void;

	$: runnerNames = response?.runners.map((runner) => runner.name) ?? [];

	const setFallback = (key: WorkStepKey, fallback: string[]) => {
		if (!draft) return;
		draft = { ...draft, steps: { ...draft.steps, [key]: { ...draft.steps[key], fallback } } };
	};
</script>

<section class="glass-item work-card px-4 py-3" data-section="work" aria-label="/work 工作流">
	<div class="flex flex-wrap items-start justify-between gap-2">
		<div>
			<h2 class="font-semibold">/work 工作流</h2>
			<p class="work-hint">为网页、Telegram 和 QQ 的 /work 设置首选执行器与兜底顺序。</p>
		</div>
		{#if response && draft}
			<button
				class="work-button"
				type="button"
				disabled={disabled || workConfigEquals(draft, response.defaults)}
				on:click={() => {
					if (response) draft = workDraftFrom({ ...response, config: response.defaults });
				}}>恢复默认</button
			>
		{/if}
	</div>

	{#if error}
		<div class="mt-3 flex flex-wrap items-center gap-2">
			<span role="status" class="text-xs text-rose-700 dark:text-rose-300">读取失败：{error}</span>
			<button class="work-button" type="button" {disabled} on:click={retry}>重试</button>
		</div>
	{:else if !response || !draft}
		<p class="work-hint mt-3" role="status">读取中…</p>
	{/if}

	{#if response && draft}
		<fieldset {disabled} class="mt-3 space-y-3" aria-label="配置 /work 工作流">
			<div class="work-flow" aria-label="流程预览">
				{#each workFlowSummary(draft) as step (step.key)}
					<span class="work-chip">
						<strong>{step.title}</strong>
						{step.runner}
						<span class="work-hint">{step.fallback.length} 个兜底</span>
					</span>
					<span aria-hidden="true">→</span>
				{/each}
				<span class="work-chip">自动发布</span>
			</div>

			<label class="flex cursor-pointer flex-wrap items-center gap-x-2 gap-y-1 py-1">
				<input
					type="checkbox"
					role="switch"
					data-work-toggle="plan_review"
					bind:checked={draft.plan_review}
				/>
				<span class="font-medium">规划后先审阅再开发</span>
				<span class="work-hint">审阅员确认或修订规划，完成审阅后才开始开发。</span>
			</label>

			{#each response.steps_meta as step (step.key)}
				{@const config = draft.steps[step.key]}
				{@const candidates = chainCandidates(runnerNames, config.fallback, config.runner)}
				<div
					class="work-row"
					class:inactive={step.optional && !draft.plan_review}
					data-work-step={step.key}
				>
					<div class="grid gap-1">
						<div class="font-medium">{step.label}</div>
						<span class="work-hint">{step.hint}</span>
						{#if step.optional && !draft.plan_review}
							<span class="work-hint">未启用（开启上方开关后生效）</span>
						{/if}
					</div>
					<div class="grid min-w-0 gap-2">
						<label class="flex flex-wrap items-center gap-2">
							<span class="work-hint">首选执行器</span>
							<select
								class="work-button"
								aria-label={`${step.label}首选执行器`}
								value={config.runner}
								on:change={(e) => {
									if (draft) draft = setWorkStepRunner(draft, step.key, e.currentTarget.value);
								}}
							>
								{#each response.runners as runner (runner.name)}
									<option value={runner.name}>
										{runnerLabel(runner.name)} · {runner.engine} / {runner.family}
									</option>
								{/each}
							</select>
						</label>
						<div class="work-flow">
							<span class="work-hint">兜底顺序</span>
							{#if !config.fallback.length}
								<span class="work-hint">不兜底：首选不可用时暂停等你处理</span>
							{/if}
							{#each config.fallback as runner, index (runner)}
								{#if index > 0}<span aria-hidden="true">→</span>{/if}
								<span class="work-chip" data-work-fallback={runner}>
									{runner}
									<button
										type="button"
										aria-label={`把 ${runner} 往前挪`}
										disabled={index === 0}
										on:click={() => setFallback(step.key, chainMove(config.fallback, index, -1))}
										>‹</button
									>
									<button
										type="button"
										aria-label={`把 ${runner} 往后挪`}
										disabled={index === config.fallback.length - 1}
										on:click={() => setFallback(step.key, chainMove(config.fallback, index, 1))}
										>›</button
									>
									<button
										type="button"
										aria-label={`移除 ${runner}`}
										on:click={() => setFallback(step.key, chainRemove(config.fallback, index))}
										>×</button
									>
								</span>
							{/each}
							{#if candidates.length}
								<select
									class="work-button"
									aria-label={`添加${step.label}兜底`}
									value=""
									on:change={(e) => {
										const select = e.currentTarget;
										if (select.value) setFallback(step.key, [...config.fallback, select.value]);
										select.value = '';
									}}
								>
									<option value="">+ 添加兜底</option>
									{#each candidates as runner (runner)}
										<option value={runner}>{runnerLabel(runner)}</option>
									{/each}
								</select>
							{/if}
						</div>
					</div>
				</div>
			{/each}
		</fieldset>
		<p class="work-hint mt-3">
			<code>/work cchclaude 需求</code> 可单次覆盖首选属于 Claude 家族的环节。命令点名的环节不自动兜底。
		</p>
	{/if}
</section>

<style>
	.work-card {
		border-radius: 0.85rem;
	}
	.work-hint {
		color: #475569;
		font-size: 0.75rem;
	}
	:global(.dark) .work-hint {
		color: #a5b4c7;
	}
	.work-flow {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.35rem;
	}
	.work-row {
		display: grid;
		gap: 0.5rem 1rem;
		padding: 0.65rem 0;
		border-top: 1px solid rgb(100 116 139 / 0.25);
	}
	@media (min-width: 640px) {
		.work-row {
			grid-template-columns: minmax(10rem, 1fr) 2fr;
		}
	}
	.work-row.inactive {
		background: rgb(100 116 139 / 0.06);
	}
	.work-chip,
	.work-button {
		border: 1px solid rgb(100 116 139 / 0.35);
		border-radius: 0.5rem;
		padding: 0.2rem 0.45rem;
		font-size: 0.75rem;
	}
	.work-button {
		max-width: 100%;
		background-color: rgb(255 255 255 / 0.75);
	}
	:global(.dark) .work-button {
		color-scheme: dark;
		background-color: #1e293b;
	}
	.work-chip {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
	}
	.work-chip button {
		width: 1.25rem;
		border-radius: 0.25rem;
	}
	.work-chip button:hover:not(:disabled),
	.work-button:hover:not(:disabled) {
		background: rgb(100 116 139 / 0.15);
	}
	button:disabled {
		opacity: 0.4;
	}
</style>
