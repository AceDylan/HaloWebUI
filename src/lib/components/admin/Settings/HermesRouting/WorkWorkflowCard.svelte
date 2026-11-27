<script lang="ts">
	import type {
		HermesWorkConfigResponse,
		WorkPresetKey,
		WorkProfileConfig,
		WorkStepKey,
		WorkWorkflowConfig
	} from '$lib/apis/hermes';
	import {
		WORK_PRESET_INFO,
		WORK_PRESET_KEYS,
		chainCandidates,
		chainMove,
		chainRemove,
		runnerLabel,
		setWorkStepRunner,
		withWorkProfile,
		workConfigEquals,
		workDraftFrom,
		workFlowSummary,
		workProfileEquals,
		workProfileOf,
		workSelfReviewWarning
	} from '$lib/utils/hermes-routing';

	export let response: HermesWorkConfigResponse | null = null;
	export let draft: WorkWorkflowConfig | null = null;
	export let error = '';
	export let disabled = false;
	export let retry: () => void;

	let activePreset: WorkPresetKey = 'default';

	$: runnerNames = response?.runners.map((runner) => runner.name) ?? [];
	$: presetList =
		response?.presets_meta?.length
			? response.presets_meta
			: WORK_PRESET_KEYS.map((key) => ({
					key,
					preset: key === 'default' ? ('' as const) : key,
					command: WORK_PRESET_INFO[key].command,
					label: WORK_PRESET_INFO[key].label,
					hint: WORK_PRESET_INFO[key].hint
				}));
	$: activeMeta = presetList.find((item) => item.key === activePreset) ?? presetList[0];
	$: activeProfile = draft ? workProfileOf(draft, activePreset) : null;
	$: activeDefaultProfile = response ? workProfileOf(response.defaults, activePreset) : null;
	$: selfReviewHint =
		activeProfile && response ? workSelfReviewWarning(activeProfile, response.runners) : '';

	const updateActiveProfile = (updater: (profile: WorkProfileConfig) => WorkProfileConfig) => {
		if (!draft) return;
		draft = withWorkProfile(draft, activePreset, updater(workProfileOf(draft, activePreset)));
	};

	const setFallback = (key: WorkStepKey, fallback: string[]) => {
		updateActiveProfile((profile) => ({
			...profile,
			steps: { ...profile.steps, [key]: { ...profile.steps[key], fallback } }
		}));
	};

	const setFlag = (key: keyof Omit<WorkProfileConfig, 'steps'>, value: boolean) => {
		updateActiveProfile((profile) => ({ ...profile, [key]: value }));
	};

	const resetActivePreset = () => {
		if (!draft || !response) return;
		const freshDefaults = workDraftFrom({ ...response, config: response.defaults });
		draft = withWorkProfile(draft, activePreset, workProfileOf(freshDefaults, activePreset));
	};

	const stepActive = (key: WorkStepKey, config: WorkProfileConfig) => {
		if (key === 'plan_review') return config.plan_review || config.dual_plan || config.ui_review;
		if (key === 'frontend') return config.split_dev;
		return true;
	};

	const stepLabel = (key: WorkStepKey, fallbackLabel: string, config: WorkProfileConfig): string => {
		if (key === 'dev') return config.split_dev ? '后端开发' : '全栈开发';
		return fallbackLabel;
	};

	const stepRoleNote = (key: WorkStepKey, config: WorkProfileConfig): string => {
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
				? '当前职责：核查并定稿 .halo/plan.md，明确前后端接口边界后放行开发'
				: '未启用（开启规划审阅、双方案并行或 UI 交互审稿后生效）';
		}
		if (key === 'dev') {
			return config.split_dev
				? '当前职责：按派活单与接口契约完成成块后端代码与后端单元测试'
				: '当前职责：按 .halo/plan.md 完成全部前后端改动与测试';
		}
		if (key === 'frontend') {
			return config.split_dev
				? '当前职责：读后端回执与 diff，完成前端实现、联调与前端测试（纯后端需求自动跳过）'
				: '未启用（开启「前后端分拆开发」后生效，可提前配置首选与兜底）';
		}
		return config.codex_review
			? '当前职责：审阅完整 diff、直接修掉问题并跑测试（交付前再走 Codex 2 轮独立审查）'
			: '当前职责：通读完整前后端 diff，审阅并直接修掉问题、跑通受影响测试后自动发布';
	};
</script>

<section class="glass-item work-card px-4 py-3" data-section="work" aria-label="/work 工作流">
	<div class="flex flex-wrap items-start justify-between gap-2">
		<div>
			<h2 class="font-semibold">/work 工作流</h2>
			<p class="work-hint">
				独立配置默认、深度、快速三种工作流：每档都能自由开关模块，并单独指定规划、后端、前端与审阅执行器及兜底顺序。
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
	{:else if !response || !draft || !activeProfile}
		<p class="work-hint mt-3" role="status">读取中…</p>
	{/if}

	{#if response && draft && activeProfile}
		<fieldset {disabled} class="mt-3 space-y-3" aria-label="配置 /work 工作流">
			<!-- All three workflows clearly visible at a glance; click any card to edit it -->
			<div class="space-y-2" data-work-overview aria-label="当前三种工作流总览">
				{#each presetList as preset (preset.key)}
					{@const flowSteps = workFlowSummary(draft, preset.key)}
					{@const isSelected = activePreset === preset.key}
					<button
						type="button"
						class="work-preset-card"
						class:active={isSelected}
						data-work-preset={preset.key}
						aria-pressed={isSelected}
						on:click={() => (activePreset = preset.key)}
					>
						<div class="work-preset-head">
							<span class="work-preset-title">
								<strong>{preset.label}</strong>
								<code class="work-cmd">{preset.command}</code>
							</span>
							<span class="work-preset-state" class:selected={isSelected}>
								{isSelected ? '正在编辑' : '点击编辑'}
							</span>
						</div>
						<div class="work-flow" aria-label={`${preset.label}流程预览`}>
							{#each flowSteps as step (step.key)}
								<span class="work-chip">
									<strong>{step.title}</strong>
									{#if !step.fixed}
										{step.runner}
										<span class="work-hint">{step.fallback.length} 兜底</span>
									{/if}
								</span>
								<span aria-hidden="true">→</span>
							{/each}
							<span class="work-chip">自动发布</span>
						</div>
					</button>
				{/each}
			</div>

			<div class="work-editor-head" data-work-editor={activePreset}>
				<div>
					<div class="font-medium">
						正在配置：{activeMeta.label} <code class="work-cmd">{activeMeta.command}</code>
					</div>
					<div class="work-hint">{activeMeta.hint}</div>
				</div>
				{#if activeDefaultProfile}
					<button
						class="work-button"
						type="button"
						data-work-reset-preset={activePreset}
						disabled={disabled || workProfileEquals(activeProfile, activeDefaultProfile)}
						on:click={resetActivePreset}>恢复本档默认</button
					>
				{/if}
			</div>

			<div class="grid gap-1.5 py-1" data-work-modules>
				<label class="flex cursor-pointer flex-wrap items-center gap-x-2 gap-y-0.5">
					<input
						type="checkbox"
						role="switch"
						data-work-toggle="plan_review"
						checked={activeProfile.plan_review}
						on:change={(e) => setFlag('plan_review', Boolean((e.currentTarget ?? e.target)?.checked))}
					/>
					<span class="font-medium">规划后先审阅再开发</span>
					<span class="work-hint">
						{activeProfile.dual_plan
							? '双方案并行已开启，当前由双方案对比合成替代单规划审阅。'
							: '审阅员核查或修订规划、明确前后端契约后再开始开发。'}
					</span>
				</label>

				<label class="flex cursor-pointer flex-wrap items-center gap-x-2 gap-y-0.5">
					<input
						type="checkbox"
						role="switch"
						data-work-toggle="dual_plan"
						checked={activeProfile.dual_plan}
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
						checked={activeProfile.plan_approval}
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
						checked={activeProfile.ui_review}
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
						checked={activeProfile.split_dev}
						on:change={(e) => setFlag('split_dev', Boolean((e.currentTarget ?? e.target)?.checked))}
					/>
					<span class="font-medium">前后端分拆开发</span>
					<span class="work-hint">
						开启后后端与前端拆为独立环节，可分别自由指定执行器（纯后端需求自动跳过前端）；关闭则全栈开发。
					</span>
				</label>

				<label class="flex cursor-pointer flex-wrap items-center gap-x-2 gap-y-0.5">
					<input
						type="checkbox"
						role="switch"
						data-work-toggle="codex_review"
						checked={activeProfile.codex_review}
						on:change={(e) => setFlag('codex_review', Boolean((e.currentTarget ?? e.target)?.checked))}
					/>
					<span class="font-medium">交付前 Codex 2 轮独立审查</span>
					<span class="work-hint">
						合并主分支前由 Codex 只读复核最多 2 轮并自动修复；关闭则由「审阅修复」把关后直接发布。
					</span>
				</label>
			</div>

			{#if selfReviewHint}
				<div class="work-warn" role="status" data-work-self-review-warn>{selfReviewHint}</div>
			{/if}

			{#each response.steps_meta as step (step.key)}
				{@const config = activeProfile.steps[step.key]}
				{@const candidates = chainCandidates(runnerNames, config.fallback, config.runner)}
				{@const active = stepActive(step.key, activeProfile)}
				{@const displayLabel = stepLabel(step.key, step.label, activeProfile)}
				<div class="work-row" class:inactive={!active} data-work-step={step.key}>
					<div class="grid gap-1">
						<div class="font-medium">{displayLabel}</div>
						<span class="work-hint">{stepRoleNote(step.key, activeProfile)}</span>
					</div>
					<div class="grid min-w-0 gap-2">
						<label class="flex flex-wrap items-center gap-2">
							<span class="work-hint">首选执行器</span>
							<select
								class="work-button"
								aria-label={`${displayLabel}首选执行器`}
								value={config.runner}
								on:change={(e) => {
									if (draft) {
										draft = setWorkStepRunner(draft, step.key, e.currentTarget.value, activePreset);
									}
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
									aria-label={`添加${displayLabel}兜底`}
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
			命令用法：<code>/work 需求</code> 按「默认工作流」执行；<code>/work 深度 需求</code> 按「深度多模型」执行；<code>/work 快速 需求</code> 按「快速精简」执行；<code>/work cchclaude 需求</code> 单次锁定对应家族执行器（不自动兜底）。
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
	.work-preset-card {
		display: grid;
		gap: 0.45rem;
		width: 100%;
		text-align: left;
		padding: 0.6rem 0.75rem;
		border-radius: 0.7rem;
		border: 1px solid rgb(100 116 139 / 0.28);
		background: rgb(255 255 255 / 0.45);
		transition: border-color 140ms ease, background-color 140ms ease;
	}
	:global(.dark) .work-preset-card {
		background: rgb(15 23 42 / 0.35);
	}
	.work-preset-card:hover {
		border-color: rgb(59 130 246 / 0.55);
	}
	.work-preset-card.active {
		border-color: rgb(37 99 235 / 0.85);
		background: rgb(59 130 246 / 0.08);
	}
	:global(.dark) .work-preset-card.active {
		border-color: rgb(96 165 250 / 0.8);
		background: rgb(59 130 246 / 0.14);
	}
	.work-preset-head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem;
	}
	.work-preset-title {
		display: inline-flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.8125rem;
	}
	.work-cmd {
		font-size: 0.72rem;
		padding: 0.08rem 0.38rem;
		border-radius: 0.35rem;
		background: rgb(100 116 139 / 0.14);
	}
	.work-preset-state {
		font-size: 0.72rem;
		color: #64748b;
	}
	.work-preset-state.selected {
		color: #2563eb;
		font-weight: 600;
	}
	:global(.dark) .work-preset-state.selected {
		color: #93c5fd;
	}
	.work-editor-head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem;
		padding-top: 0.35rem;
		border-top: 1px dashed rgb(100 116 139 / 0.3);
	}
	.work-warn {
		border-radius: 0.5rem;
		padding: 0.45rem 0.65rem;
		font-size: 0.75rem;
		color: #92400e;
		background: rgb(245 158 11 / 0.12);
		border: 1px solid rgb(245 158 11 / 0.3);
	}
	:global(.dark) .work-warn {
		color: #fcd34d;
		background: rgb(245 158 11 / 0.14);
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
