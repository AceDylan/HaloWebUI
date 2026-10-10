<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import {
		deleteTeamSchedule,
		getTeamSchedule,
		repeatTeam,
		setTeamSchedule,
		type Team,
		type TeamSchedule,
		type TeamScheduleFreq
	} from '$lib/apis/teams';
	import Modal from '$lib/components/common/Modal.svelte';
	import { scheduleWhen } from './repeat';

	/**
	 * 再来一次 / 定时 for a team that has a plan: a new team with the same goal and members (no new
	 * planning), now or every day / week / month. The header button reads the schedule when there
	 * is one, so a team that repeats says so. ``?schedule=1`` (from the 定时任务 page) opens it.
	 */
	export let team: Team;

	let show = false;
	let schedule: TeamSchedule | null = null;
	let busy = '';
	let freq: TeamScheduleFreq = 'weekly';
	let weekday = (new Date().getDay() + 6) % 7;
	let day = Math.min(new Date().getDate(), 28);
	let time = '09:00';

	const FREQS: [TeamScheduleFreq, string][] = [
		['daily', '每天'],
		['weekly', '每周'],
		['monthly', '每月']
	];
	const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];

	const fill = (s: TeamSchedule | null) => {
		schedule = s;
		if (!s) return;
		freq = s.freq;
		time = s.time;
		if (s.weekday !== null) weekday = s.weekday;
		if (s.day !== null) day = s.day;
	};

	onMount(async () => {
		try {
			fill((await getTeamSchedule(localStorage.token, team.id)).schedule);
		} catch {
			// the button still offers 再来一次; the dialog says it if saving fails
		}
		if (new URLSearchParams(window.location.search).get('schedule')) show = true;
	});

	const run = async (key: string, fn: () => Promise<void>) => {
		if (busy) return;
		busy = key;
		try {
			await fn();
		} catch (error) {
			toast.error(`${(error as Error)?.message ?? error}`);
		} finally {
			busy = '';
		}
	};

	const again = (autoStart: boolean) =>
		run(autoStart ? 'start' : 'review', async () => {
			const made = await repeatTeam(localStorage.token, team.id, autoStart);
			show = false;
			toast.success(
				made.status === 'running' || made.status === 'starting'
					? '已再来一次，成员开始工作'
					: '已按原来的计划新建，批准后开始'
			);
			await goto(`/teams/${made.id}`);
		});

	const save = (enabled = true) =>
		run(enabled ? 'save' : 'pause', async () => {
			const input = { freq, time, enabled, weekday: freq === 'weekly' ? weekday : null, day: freq === 'monthly' ? day : null };
			fill((await setTeamSchedule(localStorage.token, team.id, input)).schedule);
			toast.success(enabled ? `已设定时：${schedule?.label}` : '定时已暂停');
		});

	const remove = () =>
		run('remove', async () => {
			await deleteTeamSchedule(localStorage.token, team.id);
			schedule = null;
			toast.success('已取消定时');
		});

	$: active = !!schedule?.enabled;
</script>

<button
	type="button"
	class="tm-btn-ghost"
	class:is-scheduled={active}
	on:click={() => (show = true)}
	title={active
		? `定时：${schedule?.label}，到时自动再来一次`
		: '用同样的目标和成员再跑一次，或者设成每天 / 每周 / 每月自动跑'}
	data-team-repeat
	><svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
		>{#if active}<circle cx="8" cy="8" r="5.75" stroke="currentColor" stroke-width="1.4" /><path
				d="M8 5v3.2l2 1.3"
				stroke="currentColor"
				stroke-width="1.4"
				stroke-linecap="round"
				stroke-linejoin="round"
			/>{:else}<path
				d="M12.5 6.5A4.75 4.75 0 0 0 3.6 5M3.5 9.5a4.75 4.75 0 0 0 8.9 1.5M3.4 2.6V5h2.4M12.6 13.4V11h-2.4"
				stroke="currentColor"
				stroke-width="1.4"
				stroke-linecap="round"
				stroke-linejoin="round"
			/>{/if}</svg
	><span class="max-sm:sr-only">{active ? schedule?.label : '再来一次'}</span></button
>

<Modal bind:show size="sm">
	<div class="space-y-5 p-5" data-teams-ui data-team-repeat-dialog>
		<div>
			<div class="tm-display text-base font-semibold text-gray-900 dark:text-gray-50">再来一次</div>
			<p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
				同样的目标和成员（{team.member_count || team.plan?.members?.length || 0} 人、{team.task_count ||
					team.plan?.tasks?.length ||
					0} 个任务），不重新规划，开一个新的协作。
			</p>
			<div class="mt-3 flex flex-wrap gap-2">
				<button
					type="button"
					class="tm-btn-primary"
					disabled={!!busy}
					on:click={() => again(true)}
					data-team-repeat-start>{busy === 'start' ? '正在开始…' : '直接开始'}</button
				>
				<button
					type="button"
					class="tm-btn-ghost"
					disabled={!!busy}
					on:click={() => again(false)}
					data-team-repeat-review>{busy === 'review' ? '正在新建…' : '先看计划再批准'}</button
				>
			</div>
		</div>

		<div class="border-t border-[var(--surface-border)] pt-4">
			<div class="flex items-center gap-2">
				<div class="tm-display text-base font-semibold text-gray-900 dark:text-gray-50">定时</div>
				{#if schedule}
					<span class="text-xs {active ? 'text-[hsl(var(--tm-accent))]' : 'text-gray-400'}" data-team-schedule-state
						>{active ? `已开启 · ${schedule.label}` : '已暂停'}</span
					>
				{/if}
			</div>
			<p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
				到时间自动再来一次并直接开始，结果照常发回对话和 Telegram。上一次还没结束时这一次会跳过。
			</p>
			<div class="mt-3 space-y-2.5">
				<div class="tm-segment" role="radiogroup" aria-label="频率" data-team-schedule-freq>
					{#each FREQS as [value, label]}
						<button
							type="button"
							role="radio"
							aria-checked={freq === value}
							data-value={value}
							on:click={() => (freq = value)}>{label}</button
						>
					{/each}
				</div>
				{#if freq === 'weekly'}
					<div class="tm-segment" role="radiogroup" aria-label="星期几" data-team-schedule-weekday>
						{#each WEEKDAYS as label, i}
							<button
								type="button"
								role="radio"
								aria-checked={weekday === i}
								data-value={i}
								on:click={() => (weekday = i)}>{label}</button
							>
						{/each}
					</div>
				{/if}
				<div class="flex flex-wrap items-center gap-2">
					{#if freq === 'monthly'}
						<input
							class="halo-input !w-20 tabular-nums"
							type="number"
							min="1"
							max="28"
							bind:value={day}
							aria-label="几号"
							data-team-schedule-day
						/>
						<span class="text-sm text-gray-500">号</span>
					{/if}
					<input
						class="halo-input !w-32 tabular-nums"
						type="time"
						bind:value={time}
						aria-label="几点"
						data-team-schedule-time
					/>
				</div>
				{#if schedule?.enabled && schedule.next_run_at}
					<div class="text-xs text-gray-500 dark:text-gray-400" data-team-schedule-next>
						下一次：{scheduleWhen(schedule.next_run_at)}
					</div>
				{/if}
				{#if schedule?.last_error}
					<div class="text-xs text-[hsl(var(--tm-bad))]" data-team-schedule-error>
						上一次：{schedule.last_error}
					</div>
				{/if}
			</div>
			<div class="mt-3 flex flex-wrap items-center gap-2">
				<button
					type="button"
					class="tm-btn-primary"
					disabled={!!busy || !time}
					on:click={() => save(true)}
					data-team-schedule-save>{busy === 'save' ? '保存中…' : active ? '保存' : schedule ? '保存并开启' : '开启定时'}</button
				>
				{#if active}
					<button type="button" class="tm-btn-ghost" disabled={!!busy} on:click={() => save(false)}
						>暂停</button
					>
				{/if}
				{#if schedule}
					<button
						type="button"
						class="tm-btn-ghost tm-btn-danger ml-auto"
						disabled={!!busy}
						on:click={remove}
						data-team-schedule-delete>取消定时</button
					>
				{/if}
			</div>
		</div>
	</div>
</Modal>

<style>
	.is-scheduled {
		color: hsl(var(--tm-accent));
	}
</style>
