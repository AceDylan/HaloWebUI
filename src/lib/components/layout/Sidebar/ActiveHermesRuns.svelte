<script lang="ts">
	import { getContext } from 'svelte';
	import { mobile, showSidebar, showTaskInbox } from '$lib/stores';
	import { hermesActivityRows } from '$lib/utils/hermes-activity';
	import Folder from '../../common/Folder.svelte';
	import Modal from '../../common/Modal.svelte';
	import Tooltip from '../../common/Tooltip.svelte';
	import Bolt from '../../icons/Bolt.svelte';
	import XMark from '../../icons/XMark.svelte';
	import ActiveHermesRunsList from './ActiveHermesRunsList.svelte';

	const i18n = getContext('i18n');

	// `compact` is the collapsed-rail form: one icon with a count badge that
	// opens the runs in a popup, like 对话历史, so the sidebar stays collapsed.
	// The full form lists the runs under "Running".
	export let compact = false;
	export let buttonClass = '';
	// The rail is replaced by the full sidebar while it peeks, which would take
	// the popup with it; the sidebar cancels the peek here.
	export let onOpen: () => void = () => {};

	let showPopup = false;

	$: unreadCount = $hermesActivityRows.unread.length;
	$: approvalCount =
		$hermesActivityRows.runs.filter((run) => run.awaiting_approval).length +
		$hermesActivityRows.work.filter((row) => row.state === 'waiting').length;
	$: runningCount =
		$hermesActivityRows.runs.length +
		$hermesActivityRows.background.length +
		$hermesActivityRows.work.length;
	// Nothing left to show (the last run finished and was opened elsewhere).
	$: if (showPopup && runningCount === 0 && unreadCount === 0) {
		showPopup = false;
	}

	const openInbox = () => {
		onOpen();
		showPopup = false;
		showTaskInbox.set(true);
		if ($mobile) {
			showSidebar.set(false);
		}
	};
</script>

{#if compact}
	{#if runningCount > 0 || unreadCount > 0}
		<Tooltip
			content={approvalCount > 0
				? `${$i18n.t('Waiting for your approval')} · ${approvalCount}`
				: runningCount > 0
					? `${$i18n.t('Running')} · ${runningCount}`
					: `${$i18n.t('Finished, not yet opened')} · ${unreadCount}`}
		>
			<button
				class="{buttonClass} relative"
				type="button"
				on:click={() => {
					onOpen();
					showPopup = true;
				}}
				aria-haspopup="dialog"
				aria-label={approvalCount > 0
					? $i18n.t('Waiting for your approval')
					: runningCount > 0
						? $i18n.t('Running')
						: $i18n.t('Finished, not yet opened')}
				data-halo-hermes-runs-rail
			>
				<Bolt
					className="size-5 {approvalCount > 0
						? 'text-amber-600 dark:text-amber-400'
						: runningCount > 0
							? 'text-blue-600 dark:text-blue-400'
							: 'text-emerald-600 dark:text-emerald-400'}"
					strokeWidth="2"
				/>
				<span
					class="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-2xs font-semibold leading-none text-white {approvalCount >
					0
						? 'bg-amber-500'
						: runningCount > 0
							? 'bg-blue-500'
							: 'bg-emerald-500'}"
				>
					{approvalCount > 0 ? approvalCount : runningCount > 0 ? runningCount : unreadCount}
				</span>
			</button>
		</Tooltip>
	{:else}
		<Tooltip content="任务收件箱">
			<button
				class={buttonClass}
				type="button"
				on:click={openInbox}
				aria-haspopup="dialog"
				aria-label="任务收件箱"
				data-halo-task-inbox-rail
			>
				<Bolt className="size-5" strokeWidth="1.8" />
			</button>
		</Tooltip>
	{/if}

	<Modal size="sm" bind:show={showPopup}>
		<div data-halo-hermes-runs-popup>
			<div class="flex justify-between px-5 pt-4 pb-1 dark:text-gray-300">
				<div class="self-center text-lg font-medium">{$i18n.t('Running')}</div>
				<button
					class="self-center"
					type="button"
					aria-label={$i18n.t('Close')}
					on:click={() => {
						showPopup = false;
					}}
				>
					<XMark className="size-5" />
				</button>
			</div>
			<div class="flex max-h-[22rem] flex-col gap-0.5 overflow-y-auto px-3 pt-2 pb-2 dark:text-gray-200">
				<ActiveHermesRunsList
					showUnread
					onNavigate={() => {
						showPopup = false;
					}}
				/>
			</div>
			<div class="border-t border-gray-100 px-4 py-2.5 dark:border-gray-850">
				<button
					type="button"
					class="flex w-full items-center justify-between rounded-lg px-2 py-1 text-xs font-medium text-sky-700 transition hover:bg-gray-100 dark:text-sky-300 dark:hover:bg-gray-900"
					on:click={openInbox}
					data-halo-open-task-inbox
				>
					<span>打开任务收件箱（含已结束与 Telegram/QQ）</span>
					<span aria-hidden="true">→</span>
				</button>
			</div>
		</div>
	</Modal>
{:else if runningCount > 0}
	<Folder className="px-2 mt-0.5" name={$i18n.t('Running')} dragAndDrop={false}>
		<svelte:fragment slot="actions">
			<button
				type="button"
				class="rounded-md px-1.5 py-0.5 text-2xs font-medium text-gray-500 transition hover:bg-gray-200/70 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-850 dark:hover:text-gray-100"
				title="打开任务收件箱，查看待处理与最近结束的任务"
				on:click|stopPropagation={openInbox}
				data-halo-open-task-inbox
			>
				收件箱
			</button>
		</svelte:fragment>
		<div
			class="ml-3 pl-1 mt-[1px] flex flex-col border-s border-gray-100 dark:border-gray-900"
		>
			<ActiveHermesRunsList
				onNavigate={() => {
					if ($mobile) {
						showSidebar.set(false);
					}
				}}
			/>
		</div>
	</Folder>
{:else}
	<div class="px-2 mt-0.5">
		<button
			type="button"
			class="flex w-full items-center gap-2 rounded-xl px-2.5 py-1.5 text-left text-xs font-medium text-gray-600 transition hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-850 dark:hover:text-gray-100"
			on:click={openInbox}
			data-halo-open-task-inbox
		>
			<Bolt
				className="size-3.5 shrink-0 {unreadCount > 0
					? 'text-emerald-600 dark:text-emerald-400'
					: 'text-gray-400 dark:text-gray-500'}"
				strokeWidth="2"
			/>
			<span class="flex-1 truncate">任务收件箱</span>
			{#if unreadCount > 0}
				<span
					class="shrink-0 rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-2xs font-semibold text-emerald-700 dark:text-emerald-300"
					data-halo-task-inbox-unread>{unreadCount} 未读</span
				>
			{:else}
				<span class="shrink-0 text-2xs text-gray-400 dark:text-gray-500">最近任务</span>
			{/if}
		</button>
	</div>
{/if}
