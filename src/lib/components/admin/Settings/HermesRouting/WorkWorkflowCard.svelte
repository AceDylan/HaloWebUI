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

	const setFlag = (key: keyof Omit<WorkWorkflowConfig, 'steps'>, value: boolean) => {
		if (!draft) return;
		draft = { ...draft, [key]: value };
	};

	const stepActive = (key: WorkStepKey, config: WorkWorkflowConfig) =>
		key !== 'plan_review' || config.plan_review || config.dual_plan || config.ui_review;

	const stepRoleNote = (key: WorkStepKey, config: WorkWorkflowConfig): string => {
		if (key === 'plan') {
			return config.dual_plan
				? '当前职责：与主控并行独立出对比方案' + (config.ui_review ? '，并审阅交互与文案' : '')
				: config.ui_review
					? '当前职责：读代码出 .halo/plan.md，并审阅交互与文案'
					: '当前职责：读代码与现状，写出 .halo/plan.md 实现规划';
		}
		if (key === 'plan_review') {
			if (config.dual_plan) {
				return (
					'当前职责：主控摸底、独立出方案、对比合成' +
					(config.plan_approval ? '并请你拍板' : '') +
					(config.ui_review ? '、出设计稿并定稿' : '')
				);
			}
			if (config.ui_review) {
				return (
					'当前职责：' +
					(config.plan_review ? '审阅定稿规划、' : '') +
					'出交互设计稿并取舍定稿'
				);
			}
			return config.plan_review
				? '当前职责：核查并定稿 .halo/plan.md，确认无误后放行开发'
				: '未启用（开启规划审阅、双方案并行或 UI 交互审稿后生效）';
		}
		if (key === 'dev') {
			return config.split_dev
				? '当前职责：按派活单完成成块后端代码与单元测试'
				: '当前职责：按 .halo/plan.md 完成全部前后端改动与测试';
		}
		return config.split_dev
			? '当前职责：读后端改动、写前端联调并跑全套测试（交付前再由 Codex 独立审查 2 轮）'
			: '当前职责：审阅代码 diff、直接修掉发现的问题并跑测试确认';
	};
</script>

<section class="glass-item work-card px-4 py-3" data-section="work" aria-label="/work 工作流">
	<div class="flex flex-wrap items-start justify-between gap-2">
		<div>
			<h2 class="font-semibold">/work 工作流</h2>
			<p class="work-hint">
				统一配置网页、Telegram、QQ 与协作台的 /work：自由组合多模型模块、首选执行器与兜底顺序。
			</p>
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
				{#if draft.split_dev}
					<span class="work-chip"><strong>Codex 2 轮审查</strong></span>
					<span aria-hidden="true">→</span>
				{/if}
				<span class="work-chip">自动发布</span>
			</div>

			<div class="grid gap-1.5 py-1" data-work-modules>
				<label class="flex cursor-pointer flex-wrap items-center gap-x-2 gap-y-0.5">
					<input
						type="checkbox"
						role="switch"
						data-work-toggle="plan_review"
						checked={draft.plan_review}
						on:change={(e) => setFlag('plan_review', Boolean((e.currentTarget ?? e.target)?.checked))}
					/>
					<span class="font-medium">规划后先审阅再开发</span>
					<span class="work-hint">
						{draft.dual_plan
							? '双方案并行已开启，当前由双方案对比合成替代单规划审阅。'
							: '审阅员核查或修订规划，完成审阅后才开始开发。'}
					</span>
				</label>

				<label class="flex cursor-pointer flex-wrap items-center gap-x-2 gap-y-0.5">
					<input
						type="checkbox"
						role="switch"
						data-work-toggle="dual_plan"
						checked={draft.dual_plan}
						on:change={(e) => setFlag('dual_plan', Boolean((e.currentTarget ?? e.target)?.checked))}
					/>
					<span class="font-medium">双方案并行对照</span>
					<span class="work-hint">主控摸底后，两位规划成员并行盲写方案再逐条对比合成。</span>
				</label>

				<label class="flex cursor-pointer flex-wrap items-center gap-x-2 gap-y-0.5">
					<input
						type="checkbox"
						role="switch"
						data-work-toggle="plan_approval"
						checked={draft.plan_approval}
						on:change={(e) => setFlag('plan_approval', Boolean((e.currentTarget ?? e.target)?.checked))}
					/>
					<span class="font-medium">方案定稿后强制等你拍板</span>
					<span class="work-hint">暂停发出方案要点，等你拍板后再进开发；关闭则仅遇重大歧义再问。</span>
				</label>

				<label class="flex cursor-pointer flex-wrap items-center gap-x-2 gap-y-0.5">
					<input
						type="checkbox"
						role="switch"
						data-work-toggle="ui_review"
						checked={draft.ui_review}
						on:change={(e) => setFlag('ui_review', Boolean((e.currentTarget ?? e.target)?.checked))}
					/>
					<span class="font-medium">UI 交互与文案互审</span>
					<span class="work-hint">开发前先出设计稿并由规划顾问审交互和文案（纯后端需求自动跳过）。</span>
				</label>

				<label class="flex cursor-pointer flex-wrap items-center gap-x-2 gap-y-0.5">
					<input
						type="checkbox"
						role="switch"
						data-work-toggle="split_dev"
						checked={draft.split_dev}
						on:change={(e) => setFlag('split_dev', Boolean((e.currentTarget ?? e.target)?.checked))}
					/>
					<span class="font-medium">前后端分拆 + 交付前 Codex 2 轮审查</span>
					<span class="work-hint">
						开发写后端、验收写前端联调，合并前自动走 Codex 独立审查；关闭则全栈开发并直接审阅修复。
					</span>
				</label>
			</div>

			{#each response.steps_meta as step (step.key)}
				{@const config = draft.steps[step.key]}
				{@const candidates = chainCandidates(runnerNames, config.fallback, config.runner)}
				{@const active = stepActive(step.key, draft)}
				<div class="work-row" class:inactive={!active} data-work-step={step.key}>
					<div class="grid gap-1">
						<div class="font-medium">{step.label}</div>
						<span class="work-hint">{stepRoleNote(step.key, draft)}</span>
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
			命令用法：<code>/work 需求</code> 按此处默认配置执行；<code>/work 深度 需求</code> 单次拉满多模型全流程；<code>/work 快速 需求</code> 单次走 3 步精简闭环；<code>/work cchclaude 需求</code> 单次锁定 Claude 家族执行器（不自动兜底）。
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
