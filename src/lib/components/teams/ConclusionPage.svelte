<script lang="ts">
	import { onMount } from 'svelte';

	import './teams.css';
	import { mobile, showSidebar } from '$lib/stores';
	import { getTeam, type LiveSnapshot, type Team } from '$lib/apis/teams';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import ConclusionView from './ConclusionView.svelte';
	import TeamAvatar from './TeamAvatar.svelte';
	import { elapsed } from './clock';
	import { avatarKind, PHASE_LABEL, runnerLabel } from './model';

	/** The conclusion as a page of its own: wide reading column, table of contents, print-friendly. */
	export let teamId: string;

	let team: Team | null = null;
	let live: LiveSnapshot | null = null;
	let error = '';

	$: phase = live?.team.phase ?? team?.phase ?? 'running';
	$: done = live?.tasks.filter((t) => t.status === 'done').length ?? 0;
	$: total = live?.tasks.length ?? team?.task_count ?? 0;
	$: members = team?.plan?.members ?? [];
	$: runners = [...new Set((live?.tasks ?? []).map((t) => t.executor).filter(Boolean))];
	$: took = team?.approved_at && team?.finished_at ? team.finished_at - team.approved_at : null;
	$: leadModel =
		live?.team.lead_model?.model ?? team?.plan?.lead_model?.model ?? team?.plan?.lead?.model ?? '';

	onMount(async () => {
		try {
			const data = await getTeam(localStorage.token, teamId);
			team = data.team;
			live = data.live;
		} catch (e) {
			error = `${(e as Error)?.message ?? e}`;
		}
	});
</script>

<div
	class="tm-ambient relative flex h-screen max-h-[100dvh] w-full max-w-full flex-col"
	data-conclusion-page
	data-teams-ui
>
	<nav class="flex min-w-0 items-center gap-2 px-3 pt-2 pb-1">
		<div class="{$mobile ? '' : 'hidden'} flex flex-none items-center">
			<button
				class="rounded-xl p-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
				on:click={() => showSidebar.set(!$showSidebar)}
				aria-label="切换侧栏"><MenuLines /></button
			>
		</div>
		<a
			href="/teams"
			class="shrink-0 text-sm text-gray-500 hover:text-gray-900 dark:hover:text-gray-100">协作台</a
		>
		<span class="text-gray-300 dark:text-gray-700">/</span>
		<a
			href="/teams/{teamId}"
			class="min-w-0 truncate text-sm text-gray-500 hover:text-gray-900 dark:hover:text-gray-100"
			>{team?.title ?? '…'}</a
		>
		<span class="text-gray-300 dark:text-gray-700">/</span>
		<h1 class="shrink-0 text-sm font-semibold text-gray-900 dark:text-gray-100">结论</h1>
	</nav>
	<div class="tm-scroll flex-1 overflow-y-auto px-4 pb-16 sm:px-6">
		{#if error}
			<div class="mx-auto mt-16 max-w-md text-center text-sm text-gray-500">
				{error}
				<div class="mt-3"><a class="text-sky-600 hover:underline" href="/teams">回到协作台</a></div>
			</div>
		{:else}
			<div class="mx-auto w-full max-w-6xl pt-4 sm:pt-8">
				{#if team}
					<div class="mb-6 sm:mb-8 lg:ml-[15rem]">
						<div class="text-xs text-gray-500">
							协作任务 · {PHASE_LABEL[phase] ?? phase}{total
								? ` · ${done}/${total} 个任务完成`
								: ''}
						</div>
						<div
							class="tm-display mt-1.5 text-[1.65rem] font-semibold leading-tight tracking-tight text-gray-900 sm:text-[2rem] dark:text-gray-50"
						>
							{team.title}
						</div>
						<p
							class="mt-3 max-w-[46rem] whitespace-pre-wrap break-words text-sm leading-relaxed text-gray-600 dark:text-gray-400 line-clamp-4"
						>
							{team.goal}
						</p>
						<div
							class="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-gray-500 dark:text-gray-400"
							data-conclusion-facts
						>
							{#if members.length}
								<span class="flex items-center gap-2">
									<span class="flex -space-x-1.5" aria-hidden="true">
										<span class="stack"><TeamAvatar kind="lead" size={22} /></span>
										{#each members.slice(0, 5) as m}
											<span class="stack"><TeamAvatar kind={avatarKind(m)} size={22} /></span>
										{/each}
									</span>
									负责人 + {members.length} 位成员
								</span>
							{/if}
							{#if took !== null}
								<span
									>用时 <b class="tm-num font-semibold text-gray-800 dark:text-gray-200"
										>{elapsed(took)}</b
									></span
								>
							{/if}
							{#if runners.length}
								<span class="font-mono">{runners.map(runnerLabel).join(' · ')}</span>
							{/if}
							{#if leadModel}
								<span
									>负责人 <span class="font-mono text-gray-700 dark:text-gray-300">{leadModel}</span
									></span
								>
							{/if}
						</div>
					</div>
				{/if}
				<ConclusionView
					{teamId}
					variant="page"
					title={team?.title ?? ''}
					{phase}
					brief={live?.team.conclusion}
					progress={{ done, total }}
					chatId={team?.chat_id ?? null}
					outputs={team?.outputs}
				/>
			</div>
		{/if}
	</div>
</div>

<style>
	.stack {
		border-radius: 9999px;
		box-shadow: 0 0 0 2px hsl(var(--tm-surface));
	}
</style>
