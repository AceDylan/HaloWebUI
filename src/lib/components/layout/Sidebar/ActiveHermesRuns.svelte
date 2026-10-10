<script lang="ts">
	import { getContext } from 'svelte';
	import {
		hermesActiveRuns,
		hermesBackgroundRuns,
		hermesUnreadChatIds,
		mobile,
		showSidebar
	} from '$lib/stores';
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

	$: unreadCount = $hermesUnreadChatIds.size;
	$: approvalCount = $hermesActiveRuns.filter((run) => run.awaiting_approval).length;
	$: runningCount = $hermesActiveRuns.length + $hermesBackgroundRuns.length;
	// Nothing left to show (the last run finished and was opened elsewhere).
	$: if (showPopup && runningCount === 0 && unreadCount === 0) {
		showPopup = false;
	}
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
			<div class="flex max-h-[22rem] flex-col gap-0.5 overflow-y-auto px-3 pt-2 pb-4 dark:text-gray-200">
				<ActiveHermesRunsList
					showUnread
					onNavigate={() => {
						showPopup = false;
					}}
				/>
			</div>
		</div>
	</Modal>
{:else if runningCount > 0}
	<Folder className="px-2 mt-0.5" name={$i18n.t('Running')} dragAndDrop={false}>
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
{/if}
