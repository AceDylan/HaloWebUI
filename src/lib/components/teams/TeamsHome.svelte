<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import { mobile, showSidebar } from '$lib/stores';
	import {
		checkRunners,
		createTeam,
		getTeamsMeta,
		listTeams,
		type Team,
		type TeamsMeta
	} from '$lib/apis/teams';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import RunnerStatus from './RunnerStatus.svelte';
	import StatusChip from './StatusChip.svelte';
	import { PHASE_LABEL, runnerLabel } from './model';

	/** Your collaboration tasks (only yours) and a box to start a new one. */
	let teams: Team[] = [];
	let loaded = false;
	let error = '';
	let goal = '';
	let creating = false;
	let chatId: string | null = null;
	let meta: TeamsMeta | null = null;
	let metaError = '';
	let checking = false;
	let leadModel = '';

	// The lead follows Hermes' default model unless this team picks another configured one.
	$: defaultModel = meta?.lead_model?.choices?.[0] ?? meta?.lead_model?.model ?? '';
	$: modelChoices = (meta?.lead_model?.choices ?? []).filter((m) => m !== defaultModel);

	$: chatTeams = chatId ? teams.filter((t) => t.chat_id === chatId) : [];

	const statusOf = (t: Team) => (t.status === 'running' ? (t.phase ?? 'running') : t.status);
	const chipOf = (s: string) =>
		({
			planning: 'running',
			plan_ready: 'waiting_user',
			plan_failed: 'failed',
			starting: 'queued',
			start_failed: 'failed',
			cancelled: 'stopped',
			running: 'running',
			attention: 'waiting_user',
			paused: 'paused',
			stopped: 'stopped',
			completed: 'done'
		})[s] ?? 'queued';

	const load = async () => {
		try {
			teams = (await listTeams(localStorage.token)).teams;
			error = '';
		} catch (e) {
			error = `${e?.message ?? e}`;
		} finally {
			loaded = true;
		}
	};

	const loadMeta = async () => {
		try {
			meta = await getTeamsMeta(localStorage.token);
			metaError = '';
		} catch (e) {
			metaError = `${e?.message ?? e}`;
		}
	};

	const recheck = async () => {
		if (checking) return;
		checking = true;
		try {
			const registry = await checkRunners(localStorage.token);
			meta = meta ? { ...meta, registry } : meta;
			if (!meta) await loadMeta();
			metaError = '';
		} catch (e) {
			metaError = `${e?.message ?? e}`;
		} finally {
			checking = false;
		}
	};

	const create = async () => {
		const text = goal.trim();
		if (!text || creating) return;
		creating = true;
		try {
			const team = await createTeam(localStorage.token, text, chatId, leadModel || null);
			goto(`/teams/${team.id}`);
		} catch (e) {
			toast.error(`${e?.message ?? e}`);
		} finally {
			creating = false;
		}
	};

	onMount(() => {
		// "发起协作任务" from a chat links here with ?chat=<id> (and an optional ?goal=).
		const params = new URLSearchParams(window.location.search);
		chatId = params.get('chat');
		goal = params.get('goal') ?? '';
		load();
		loadMeta();
	});
</script>

<div class="relative flex h-screen max-h-[100dvh] w-full flex-col" data-teams-home>
	<nav class="flex items-center gap-2 px-3 pt-2 pb-1">
		<div class="{$mobile ? '' : 'hidden'} flex flex-none items-center">
			<button
				class="rounded-xl p-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
				on:click={() => showSidebar.set(!$showSidebar)}
				aria-label="切换侧栏"><MenuLines /></button
			>
		</div>
		<h1 class="text-sm font-semibold text-gray-900 dark:text-gray-100">协作台</h1>
	</nav>
	<div class="flex-1 overflow-y-auto px-3 pb-8">
		<div class="mx-auto flex max-w-3xl flex-col gap-5 pt-2">
			{#if chatId}
				<div class="flex items-center gap-2 text-xs">
					<a
						href="/c/{chatId}"
						class="rounded-xl px-2.5 py-1 text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-850"
						>← 返回对话</a
					>
				</div>
				{#if chatTeams.length}
					<section aria-label="这个对话的协作任务">
						<h2 class="mb-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
							这个对话的协作任务
						</h2>
						<ul class="flex flex-col gap-2">
							{#each chatTeams as team (team.id)}
								<li>
									<a
										href="/teams/{team.id}"
										class="flex items-center gap-3 rounded-2xl border border-sky-200 bg-sky-50/50 px-4 py-3 hover:border-sky-300 dark:border-sky-900 dark:bg-sky-950/20"
									>
										<span class="min-w-0 flex-1 truncate text-sm font-medium">{team.title}</span>
										<StatusChip
											status={chipOf(statusOf(team))}
											label={PHASE_LABEL[statusOf(team)] ?? statusOf(team)}
										/>
										<span class="text-xs text-sky-700 dark:text-sky-300">打开协作台 →</span>
									</a>
								</li>
							{/each}
						</ul>
					</section>
				{/if}
			{/if}
			<form
				class="flex flex-col gap-2 rounded-2xl border border-gray-100 p-4 dark:border-gray-850"
				on:submit|preventDefault={create}
			>
				<label for="team-goal" class="text-sm font-semibold text-gray-900 dark:text-gray-100"
					>发起协作任务</label
				>
				<p class="text-xs text-gray-500">
					写下要多个代理一起完成的事。负责人会先给出成员分工和带依赖的任务计划，你批准后才开始执行。
					{#if chatId}<span class="text-sky-700 dark:text-sky-300">会关联到你刚才的对话。</span
						>{/if}
				</p>
				<textarea
					id="team-goal"
					bind:value={goal}
					rows="4"
					maxlength="8000"
					class="w-full resize-y rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-gray-800 dark:bg-gray-900"
					placeholder="例如：调研三个开源看板工具并写一份对比报告，最后由评审成员检查结论"
					on:keydown={(e) => {
						if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) create();
					}}
				/>
				<div class="flex flex-wrap items-center gap-x-3 gap-y-2">
					<button
						type="submit"
						class="rounded-xl bg-gray-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-800 active:scale-[0.98] disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white"
						disabled={creating || !goal.trim()}>{creating ? '提交中…' : '让负责人做计划'}</button
					>
					<label class="flex min-w-0 items-center gap-1.5 text-xs text-gray-500" data-lead-model>
						<span class="shrink-0">负责人模型</span>
						<select
							bind:value={leadModel}
							class="min-w-0 max-w-[14rem] truncate rounded-lg border border-gray-200 bg-white py-1 pl-2 pr-7 font-mono text-xs text-gray-800 transition focus:border-sky-400 focus:outline-none dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
							title="负责人做计划、写结论用的模型；默认跟随 Hermes 当前的默认模型"
						>
							<option value=""
								>{meta?.lead_model?.model ? `Hermes 默认 · ${defaultModel}` : 'Hermes 默认'}</option
							>
							{#each modelChoices as model}
								<option value={model}>{model}</option>
							{/each}
						</select>
					</label>
					<span class="text-xs text-gray-400">做计划只调用一次模型，不会启动任何成员</span>
				</div>
			</form>

			<RunnerStatus
				registry={meta?.registry ?? null}
				{checking}
				error={metaError}
				on:check={recheck}
			/>

			<section>
				<h2 class="mb-2 text-sm font-semibold text-gray-900 dark:text-gray-100">我的协作任务</h2>
				{#if !loaded}
					<div class="text-sm text-gray-400">正在加载…</div>
				{:else if error}
					<div class="text-sm text-red-600" role="alert">{error}</div>
				{:else if teams.length === 0}
					<div
						class="rounded-2xl bg-gray-50 px-4 py-6 text-center text-sm text-gray-500 dark:bg-gray-850"
					>
						还没有协作任务
					</div>
				{:else}
					<ul class="flex flex-col gap-2">
						{#each teams as team (team.id)}
							<li
								class="relative flex items-center gap-3 rounded-2xl border border-gray-100 px-4 py-3 transition hover:border-gray-200 hover:bg-gray-50/50 dark:border-gray-850 dark:hover:border-gray-700 dark:hover:bg-gray-900/40"
							>
								<a
									href="/teams/{team.id}"
									class="min-w-0 flex-1 after:absolute after:inset-0 after:rounded-2xl focus:outline-none focus-visible:after:ring-2 focus-visible:after:ring-sky-400"
								>
									<div class="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
										{team.title}
									</div>
									<div class="truncate text-xs text-gray-500">
										{new Date(team.updated_at * 1000).toLocaleString('zh-CN', { hour12: false })}
										{#if team.task_count}
											· {team.member_count} 位成员 · {team.task_count} 个任务{/if}
										{#if team.executors?.length}
											· {team.executors.map(runnerLabel).join(' + ')}{/if}
									</div>
								</a>
								{#if statusOf(team) === 'completed' || statusOf(team) === 'stopped'}
									<a
										href="/teams/{team.id}/conclusion"
										class="relative z-10 hidden shrink-0 rounded-lg px-2 py-1 text-xs font-medium text-emerald-700 transition hover:bg-emerald-50 sm:inline-flex dark:text-emerald-300 dark:hover:bg-emerald-950/40"
										>结论</a
									>
								{/if}
								<StatusChip
									status={chipOf(statusOf(team))}
									label={PHASE_LABEL[statusOf(team)] ?? statusOf(team)}
								/>
							</li>
						{/each}
					</ul>
				{/if}
			</section>
		</div>
	</div>
</div>
