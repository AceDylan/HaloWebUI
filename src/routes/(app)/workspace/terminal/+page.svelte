<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { getTerminalConfig } from '$lib/apis/terminal';
	import FileBrowser from '$lib/components/workspace/FileBrowser.svelte';
	import Terminal from '$lib/components/workspace/Terminal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n = getContext<any>('i18n');

	let activeTab: 'files' | 'terminal' = 'files';
	// null while checking; the server decides whether the file workspace is on. When it is
	// off we say so and point at the setting instead of letting each panel fail with a toast.
	let terminalEnabled: boolean | null = null;

	const checkAvailability = async () => {
		try {
			const config = (await getTerminalConfig(localStorage.token)) as { enabled?: boolean } | null;
			terminalEnabled = config?.enabled !== false;
		} catch (e) {
			// Unknown state: let the panels try and report their own errors.
			terminalEnabled = true;
		}
	};

	onMount(checkAvailability);
</script>

<div class="flex h-full flex-col gap-4">
	<div class="workspace-toolbar-row lg:justify-between">
		<div class="space-y-1">
			<div class="text-base font-semibold text-gray-900 dark:text-gray-100">
				{$i18n.t('Files')}
			</div>
			<div class="text-xs text-gray-600 dark:text-gray-400">
				{$i18n.t(
					'Switch between file browser and terminal access for advanced workspace operations.'
				)}
			</div>
		</div>

		<div
			class="inline-flex max-w-full items-center gap-1.5 self-start rounded-xl bg-gray-100/70 p-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)] dark:bg-gray-850/80 dark:shadow-none lg:self-auto"
			role="tablist"
		>
			<button
				type="button"
				role="tab"
				aria-selected={activeTab === 'files'}
				class={`rounded-lg px-4 py-2 text-sm font-medium transition-all ${
					activeTab === 'files'
						? 'bg-white text-gray-900 shadow-[0_1px_3px_rgba(15,23,42,0.08)] dark:bg-gray-800 dark:text-white'
						: 'text-gray-600 hover:bg-white/50 hover:text-gray-800 dark:text-gray-400 dark:hover:bg-gray-800/50 dark:hover:text-gray-200'
				}`}
				on:click={() => (activeTab = 'files')}
			>
				{$i18n.t('File Browser')}
			</button>
			<button
				type="button"
				role="tab"
				aria-selected={activeTab === 'terminal'}
				class={`rounded-lg px-4 py-2 text-sm font-medium transition-all ${
					activeTab === 'terminal'
						? 'bg-white text-gray-900 shadow-[0_1px_3px_rgba(15,23,42,0.08)] dark:bg-gray-800 dark:text-white'
						: 'text-gray-600 hover:bg-white/50 hover:text-gray-800 dark:text-gray-400 dark:hover:bg-gray-800/50 dark:hover:text-gray-200'
				}`}
				on:click={() => (activeTab = 'terminal')}
			>
				{$i18n.t('Terminal')}
			</button>
		</div>
	</div>

	<section class="workspace-section flex-1 min-h-0 overflow-hidden">
		{#if terminalEnabled === null}
			<div class="flex h-full items-center justify-center py-16">
				<Spinner className="size-6 text-gray-500" />
			</div>
		{:else if terminalEnabled === false}
			<div class="workspace-empty-state" data-halo-terminal-disabled="true">
				<div class="text-sm font-medium text-gray-900 dark:text-gray-100">
					{$i18n.t('File workspace is disabled')}
				</div>
				<p class="mt-2 text-sm text-gray-600 dark:text-gray-400">
					{$i18n.t('Enable the file browser and terminal under Admin Settings → Code Execution.')}
				</p>
				<div class="mt-4 flex flex-wrap items-center justify-center gap-2">
					<a class="workspace-primary-button" href="/admin/settings">
						{$i18n.t('Open admin settings')}
					</a>
					<button type="button" class="workspace-secondary-button" on:click={checkAvailability}>
						{$i18n.t('Retry')}
					</button>
				</div>
			</div>
		{:else if activeTab === 'files'}
			<FileBrowser />
		{:else}
			<Terminal />
		{/if}
	</section>
</div>
