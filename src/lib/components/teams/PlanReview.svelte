<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	import type { Team, TeamExecutor, TeamsMeta } from '$lib/apis/teams';
	import RunnerStatus from './RunnerStatus.svelte';
	import StatusChip from './StatusChip.svelte';
	import TeamAvatar from './TeamAvatar.svelte';
	import { avatarKind, EXECUTOR_OPTIONS, KIND_LABEL, memberRunner, runnerLabel } from './model';

	/**
	 * The lead's plan, shown before anything runs: who does what (each member is a HaloWebUI
	 * assistant template with a task kind), which runner each member starts on and what will
	 * actually run it now, and the dependent tasks. Approve, change runners, ask for a new plan,
	 * or cancel.
	 */
	export let team: Team;
	export let busy = false;
	export let parallelCap = 2;
	export let registry: TeamsMeta['registry'] | null = null;
	export let registryError = '';
	export let checking = false;

	const dispatch = createEventDispatcher<{
		approve: void;
		replan: string;
		cancel: void;
		executor: { name: string; executor: TeamExecutor; source: 'user' | 'auto' };
		recheck: void;
	}>();
	let feedback = '';
	let showFeedback = false;

	$: plan = team.plan;
	$: layers = plan?.layers?.length ? plan.layers : plan ? [plan.tasks.map((t) => t.key)] : [];
	$: byKey = new Map((plan?.tasks ?? []).map((t) => [t.key, t]));
	$: widest = plan?.widest_layer ?? Math.max(0, ...layers.map((l) => l.length));
	$: parallel = Math.min(widest, parallelCap);
	$: editable = team.status === 'plan_ready' || team.status === 'start_failed';
	$: runnersBy = new Map((registry?.runners ?? []).map((r) => [r.name, r]));
	$: order = registry?.order?.length ? registry.order : EXECUTOR_OPTIONS.map((o) => o.value);
	$: kindLabel = (kind?: string) =>
		registry?.kinds.find((k) => k.value === kind)?.label ?? KIND_LABEL[kind ?? ''] ?? '';
	$: actuals = (plan?.members ?? []).map((m) => memberRunner(m).actual).filter(Boolean) as string[];
	$: plannedRunners = [...new Set(actuals)];
	$: fallbackCount = (plan?.members ?? []).filter((m) => memberRunner(m).changed).length;
	$: blocked = (plan?.members ?? []).filter((m) => memberRunner(m).actual === null).length;
	$: lead = plan?.lead_model;
	$: memberCount = plan?.members.length ?? 0;

	const optionLabel = (name: string) => {
		const info = runnersBy.get(name as TeamExecutor);
		const base =
			name === 'hermes' ? 'Hermes 代理' : `${name}${info?.engine ? ` · ${info.engine}` : ''}`;
		return info && !info.available ? `${base}（不可用）` : base;
	};

	const sourceText = (m: { executor_source?: string; kind?: string; recommended?: string }) =>
		m.executor_source === 'user'
			? '你手动指定'
			: m.executor_source === 'goal'
				? '目标里点名'
				: `按「${kindLabel(m.kind) || '任务类型'}」推荐`;
</script>

{#if plan}
	<div class="flex flex-col gap-6" data-plan-review>
		<section class="flex flex-col gap-2">
			{#if plan.summary}
				<p
					class="max-w-3xl text-[15px] leading-relaxed text-gray-800 dark:text-gray-200 whitespace-pre-wrap"
				>
					{plan.summary}
				</p>
			{/if}
			{#if lead?.model}
				<p class="text-xs text-gray-500" data-lead-model>
					负责人用 <span class="font-mono text-gray-700 dark:text-gray-300">{lead.model}</span
					>{lead.label ? `（${lead.label}）` : ''}做的计划{#if lead.fallback_from?.length}，<span
							class="text-amber-700 dark:text-amber-300"
							>{lead.fallback_from.join('、')} 没有回答，改用了 {lead.model}</span
						>{/if}
				</p>
			{/if}
		</section>

		<dl
			class="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-gray-100 bg-gray-100 text-xs sm:grid-cols-4 dark:border-gray-850 dark:bg-gray-850"
		>
			<div class="bg-white px-4 py-3 dark:bg-gray-900">
				<dt class="text-gray-500">成员</dt>
				<dd class="mt-0.5 text-lg font-semibold tabular-nums text-gray-900 dark:text-gray-100">
					1 + {memberCount}
				</dd>
				<dd class="text-gray-400">负责人 + 成员</dd>
			</div>
			<div class="bg-white px-4 py-3 dark:bg-gray-900">
				<dt class="text-gray-500">任务</dt>
				<dd class="mt-0.5 text-lg font-semibold tabular-nums text-gray-900 dark:text-gray-100">
					{plan.tasks.length}
				</dd>
				<dd class="text-gray-400">{layers.length} 步</dd>
			</div>
			<div class="bg-white px-4 py-3 dark:bg-gray-900">
				<dt class="text-gray-500">同时执行</dt>
				<dd class="mt-0.5 text-lg font-semibold tabular-nums text-gray-900 dark:text-gray-100">
					最多 {parallel}
				</dd>
				<dd class="text-gray-400">
					{widest > parallelCap
						? `可并行 ${widest} 个，本机上限 ${parallelCap}`
						: `本机上限 ${parallelCap}`}
				</dd>
			</div>
			<div class="bg-white px-4 py-3 dark:bg-gray-900">
				<dt class="text-gray-500">执行来源</dt>
				<dd
					class="mt-0.5 truncate font-mono text-[15px] font-semibold text-gray-900 dark:text-gray-100"
					title={plannedRunners.map(runnerLabel).join(' + ')}
				>
					{plannedRunners.map(runnerLabel).join(' + ') || '—'}
				</dd>
				<dd class={fallbackCount ? 'text-amber-700 dark:text-amber-300' : 'text-gray-400'}>
					{blocked
						? `${blocked} 位成员没有可用的执行来源`
						: fallbackCount
							? `${fallbackCount} 位成员已改用备选`
							: '都用推荐的执行来源'}
				</dd>
			</div>
		</dl>

		<section>
			<h3 class="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-100">成员分工</h3>
			<ul class="grid gap-3 md:grid-cols-2">
				<li
					class="flex items-center gap-3 rounded-2xl border border-indigo-200/70 bg-indigo-50/50 p-3 dark:border-indigo-900/60 dark:bg-indigo-950/25"
				>
					<TeamAvatar kind="lead" size={38} />
					<div class="min-w-0">
						<div class="text-sm font-semibold">
							team-lead <span class="font-normal text-gray-500">· 负责人</span>
						</div>
						<div class="text-xs leading-relaxed text-gray-500">
							拆分任务、批准后按依赖调度成员，全部完成后写结论{lead?.model
								? `（${lead.model}）`
								: ''}
						</div>
					</div>
				</li>
				{#each plan.members as member (member.name)}
					{@const d = memberRunner(member)}
					<li
						class="flex min-w-0 flex-col gap-3 rounded-2xl border border-gray-100 p-3 dark:border-gray-850"
						data-plan-member={member.name}
					>
						<div class="flex items-start gap-3">
							<TeamAvatar kind={avatarKind(member)} size={38} />
							<div class="min-w-0 flex-1">
								<div class="flex min-w-0 items-baseline gap-1.5">
									<span class="truncate text-sm font-semibold text-gray-900 dark:text-gray-100"
										>{member.name}</span
									>
									<span class="shrink-0 text-xs text-gray-500">{member.role}</span>
								</div>
								<div class="mt-1 flex flex-wrap gap-1.5 text-[11px]">
									{#if member.assistant}
										<span
											class="inline-flex max-w-full items-center gap-1 rounded-md bg-orange-50 px-1.5 py-0.5 text-orange-800 dark:bg-orange-950/40 dark:text-orange-200"
											title={member.assistant.description
												? `助手模板：${member.assistant.description}`
												: '助手模板'}
											data-assistant={member.assistant.id}
											><span aria-hidden="true">{member.assistant.emoji}</span><span
												class="truncate">{member.assistant.name}</span
											></span
										>
									{:else}
										<span
											class="rounded-md bg-gray-100 px-1.5 py-0.5 text-gray-500 dark:bg-gray-850"
											title="没有合适的助手模板，负责人自定义了这个角色">自定义角色</span
										>
									{/if}
									{#if member.kind}
										<span
											class="rounded-md bg-gray-100 px-1.5 py-0.5 text-gray-600 dark:bg-gray-850 dark:text-gray-300"
											>{kindLabel(member.kind)}</span
										>
									{/if}
								</div>
								{#if member.focus}<p
										class="mt-1.5 text-xs leading-relaxed text-gray-500 line-clamp-2"
									>
										{member.focus}
									</p>{/if}
							</div>
						</div>
						<div class="mt-auto rounded-xl bg-gray-50 px-3 py-2.5 dark:bg-gray-850/60">
							<div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5">
								<label class="shrink-0 text-xs text-gray-500" for="runner-{member.name}"
									>执行来源</label
								>
								<select
									id="runner-{member.name}"
									class="min-w-0 max-w-[13rem] flex-1 truncate rounded-lg border border-gray-200 bg-white py-1 pl-2 pr-7 text-xs text-gray-900 transition focus:border-sky-400 focus:outline-none disabled:opacity-60 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
									value={member.executor}
									disabled={!editable || busy}
									on:change={(e) =>
										dispatch('executor', {
											name: member.name,
											executor:
												EXECUTOR_OPTIONS.find((o) => o.value === e.currentTarget.value)?.value ??
												'hermes',
											source: 'user'
										})}
								>
									{#each order as name}
										<option value={name}
											>{optionLabel(name)}{member.recommended === name ? ' · 推荐' : ''}</option
										>
									{/each}
								</select>
								<span class="min-w-0 truncate text-[11px] text-gray-400">{sourceText(member)}</span>
								{#if member.executor_source === 'user' && editable}
									<button
										type="button"
										class="ml-auto shrink-0 rounded-md px-1.5 py-0.5 text-[11px] text-sky-700 transition hover:bg-sky-50 disabled:opacity-50 dark:text-sky-300 dark:hover:bg-sky-950/40"
										disabled={busy}
										on:click={() =>
											dispatch('executor', {
												name: member.name,
												executor: member.executor,
												source: 'auto'
											})}
										title="按任务类型重新自动选择">恢复自动</button
									>
								{/if}
							</div>
							{#if d.actual === null}
								<p
									class="mt-1.5 text-[11px] leading-relaxed text-red-700 dark:text-red-300"
									role="alert"
								>
									{runnerLabel(d.chosen)} 之后的执行来源都不可用：{d.reason}
								</p>
							{:else if d.changed}
								<p
									class="mt-1.5 text-[11px] leading-relaxed text-amber-800 dark:text-amber-200"
									data-runner-fallback
								>
									实际将由 <b class="font-mono">{runnerLabel(d.actual)}</b> 执行 · {d.reason ||
										`${runnerLabel(d.chosen)} 现在不可用`}
								</p>
							{:else if runnersBy.get(d.chosen)?.available}
								<p class="mt-1.5 text-[11px] text-emerald-700 dark:text-emerald-300">
									{runnerLabel(d.chosen)} 可用
								</p>
							{/if}
						</div>
					</li>
				{/each}
			</ul>
			<p class="mt-2 text-[11px] leading-relaxed text-gray-400">
				执行来源不可用时会沿 {order.map(runnerLabel).join(' → ')} 往后兜底，你手动选的也一样；每次改派都会在任务上记下原因。
			</p>
		</section>

		<RunnerStatus
			{registry}
			{checking}
			error={registryError}
			on:check={() => dispatch('recheck')}
		/>

		<section>
			<h3 class="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-100">任务和依赖</h3>
			<ol class="flex flex-col gap-4">
				{#each layers as layer, depth}
					<li>
						<div class="mb-1.5 flex items-center gap-2 text-xs text-gray-500">
							<span
								class="grid size-5 place-items-center rounded-full bg-gray-100 font-mono text-[10px] font-semibold text-gray-600 dark:bg-gray-850 dark:text-gray-300"
								>{depth + 1}</span
							>
							第 {depth + 1} 步{layer.length > 1 ? ` · ${layer.length} 个任务可并行` : ''}
						</div>
						<ul class="grid gap-2 sm:grid-cols-2">
							{#each layer as key}
								{@const task = byKey.get(key)}
								{#if task}
									<li
										class="min-w-0 rounded-2xl border border-gray-100 px-3 py-2.5 dark:border-gray-850"
									>
										<div class="flex min-w-0 items-center gap-2 text-xs">
											<span class="font-mono font-semibold text-gray-500">#{task.key}</span>
											<span class="min-w-0 truncate text-gray-500">{task.member}</span>
											{#if task.depends_on.length}
												<span class="ml-auto shrink-0"
													><StatusChip
														status="waiting_deps"
														label={`依赖 ${task.depends_on.map((d) => '#' + d).join('、')}`}
													/></span
												>
											{/if}
										</div>
										<div
											class="mt-1 break-words text-sm font-medium text-gray-900 dark:text-gray-100"
										>
											{task.title}
										</div>
										<details class="mt-1">
											<summary
												class="cursor-pointer select-none text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
												>说明</summary
											>
											<p
												class="mt-1 whitespace-pre-wrap break-words text-xs leading-relaxed text-gray-600 dark:text-gray-400"
											>
												{task.description}
											</p>
										</details>
									</li>
								{/if}
							{/each}
						</ul>
					</li>
				{/each}
			</ol>
		</section>

		{#if editable}
			<div
				class="sticky bottom-0 -mx-1 flex flex-col gap-2 border-t border-gray-100 bg-white/95 px-1 pb-1 pt-3 backdrop-blur dark:border-gray-850 dark:bg-gray-900/95"
			>
				<p class="text-xs text-gray-500">
					批准后成员才开始工作（普通聊天不会自动启动多代理）。每个成员会消耗模型额度；可以随时暂停派发或停止。
				</p>
				<div class="flex flex-wrap items-center gap-2">
					<button
						type="button"
						class="rounded-xl bg-gray-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-800 active:scale-[0.98] disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white"
						disabled={busy}
						on:click={() => dispatch('approve')}>{busy ? '处理中…' : '批准并开始'}</button
					>
					<button
						type="button"
						class="rounded-xl bg-gray-100 px-4 py-2 text-sm text-gray-700 transition hover:bg-gray-200 active:scale-[0.98] disabled:opacity-50 dark:bg-gray-850 dark:text-gray-200 dark:hover:bg-gray-800"
						disabled={busy}
						aria-expanded={showFeedback}
						on:click={() => (showFeedback = !showFeedback)}>按意见重新规划</button
					>
					<button
						type="button"
						class="rounded-xl px-4 py-2 text-sm text-gray-500 transition hover:text-red-600 disabled:opacity-50"
						disabled={busy}
						on:click={() => dispatch('cancel')}>取消</button
					>
				</div>
				{#if showFeedback}
					<form
						class="flex flex-col gap-1.5"
						on:submit|preventDefault={() => dispatch('replan', feedback)}
					>
						<label class="text-xs text-gray-600 dark:text-gray-300" for="team-replan"
							>你希望怎么改？</label
						>
						<textarea
							id="team-replan"
							bind:value={feedback}
							rows="3"
							maxlength="2000"
							class="w-full rounded-xl border border-gray-200 bg-white px-2.5 py-2 text-sm outline-none transition focus:border-sky-400 dark:border-gray-800 dark:bg-gray-900"
							placeholder="例如：再加一个测试成员；前端交给 codex；把评审放到最后"
						/>
						<button
							type="submit"
							class="self-start rounded-xl bg-sky-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-sky-700 disabled:opacity-50"
							disabled={busy}>让负责人重新规划</button
						>
					</form>
				{/if}
			</div>
		{/if}
	</div>
{/if}
