<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	import type { HermesModel, Team, TeamExecutor, TeamPlanMember, TeamsMeta } from '$lib/apis/teams';
	import AssistantChoiceTag from './AssistantChoiceTag.svelte';
	import RunnerStatus from './RunnerStatus.svelte';
	import StatusChip from './StatusChip.svelte';
	import TeamAvatar from './TeamAvatar.svelte';
	import { avatarKind, EXECUTOR_OPTIONS, KIND_LABEL, memberRunner, runnerLabel } from './model';

	/**
	 * The lead's plan, shown before anything runs: who does what (each member's assistant — one
	 * of the user's, a template, an upgrade or a new one, written to the library only on approval —
	 * and its task kind), which runner each member starts on and what will actually run it now,
	 * and the dependent tasks. Approve, change runners, ask for a new plan, or cancel.
	 */
	export let team: Team;
	export let busy = false;
	export let parallelCap = 2;
	export let registry: TeamsMeta['registry'] | null = null;
	export let registryError = '';
	export let checking = false;
	/** Git repositories the team could work in instead (from the teams meta). */
	export let projects: { path: string; name: string }[] = [];
	/** Models a member running on Hermes can use (from the teams meta). */
	export let models: HermesModel[] = [];

	const dispatch = createEventDispatcher<{
		approve: void;
		replan: string;
		/** Plan again in another place: a repository path, or "none" for a fresh directory. */
		'replan-project': string;
		cancel: void;
		executor: { name: string; executor: TeamExecutor; source: 'user' | 'auto' };
		/** source auto: back to the lead's recommendation. */
		model: { name: string; model: string; source: 'user' | 'auto' };
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
	// 助手库: what the lead proposes to write, and (after a failed start) what was already applied
	$: proposals = new Map((plan?.assistant_proposals ?? []).map((p) => [p.key, p]));
	$: applied = plan?.assistants_applied?.members ?? null;
	$: writes = applied ? [] : (plan?.assistant_proposals ?? []).filter((p) => p.action !== 'temporary');
	$: updates = writes.filter((p) => p.action === 'update').length;
	$: creates = writes.filter((p) => p.action === 'create').length;
	$: mayWrite = plan?.assistant_library?.may_write ?? true;
	let openPrompt: string | null = null;

	const optionLabel = (name: string) => {
		const info = runnersBy.get(name as TeamExecutor);
		const base =
			name === 'hermes' ? 'Hermes 代理' : `${name}${info?.engine ? ` · ${info.engine}` : ''}`;
		return info && !info.available ? `${base}（不可用）` : base;
	};

	// The model matters when Hermes does the member's work: its own runner, or where it fell back to.
	const runsOnHermes = (m: TeamPlanMember, actual: string | null | undefined) =>
		m.executor === 'hermes' || actual === 'hermes';
	const modelOptions = (m: TeamPlanMember): HermesModel[] =>
		m.model && !models.some((o) => o.model === m.model)
			? [...models, { model: m.model, default: false, hint: '' }]
			: models;
	const modelHint = (name?: string) => models.find((o) => o.model === name)?.hint ?? '';
	const modelSourceText = (m: TeamPlanMember) =>
		m.model_source === 'user'
			? '你手动指定'
			: m.model_source === 'lead'
				? '负责人推荐'
				: 'Hermes 默认模型';

	const sourceText = (m: { executor_source?: string; kind?: string; recommended?: string }) =>
		m.executor_source === 'user'
			? '你手动指定'
			: m.executor_source === 'goal'
				? '目标里点名'
				: `按「${kindLabel(m.kind) || '任务类型'}」推荐`;
</script>

{#if plan}
	<div class="flex flex-col gap-6" data-plan-review>
		<section class="flex items-start gap-3.5">
			<TeamAvatar kind="lead" status="done" size={40} />
			<div class="flex min-w-0 flex-col gap-1.5">
				<div class="flex items-center gap-2">
					<span class="tm-display text-base font-semibold text-gray-900 dark:text-gray-50"
						>负责人的计划</span
					>
					<StatusChip
						status={team.status === 'plan_ready'
							? 'waiting_user'
							: team.status === 'cancelled'
								? 'stopped'
								: 'failed'}
						label={team.status === 'plan_ready'
							? '等你批准'
							: team.status === 'cancelled'
								? '已取消'
								: '启动失败，可以重新批准'}
					/>
					{#if plan.effort === 'quick'}
						<span
							class="whitespace-nowrap rounded-full px-2 py-[3px] text-[11px] font-medium leading-none text-gray-600 ring-1 ring-inset ring-gray-200 dark:text-gray-300 dark:ring-gray-700"
							title="简单问题：一个成员直接查清作答，几分钟出结果"
							data-plan-effort="quick">快答</span
						>
					{/if}
				</div>
				{#if plan.summary}
					<p
						class="max-w-3xl whitespace-pre-wrap text-[15px] leading-relaxed text-gray-700 dark:text-gray-200"
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
			</div>
		</section>

		<section
			class="tm-card-quiet flex flex-col gap-1.5 px-4 py-3 text-[13px] text-gray-700 dark:text-gray-200"
			data-plan-project={plan.project?.path ?? 'none'}
		>
			<div class="flex flex-wrap items-center gap-x-2 gap-y-1.5">
				<svg
					class="size-4 shrink-0 text-gray-400"
					viewBox="0 0 16 16"
					fill="none"
					aria-hidden="true"
					><path
						d="M2 4.5A1.5 1.5 0 0 1 3.5 3h2.6l1.4 1.5h5A1.5 1.5 0 0 1 14 6v5.5a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 11.5v-7Z"
						stroke="currentColor"
						stroke-width="1.3"
						stroke-linejoin="round"
					/></svg
				>
				{#if plan.project}
					<span
						>在项目 <b class="font-semibold text-gray-900 dark:text-gray-50">{plan.project.name}</b>
						里做</span
					>
					<span class="font-mono text-xs text-gray-500" title={plan.project.path}
						>{plan.project.path}</span
					>
					{#if plan.project.auto}
						<span
							class="rounded-full bg-sky-50 px-2 py-0.5 text-[11px] text-sky-700 dark:bg-sky-950 dark:text-sky-300"
							>目标里点名了它</span
						>
					{/if}
				{:else}
					<span>在一个新的工作目录里做</span>
				{/if}
				{#if editable}
					<span class="ml-auto flex items-center gap-2">
						{#if plan.project}
							<button
								type="button"
								class="tm-btn-ghost !py-1 !text-xs"
								disabled={busy}
								on:click={() => dispatch('replan-project', 'none')}
								data-plan-project-none>改在新目录重做计划</button
							>
						{:else if projects.length}
							<label class="flex items-center gap-1.5 text-xs text-gray-500">
								换到项目里重做
								<select
									class="plan-project-select rounded-lg border bg-transparent px-2 py-1 text-xs tm-hairline"
									disabled={busy}
									on:change={(e) => {
										const value = e.currentTarget.value;
										if (value) dispatch('replan-project', value);
									}}
								>
									<option value="">选择项目…</option>
									{#each projects as p (p.path)}
										<option value={p.path}>{p.name}</option>
									{/each}
								</select>
							</label>
						{/if}
					</span>
				{/if}
			</div>
			{#if plan.project}
				<p class="text-xs leading-relaxed text-gray-500 dark:text-gray-400">
					批准后团队从 <span class="font-mono">{plan.project.branch || 'HEAD'}</span>
					{plan.project.head ? `（${plan.project.head}）` : ''}开一个自己的分支，在独立的 worktree
					里改，不碰你正在用的工作区；每个任务完成自动提交。结束后在「变更」里看差异，合并、推送都由你来点。{#if plan.project.auto}
						只是提问、做分析也可以留在项目里（成员能读到代码）；团队结束时如果没有改动任何文件，分支会自动清理。{/if}{#if plan.project.dirty}<span
							class="text-amber-700 dark:text-amber-300"
						>
							你的工作区现在有未提交的改动：不影响团队，合并前需要先提交。</span
						>{/if}
				</p>
			{/if}
		</section>

		<dl class="stats tm-card grid grid-cols-2 overflow-hidden text-xs sm:grid-cols-4">
			<div class="stat px-4 py-3.5">
				<dt class="text-gray-500">成员</dt>
				<dd class="tm-num mt-1 text-xl font-semibold text-gray-900 dark:text-gray-50">
					1 + {memberCount}
				</dd>
				<dd class="text-gray-400">负责人 + 成员</dd>
			</div>
			<div class="stat px-4 py-3.5">
				<dt class="text-gray-500">任务</dt>
				<dd class="tm-num mt-1 text-xl font-semibold text-gray-900 dark:text-gray-50">
					{plan.tasks.length}
				</dd>
				<dd class="text-gray-400">{layers.length} 步</dd>
			</div>
			<div class="stat px-4 py-3.5">
				<dt class="text-gray-500">同时执行</dt>
				<dd class="tm-num mt-1 text-xl font-semibold text-gray-900 dark:text-gray-50">
					最多 {parallel}
				</dd>
				<dd class="text-gray-400">
					{widest > parallelCap
						? `可并行 ${widest} 个，本机上限 ${parallelCap}`
						: `本机上限 ${parallelCap}`}
				</dd>
			</div>
			<div class="stat px-4 py-3.5">
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
			<h3 class="tm-eyebrow mb-3">成员分工</h3>
			{#if writes.length || (!mayWrite && plan.assistant_proposals?.length)}
				<p class="mb-3 text-xs leading-relaxed text-gray-500" data-assistant-writes>
					{#if writes.length}
						批准后才写入助手库：{[
							updates ? `升级 ${updates} 个` : '',
							creates ? `新建 ${creates} 个（默认不在模型菜单里显示）` : ''
						]
							.filter(Boolean)
							.join('、')}；重新规划或取消不会写入。
					{:else}
						你没有保存助手的权限：负责人设计的设定只在这次协作里用。
					{/if}
				</p>
			{/if}
			<ul class="grid gap-3 md:grid-cols-2">
				<li class="lead tm-card flex items-center gap-3 self-start px-3.5 py-3 md:col-span-2">
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
						class="tm-card tm-hover flex min-w-0 flex-col gap-3 p-3.5"
						data-plan-member={member.name}
					>
						<div class="flex items-start gap-3">
							<TeamAvatar kind={avatarKind(member)} size={38} />
							<div class="min-w-0 flex-1">
								<div class="flex min-w-0 items-baseline gap-1.5">
									<span
										class="max-w-[70%] shrink-0 truncate text-sm font-semibold text-gray-900 dark:text-gray-100"
										title={member.name}>{member.name}</span
									>
									<span class="min-w-0 truncate text-xs text-gray-500" title={member.role}
										>{member.role}</span
									>
								</div>
								<div class="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
									{#if member.assistant}
										<span
											class="inline-flex max-w-full items-center gap-1 rounded-md bg-orange-500/10 px-1.5 py-0.5 text-orange-800 ring-1 ring-inset ring-orange-500/20 dark:text-orange-200"
											title={member.assistant.description
												? `助手：${member.assistant.description}`
												: '助手'}
											data-assistant={member.assistant.id ||
												member.assistant.ref ||
												member.assistant.proposal ||
												member.assistant.name}
											><span aria-hidden="true">{member.assistant.emoji ?? ''}</span><span
												class="truncate">{member.assistant.name}</span
											></span
										>
										<AssistantChoiceTag
											action={applied?.[member.name]?.action ?? member.assistant.action}
										/>
									{:else}
										<span
											class="rounded-md bg-gray-500/10 px-1.5 py-0.5 text-gray-500"
											title="没有合适的助手模板，负责人自定义了这个角色">自定义角色</span
										>
									{/if}
									{#if member.kind}
										<span
											class="rounded-md bg-gray-500/10 px-1.5 py-0.5 text-gray-600 dark:text-gray-300"
											>{kindLabel(member.kind)}</span
										>
									{/if}
								</div>
								{#if member.focus}
									<!-- a div: the global `li p { display: inline }` would undo the clamp -->
									<div
										class="mt-1.5 text-xs leading-relaxed text-gray-500 line-clamp-2"
										title={member.focus}
									>
										{member.focus}
									</div>
								{/if}
								{#if member.assistant}
									{@const a = member.assistant}
									{@const note = applied?.[member.name]?.note || a.note}
									{@const proposal = a.proposal ? proposals.get(a.proposal) : undefined}
									{#if a.reason || note || proposal}
										<div class="mt-1 text-[11px] leading-relaxed text-gray-500" data-assistant-why>
											{#if a.reason}<span>{a.reason}</span>{/if}
											{#if note}<span class="text-amber-700 dark:text-amber-300">{note}</span>{/if}
											{#if proposal}
												<button
													type="button"
													class="text-sky-700 hover:underline dark:text-sky-300"
													aria-expanded={openPrompt === member.name}
													on:click={() =>
														(openPrompt = openPrompt === member.name ? null : member.name)}
													data-assistant-prompt-toggle
													>{openPrompt === member.name
														? '收起设定'
														: proposal.ref
															? '查看升级后的设定'
															: '查看设定'}</button
												>
											{/if}
										</div>
										{#if proposal && openPrompt === member.name}
											<div class="prompt-box mt-1.5 rounded-lg px-2.5 py-2" data-assistant-prompt>
												{#if proposal.change}
													<div class="mb-1 text-[11px] text-violet-700 dark:text-violet-300">
														{proposal.ref ? '这次升级' : '能做什么'}：{proposal.change}
													</div>
												{/if}
												<pre
													class="tm-scroll max-h-48 overflow-y-auto whitespace-pre-wrap break-words font-sans text-[11px] leading-relaxed text-gray-600 dark:text-gray-300">{proposal.system_prompt}</pre>
											</div>
										{/if}
									{/if}
								{/if}
							</div>
						</div>
						<div class="runner-box mt-auto rounded-xl px-3 py-2.5">
							<div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5">
								<label class="shrink-0 text-xs text-gray-500" for="runner-{member.name}"
									>执行来源</label
								>
								<select
									id="runner-{member.name}"
									class="compact-select min-w-0 max-w-[16rem] flex-1 truncate rounded-lg border border-gray-200 bg-white py-1 pl-2 pr-7 text-xs text-gray-900 transition focus:border-sky-400 focus:outline-none disabled:opacity-60 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
									value={member.executor}
									disabled={!editable || busy || member.kind === 'image'}
									title={member.kind === 'image'
										? '生图成员只能由 Hermes 执行：gpt-image 是 Hermes 的生图工具'
										: ''}
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
								<span class="min-w-0 truncate text-[11px] text-gray-400"
									>{member.kind === 'image' ? '用 gpt-image 生图，只能由 Hermes 执行' : sourceText(member)}</span
								>
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
								<div
									class="mt-1.5 text-[11px] leading-relaxed text-red-700 dark:text-red-300"
									role="alert"
								>
									{runnerLabel(d.chosen)} 之后的执行来源都不可用：{d.reason}
								</div>
							{:else if d.changed}
								<div
									class="mt-1.5 text-[11px] leading-relaxed text-amber-800 dark:text-amber-200"
									data-runner-fallback
								>
									实际将由 <b class="font-mono">{runnerLabel(d.actual)}</b> 执行 · {d.reason ||
										`${runnerLabel(d.chosen)} 现在不可用`}
								</div>
							{:else if runnersBy.get(d.chosen)?.available}
								<div class="mt-1.5 text-[11px] text-emerald-700 dark:text-emerald-300">
									{runnerLabel(d.chosen)} 可用
								</div>
							{/if}
							{#if runsOnHermes(member, d.actual) && (models.length || member.model)}
								<div
									class="tm-hairline mt-2 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5 border-t pt-2"
									data-member-model={member.model ?? ''}
								>
									<label class="shrink-0 text-xs text-gray-500" for="model-{member.name}"
										>模型</label
									>
									{#if models.length}
										<select
											id="model-{member.name}"
											class="compact-select min-w-0 max-w-[16rem] flex-1 truncate rounded-lg border border-gray-200 bg-white py-1 pl-2 pr-7 font-mono text-xs text-gray-900 transition focus:border-sky-400 focus:outline-none disabled:opacity-60 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
											value={member.model ?? ''}
											disabled={!editable || busy}
											on:change={(e) =>
												dispatch('model', {
													name: member.name,
													model: e.currentTarget.value,
													source: 'user'
												})}
										>
											{#each modelOptions(member) as option (option.model)}
												<option value={option.model} title={option.hint}
													>{option.model}{option.model === member.model_recommended
														? ' · 推荐'
														: option.default
															? ' · 默认'
															: ''}</option
												>
											{/each}
										</select>
									{:else}
										<span class="font-mono text-xs text-gray-700 dark:text-gray-200"
											>{member.model}</span
										>
									{/if}
									<span class="min-w-0 truncate text-[11px] text-gray-400"
										>{modelSourceText(member)}</span
									>
									{#if member.model_source === 'user' && editable && member.model_recommended && member.model_recommended !== member.model}
										<button
											type="button"
											class="ml-auto shrink-0 rounded-md px-1.5 py-0.5 text-[11px] text-sky-700 transition hover:bg-sky-50 disabled:opacity-50 dark:text-sky-300 dark:hover:bg-sky-950/40"
											disabled={busy}
											on:click={() =>
												dispatch('model', { name: member.name, model: '', source: 'auto' })}
											title="用负责人推荐的 {member.model_recommended}"
											data-model-reset>恢复推荐</button
										>
									{/if}
								</div>
								{#if modelHint(member.model)}
									<div class="mt-1 text-[11px] leading-relaxed text-gray-400">
										{modelHint(member.model)}
									</div>
								{/if}
							{/if}
						</div>
					</li>
				{/each}
			</ul>
			<p class="mt-2 text-[11px] leading-relaxed text-gray-400">
				执行来源不可用时会沿 {order.map(runnerLabel).join(' → ')} 往后兜底，你手动选的也一样；每次改派都会在任务上记下原因。由
				Hermes 执行的成员用上面选的模型（负责人按分工推荐，可以改）。
			</p>
		</section>

		<RunnerStatus
			{registry}
			{checking}
			error={registryError}
			on:check={() => dispatch('recheck')}
		/>

		<section>
			<h3 class="tm-eyebrow mb-3">任务和依赖</h3>
			<ol class="steps flex flex-col gap-5">
				{#each layers as layer, depth}
					<li class="step relative pl-9">
						<div class="mb-2 flex items-center gap-2 text-xs text-gray-500">
							<span
								class="step-node tm-num absolute left-0 top-0 grid size-6 place-items-center rounded-full text-[11px] font-semibold"
								>{depth + 1}</span
							>
							第 {depth + 1} 步{layer.length > 1 ? ` · ${layer.length} 个任务可并行` : ''}
						</div>
						<ul class="grid gap-2 sm:grid-cols-2">
							{#each layer as key}
								{@const task = byKey.get(key)}
								{#if task}
									<li class="tm-card min-w-0 px-3.5 py-3">
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
			<div class="dock-wrap sticky -bottom-6 z-10 -mx-2 px-2 pb-9 pt-6">
				<div class="dock tm-glass flex flex-col gap-2 rounded-2xl px-4 py-3">
					<p class="text-xs text-gray-500">
						批准后成员才开始工作（普通聊天不会自动启动多代理）。每个成员会消耗模型额度；可以随时暂停派发或停止。
					</p>
					<div class="flex flex-wrap items-center gap-2">
						<button
							type="button"
							class="tm-btn-primary"
							disabled={busy}
							on:click={() => dispatch('approve')}
							>{busy ? '处理中…' : '批准并开始'}<svg
								class="size-3.5"
								viewBox="0 0 16 16"
								fill="none"
								aria-hidden="true"
								><path
									d="M3 8h9.5M8.5 4l4 4-4 4"
									stroke="currentColor"
									stroke-width="1.7"
									stroke-linecap="round"
									stroke-linejoin="round"
								/></svg
							></button
						>
						<button
							type="button"
							class="tm-btn-ghost !px-3.5 !py-2 !text-sm"
							disabled={busy}
							aria-expanded={showFeedback}
							on:click={() => (showFeedback = !showFeedback)}>按意见重新规划</button
						>
						<button
							type="button"
							class="rounded-xl px-3 py-2 text-sm text-gray-500 transition hover:text-red-600 disabled:opacity-50"
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
								class="tm-btn-primary self-start !py-1.5 !text-xs"
								disabled={busy}>让负责人重新规划</button
							>
						</form>
					{/if}
				</div>
			</div>
		{/if}
	</div>
{/if}

<style>
	.stats .stat + .stat {
		border-left: 1px solid hsl(var(--tm-line));
	}
	@media (max-width: 639px) {
		.stats .stat:nth-child(3) {
			border-left: 0;
		}
		.stats .stat:nth-child(n + 3) {
			border-top: 1px solid hsl(var(--tm-line));
		}
	}
	.lead {
		background: radial-gradient(120% 160% at 0% 0%, hsl(250 90% 65% / 0.1), transparent 55%),
			hsl(var(--tm-surface));
	}
	.runner-box,
	.prompt-box {
		background: hsl(var(--tm-surface-2));
		border: 1px solid hsl(var(--tm-line));
	}
	.steps .step:not(:last-child)::before {
		content: '';
		position: absolute;
		left: 11.5px;
		top: 28px;
		bottom: -16px;
		width: 1px;
		background: linear-gradient(hsl(var(--tm-line-strong)), hsl(var(--tm-line)));
	}
	.step-node {
		color: hsl(var(--tm-accent));
		background: hsl(var(--tm-accent) / 0.08);
		box-shadow: inset 0 0 0 1px hsl(var(--tm-accent) / 0.25);
	}
	.dock {
		box-shadow: var(--tm-shadow-lift);
	}
	/* The page fades out under the floating dock instead of peeking out below it. */
	.dock-wrap {
		background: linear-gradient(to bottom, transparent, var(--tm-page) 55%);
	}
	/* The app's global `select` rule (unlayered) outranks Tailwind's utilities: size these here. */
	.compact-select {
		font-size: 0.75rem;
		line-height: 1rem;
		padding: 0.3rem 1.75rem 0.3rem 0.55rem;
		background-size: 1em 1em;
	}
</style>
