<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	import type { Team, TeamExecutor } from '$lib/apis/teams';
	import StatusChip from './StatusChip.svelte';
	import TeamAvatar from './TeamAvatar.svelte';
	import { avatarKind, EXECUTOR_LABEL, EXECUTOR_OPTIONS } from './model';

	/** The lead's plan, shown before anything runs: approve it, ask for changes, or cancel. */
	export let team: Team;
	export let busy = false;
	export let parallelCap = 2;

	const dispatch = createEventDispatcher<{
		approve: void;
		replan: string;
		cancel: void;
		executor: { name: string; executor: TeamExecutor };
	}>();
	let feedback = '';
	let showFeedback = false;

	$: plan = team.plan;
	$: layers = plan?.layers?.length ? plan.layers : plan ? [plan.tasks.map((t) => t.key)] : [];
	$: byKey = new Map((plan?.tasks ?? []).map((t) => [t.key, t]));
	$: widest = plan?.widest_layer ?? Math.max(0, ...layers.map((l) => l.length));
	$: parallel = Math.min(widest, parallelCap);
	$: executors = [...new Set((plan?.members ?? []).map((m) => m.executor))];
	$: editable = team.status === 'plan_ready' || team.status === 'start_failed';
</script>

{#if plan}
	<div class="flex flex-col gap-4" data-plan-review>
		{#if plan.summary}
			<p class="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{plan.summary}</p>
		{/if}

		<div class="grid gap-2 sm:grid-cols-3 text-xs">
			<div class="rounded-xl bg-gray-50 px-3 py-2 dark:bg-gray-850">
				<div class="text-gray-500">成员</div>
				<div class="text-base font-semibold text-gray-900 dark:text-gray-100">1 位负责人 + {plan.members.length} 位成员</div>
			</div>
			<div class="rounded-xl bg-gray-50 px-3 py-2 dark:bg-gray-850">
				<div class="text-gray-500">预计同时执行</div>
				<div class="text-base font-semibold text-gray-900 dark:text-gray-100">最多 {parallel} 个成员</div>
				<div class="text-gray-400">
					{widest > parallelCap ? `计划里最多 ${widest} 个可并行，本机上限 ${parallelCap}，其余排队` : `本机上限 ${parallelCap}`}
				</div>
			</div>
			<div class="rounded-xl bg-gray-50 px-3 py-2 dark:bg-gray-850">
				<div class="text-gray-500">执行来源</div>
				<div class="text-base font-semibold text-gray-900 dark:text-gray-100">{executors.map((e) => EXECUTOR_LABEL[e] ?? e).join(' + ')}</div>
				<div class="text-gray-400">角色数不等于同时运行数</div>
			</div>
		</div>

		<div>
			<h3 class="mb-2 text-sm font-semibold text-gray-900 dark:text-gray-100">成员分工</h3>
			<ul class="grid gap-2 sm:grid-cols-2">
				<li class="flex items-center gap-2.5 rounded-2xl border border-indigo-200/70 bg-indigo-50/60 px-3 py-2 dark:border-indigo-900/60 dark:bg-indigo-950/30">
					<TeamAvatar kind="lead" size={34} />
					<div class="min-w-0">
						<div class="text-sm font-semibold">team-lead</div>
						<div class="text-xs text-gray-500">负责人 · 制定了这个计划，批准后由派发器按依赖调度成员</div>
					</div>
				</li>
				{#each plan.members as member (member.name)}
					<li class="flex items-center gap-2.5 rounded-2xl border border-gray-100 px-3 py-2 dark:border-gray-850">
						<TeamAvatar kind={avatarKind(member)} size={34} />
						<div class="min-w-0 flex-1">
							<div class="text-sm font-semibold truncate">{member.name} <span class="font-normal text-gray-500">· {member.role}</span></div>
							{#if member.focus}<div class="text-xs text-gray-500 line-clamp-2">{member.focus}</div>{/if}
						</div>
						<label class="shrink-0 text-xs">
							<span class="sr-only">{member.name} 的执行来源</span>
							<select
								class="max-w-[9rem] truncate rounded-lg border border-gray-200 bg-white px-1.5 py-1 text-xs dark:border-gray-700 dark:bg-gray-900 disabled:opacity-60"
								title="执行来源：Hermes 代理，或聊天里 /reclaude、/codex … 用的同一套 runner"
								value={member.executor}
								disabled={!editable || busy}
								on:change={(e) =>
									dispatch('executor', {
										name: member.name,
										executor: EXECUTOR_OPTIONS.find((o) => o.value === e.currentTarget.value)?.value ?? 'hermes'
									})}
							>
								{#each EXECUTOR_OPTIONS as option}
									<option value={option.value}>{option.label}</option>
								{/each}
							</select>
						</label>
					</li>
				{/each}
			</ul>
		</div>

		<div>
			<h3 class="mb-2 text-sm font-semibold text-gray-900 dark:text-gray-100">任务和依赖</h3>
			<ol class="flex flex-col gap-3">
				{#each layers as layer, depth}
					<li>
						<div class="mb-1 text-xs text-gray-500">
							第 {depth + 1} 步{layer.length > 1 ? ` · ${layer.length} 个任务可并行` : ''}
						</div>
						<ul class="grid gap-2 sm:grid-cols-2">
							{#each layer as key}
								{@const task = byKey.get(key)}
								{#if task}
									<li class="rounded-2xl border border-gray-100 px-3 py-2 dark:border-gray-850">
										<div class="flex items-center gap-2 text-xs">
											<span class="font-mono font-semibold text-gray-500">#{task.key}</span>
											<span class="text-gray-500">{task.member}</span>
											{#if task.depends_on.length}
												<span class="ml-auto"><StatusChip status="waiting_deps" label={`依赖 ${task.depends_on.map((d) => '#' + d).join('、')}`} /></span>
											{/if}
										</div>
										<div class="mt-1 text-sm font-medium text-gray-900 dark:text-gray-100">{task.title}</div>
										<details class="mt-1">
											<summary class="cursor-pointer text-xs text-gray-500">说明</summary>
											<p class="mt-1 whitespace-pre-wrap break-words text-xs text-gray-600 dark:text-gray-400">{task.description}</p>
										</details>
									</li>
								{/if}
							{/each}
						</ul>
					</li>
				{/each}
			</ol>
		</div>

		{#if editable}
			<div class="flex flex-col gap-2 border-t border-gray-100 pt-3 dark:border-gray-850">
				<p class="text-xs text-gray-500">
					批准后成员才开始工作（普通聊天不会自动启动多代理）。每个成员会消耗模型额度；可以随时暂停派发或停止。
				</p>
				<div class="flex flex-wrap items-center gap-2">
					<button
						type="button"
						class="rounded-xl bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
						disabled={busy}
						on:click={() => dispatch('approve')}>{busy ? '正在启动…' : '批准并开始'}</button
					>
					<button
						type="button"
						class="rounded-xl bg-gray-100 px-4 py-2 text-sm text-gray-700 hover:bg-gray-200 disabled:opacity-50 dark:bg-gray-850 dark:text-gray-200"
						disabled={busy}
						on:click={() => (showFeedback = !showFeedback)}>按意见重新规划</button
					>
					<button
						type="button"
						class="rounded-xl px-4 py-2 text-sm text-gray-500 hover:text-red-600 disabled:opacity-50"
						disabled={busy}
						on:click={() => dispatch('cancel')}>取消</button
					>
				</div>
				{#if showFeedback}
					<form class="flex flex-col gap-1.5" on:submit|preventDefault={() => dispatch('replan', feedback)}>
						<label class="text-xs text-gray-600 dark:text-gray-300" for="team-replan">你希望怎么改？</label>
						<textarea
							id="team-replan"
							bind:value={feedback}
							rows="3"
							maxlength="2000"
							class="w-full rounded-xl border border-gray-200 bg-white px-2.5 py-2 text-sm outline-none focus:border-sky-400 dark:border-gray-800 dark:bg-gray-900"
							placeholder="例如：再加一个测试成员；把评审放到最后"
						/>
						<button
							type="submit"
							class="self-start rounded-xl bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-700 disabled:opacity-50"
							disabled={busy}>让负责人重新规划</button
						>
					</form>
				{/if}
			</div>
		{/if}
	</div>
{/if}
