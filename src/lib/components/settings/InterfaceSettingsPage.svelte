<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import InterfacePreferences from '$lib/components/settings/InterfacePreferences.svelte';
	import AdminInterface from '$lib/components/admin/Settings/Interface.svelte';
	import InlineDirtyActions from '$lib/components/admin/Settings/InlineDirtyActions.svelte';
	import { user } from '$lib/stores';
	import {
		INTERFACE_TAB_QUERY_KEY,
		getVisibleInterfaceTabs,
		interfaceTabHref,
		resolveInterfaceTab,
		type InterfaceTab
	} from '$lib/components/settings/interface-tabs';

	import type { Writable } from 'svelte/store';
	import type { UserSettingsContext } from '$lib/types/user-settings';

	const i18n: Writable<any> = getContext('i18n');
	const { saveSettings } = getContext<UserSettingsContext>('user-settings');

	let preferencesForm: InterfacePreferences | null = null;
	let adminForm: AdminInterface | null = null;
	let isAdmin = false;
	let selectedTab: InterfaceTab = 'appearance';

	// Per-section dirty state
	let sectionDirty: Record<string, boolean> = {};
	let tasksDirty = false;
	let saving = false;

	$: isAdmin = $user?.role === 'admin';
	$: activeDirty = selectedTab === 'tasks' ? tasksDirty : (sectionDirty[selectedTab] ?? false);

	// The section is addressed by ?tab= so the settings layout can link to it (second-level
	// nav on desktop). The strip below is the phone/tablet way to switch.
	$: selectedTab = resolveInterfaceTab($page.url.searchParams.get(INTERFACE_TAB_QUERY_KEY), isAdmin);

	const selectTab = (key: InterfaceTab) => {
		if (key === selectedTab) return;
		void goto(interfaceTabHref(key), { replaceState: true, noScroll: true, keepFocus: true });
	};

	$: allTabs = getVisibleInterfaceTabs(isAdmin).map((t) => ({
		...t,
		title: $i18n.t(t.titleKey),
		description: $i18n.t(t.descKey)
	}));

	$: activeTab = allTabs.find((t) => t.key === selectedTab) ?? allTabs[0];

	const handleSave = async () => {
		if (saving) return;
		saving = true;
		try {
			if (selectedTab === 'tasks') {
				await (adminForm as any)?.save?.();
			} else {
				await preferencesForm?.saveSection?.(selectedTab as any);
			}
			toast.success($i18n.t('Settings saved successfully!'));
		} catch (error) {
			console.error(error);
			toast.error($i18n.t('Failed to save settings.'));
		} finally {
			saving = false;
		}
	};

	const handleReset = async () => {
		if (selectedTab === 'tasks') {
			await (adminForm as any)?.reset?.();
		} else {
			await preferencesForm?.resetSection?.(selectedTab as any);
		}
	};
</script>

<div class="h-full space-y-6 overflow-y-auto scrollbar-hidden">
	<div class="max-w-6xl mx-auto space-y-6">
		<!-- ==================== Section header ==================== -->
		<section class="glass-section p-4 space-y-3 sm:p-5">
			{#if activeTab}
				<div class="flex items-start gap-3">
					<div class="glass-icon-badge shrink-0 {activeTab.badgeColor}">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 24 24"
							fill="currentColor"
							class="size-[18px] {activeTab.iconColor}"
						>
							{#each activeTab.iconPaths as pathD}
								<path fill-rule="evenodd" d={pathD} clip-rule="evenodd" />
							{/each}
						</svg>
					</div>
					<div class="min-w-0 flex-1">
						<div class="flex flex-wrap items-center gap-3">
							<!-- One compact line: section name + description. The sub-sections themselves live in
							     the left nav (desktop) or the chip strip below (phone), not in this card. -->
							<h2 class="text-sm font-semibold text-gray-800 dark:text-gray-100">
								{activeTab.title}
							</h2>
							<p class="text-xs text-gray-400 dark:text-gray-500">
								{activeTab.description}
							</p>
							<div class="ml-auto">
								<InlineDirtyActions
									dirty={activeDirty}
									{saving}
									saveAsSubmit={false}
									on:reset={handleReset}
									on:save={handleSave}
								/>
							</div>
						</div>
					</div>
				</div>
			{/if}

			<!-- Phone / tablet: horizontally scrolling chips with dissolved edges. Desktop uses the
			     second-level links in the settings nav instead. -->
			<div
				class="-mx-4 flex gap-1.5 overflow-x-auto px-4 scrollbar-none scroll-fade-x lg:hidden sm:-mx-5 sm:px-5"
				role="tablist"
				aria-label={$i18n.t('Interface')}
			>
				{#each allTabs as tab (tab.key)}
					<button
						type="button"
						role="tab"
						aria-selected={selectedTab === tab.key}
						class="flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1.5 text-[13px] font-medium transition {selectedTab ===
						tab.key
							? 'border-transparent bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-fg)]'
							: 'border-gray-200/80 bg-white/70 text-gray-500 hover:text-gray-800 dark:border-gray-700/70 dark:bg-gray-900/50 dark:text-gray-400 dark:hover:text-gray-100'}"
						on:click={() => selectTab(tab.key)}
					>
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="size-3.5">
							{#each tab.iconPaths as pathD}
								<path fill-rule="evenodd" d={pathD} clip-rule="evenodd" />
							{/each}
						</svg>
						<span>{tab.title}</span>
					</button>
				{/each}
			</div>
		</section>

		<!-- ==================== Tab Content ==================== -->
		{#if selectedTab !== 'tasks'}
			<section class="p-5 space-y-3 transition-all duration-300 {activeDirty ? 'glass-section glass-section-dirty' : 'glass-section'}">
				<InterfacePreferences
					bind:this={preferencesForm}
					{saveSettings}
					embedded={true}
					activeSection={selectedTab}
					on:sectionDirtyChange={(event) => {
						sectionDirty = event.detail?.sections ?? {};
					}}
					on:save={() => {
						toast.success($i18n.t('Settings saved successfully!'));
					}}
				/>
			</section>
		{:else if isAdmin}
			<section class="p-5 space-y-3 transition-all duration-300 {tasksDirty ? 'glass-section glass-section-dirty' : 'glass-section'}">
				<AdminInterface
					bind:this={adminForm}
					embedded={true}
					on:dirtyChange={(event) => {
						tasksDirty = !!event.detail?.value;
					}}
					on:save={() => {
						toast.success($i18n.t('Settings saved successfully!'));
					}}
				/>
			</section>
		{/if}
	</div>
</div>
