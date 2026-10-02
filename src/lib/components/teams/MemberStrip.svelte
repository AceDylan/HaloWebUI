<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	import StatusChip from './StatusChip.svelte';
	import TeamAvatar from './TeamAvatar.svelte';
	import { avatarKind, EXECUTOR_LABEL } from './model';

	/** The lead and every member: who is on the team, what each one is doing right now. */
	export let lead: { name: string; role: string; status: string; note?: string };
	export let members: {
		name: string;
		role: string;
		executor: string;
		status: string;
		focus?: string;
		currentKey?: string | null;
		currentTitle?: string | null;
		waitingFor?: string[];
	}[] = [];
	export let selected: string | null = null;
	export let layout: 'row' | 'list' = 'row';

	const dispatch = createEventDispatcher();
</script>

<div
	class={layout === 'row' ? 'flex gap-2 overflow-x-auto pb-1 scrollbar-hidden' : 'flex flex-col gap-2'}
	role="list"
	aria-label="团队成员"
>
	<div
		role="listitem"
		class="flex items-center gap-2.5 rounded-2xl border border-indigo-200/70 bg-indigo-50/60 px-3 py-2 dark:border-indigo-900/60 dark:bg-indigo-950/30 {layout ===
		'row'
			? 'min-w-[200px] shrink-0'
			: ''}"
	>
		<TeamAvatar kind="lead" status={lead.status} size={36} />
		<div class="min-w-0">
			<div class="flex items-center gap-1.5">
				<span class="truncate text-sm font-semibold text-gray-900 dark:text-gray-100">{lead.name}</span>
				<StatusChip status={lead.status} />
			</div>
			<div class="truncate text-xs text-gray-500 dark:text-gray-400">{lead.role}{lead.note ? ` · ${lead.note}` : ''}</div>
		</div>
	</div>
	{#each members as member (member.name)}
		<div role="listitem" class={layout === 'row' ? 'shrink-0' : ''}>
		<button
			type="button"
			class="flex items-center gap-2.5 rounded-2xl border px-3 py-2 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400
			{selected === member.name
				? 'border-sky-300 bg-sky-50/70 dark:border-sky-700 dark:bg-sky-950/30'
				: 'border-gray-100 bg-white hover:border-gray-200 dark:border-gray-850 dark:bg-gray-900 dark:hover:border-gray-700'}
			{layout === 'row' ? 'min-w-[220px] max-w-[280px] h-full' : 'w-full'}"
			aria-pressed={selected === member.name}
			on:click={() => dispatch('select', selected === member.name ? null : member.name)}
			data-member={member.name}
		>
			<TeamAvatar kind={avatarKind(member)} status={member.status} size={36} />
			<div class="min-w-0 flex-1">
				<div class="flex items-center gap-1.5">
					<span class="truncate text-sm font-semibold text-gray-900 dark:text-gray-100">{member.name}</span>
					<StatusChip status={member.status} />
				</div>
				<div class="truncate text-xs text-gray-500 dark:text-gray-400">
					{member.role} · {EXECUTOR_LABEL[member.executor] ?? member.executor}
				</div>
				{#if member.currentKey}
					<div class="truncate text-xs text-sky-700 dark:text-sky-300">#{member.currentKey} {member.currentTitle ?? ''}</div>
				{:else if member.waitingFor?.length}
					<div class="truncate text-xs text-amber-600 dark:text-amber-400">等 {member.waitingFor.join('、')} 完成</div>
				{/if}
			</div>
		</button>
		</div>
	{/each}
</div>
