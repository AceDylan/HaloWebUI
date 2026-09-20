<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import { goto } from '$app/navigation';

	import { WEBUI_NAME, config, showSidebar, user, mobile } from '$lib/stores';
	import { createHubEmbed, openHubInNewTab, type HubEmbed } from '$lib/apis/hub';

	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	const i18n = getContext<Writable<i18nType>>('i18n');

	// The Hub runs its own scripts, keeps its own cookie and opens bookmarks in
	// new tabs, so it needs scripts, its real origin, forms, pop-ups that are not
	// themselves sandboxed, downloads (config export) and confirm() dialogs.
	// Deliberately absent: allow-top-navigation — the framed page must never be
	// able to navigate HaloWebUI itself away.
	const SANDBOX =
		'allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads allow-modals';

	let embed: HubEmbed | null = null;
	let error = '';
	let loading = true;
	// Re-keying the iframe is the only reliable reload: its src is a single-use ticket.
	let frameKey = 0;

	$: notice = describe(embed);

	const describe = (value: HubEmbed | null): string => {
		if (!value) return '';
		const allowed = value.handshake?.frame_ancestors;
		if (Array.isArray(allowed) && !allowed.includes(window.location.origin)) {
			return $i18n.t(
				'The Bookmark Hub does not allow this site to embed it. Add {{origin}} to HUB_FRAME_ANCESTORS on the Hub.',
				{ origin: window.location.origin }
			);
		}
		if (value.sso) return '';
		switch (value.handshake?.reason) {
			case 'secret_unset':
			case 'secret_too_short':
				return $i18n.t(
					'Automatic sign-in is off: HUB_TRUSTED_EMBED_ADMIN_SECRET is not set on HaloWebUI. Unlock the Hub with its own password.'
				);
			case 'hub_not_configured':
				return $i18n.t(
					'Automatic sign-in is off: HUB_TRUSTED_EMBED_ADMIN_SECRET is not set on the Hub. Unlock the Hub with its own password.'
				);
			case 'secret_mismatch':
				return $i18n.t(
					'Automatic sign-in failed: HUB_TRUSTED_EMBED_ADMIN_SECRET differs between HaloWebUI and the Hub.'
				);
			default:
				return $i18n.t('Automatic sign-in is unavailable. Unlock the Hub with its own password.');
		}
	};

	const load = async () => {
		loading = true;
		error = '';
		try {
			embed = await createHubEmbed(localStorage.token);
			frameKey += 1;
		} catch (err) {
			embed = null;
			error = err instanceof Error ? err.message : String(err);
		} finally {
			loading = false;
		}
	};

	onMount(async () => {
		// The embed signs the viewer into the Hub as its administrator.
		if ($user?.role !== 'admin' || $config?.hub_embed?.enabled === false) {
			await goto('/');
			return;
		}
		await load();
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Bookmarks')} | {$WEBUI_NAME}
	</title>
</svelte:head>

<div class="relative flex flex-col w-full h-screen max-h-[100dvh] max-w-full">
	<nav class="px-2.5 pt-1 backdrop-blur-xl drag-region">
		<div class="flex items-center gap-1">
			<div class="{$mobile ? '' : 'hidden'} self-center flex flex-none items-center">
				<button
					id="sidebar-toggle-button"
					class="cursor-pointer p-1.5 flex rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					on:click={() => {
						showSidebar.set(!$showSidebar);
					}}
					aria-label="Toggle Sidebar"
				>
					<div class=" m-auto self-center">
						<MenuLines />
					</div>
				</button>
			</div>

			<div class="flex items-center text-sm font-semibold px-1 py-1">
				{$i18n.t('Bookmarks')}
			</div>

			<div class="ml-auto flex items-center gap-0.5 no-drag-region">
				<Tooltip content={$i18n.t('Reload')}>
					<button
						class="p-1.5 rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition disabled:opacity-50"
						on:click={load}
						disabled={loading}
						aria-label={$i18n.t('Reload')}
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.75"
							stroke="currentColor"
							class="size-4.5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99"
							/>
						</svg>
					</button>
				</Tooltip>

				<Tooltip content={$i18n.t('Open in new tab')}>
					<button
						class="p-1.5 rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						on:click={() => openHubInNewTab(localStorage.token, embed?.hub_url ?? $config?.hub_embed?.url)}
						aria-label={$i18n.t('Open in new tab')}
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.75"
							stroke="currentColor"
							class="size-4.5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25"
							/>
						</svg>
					</button>
				</Tooltip>
			</div>
		</div>
	</nav>

	{#if notice}
		<div
			class="mx-2.5 mt-1 px-3 py-2 rounded-xl text-xs bg-amber-500/10 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
			role="status"
		>
			{notice}
		</div>
	{/if}

	<div class="flex-1 min-h-0 p-2.5 pt-1.5">
		{#if loading && !embed}
			<div class="w-full h-full flex items-center justify-center">
				<Spinner />
			</div>
		{:else if error}
			<div class="w-full h-full flex flex-col items-center justify-center gap-3 text-sm">
				<div class="text-gray-500 dark:text-gray-400 text-center max-w-md">
					{$i18n.t('Could not open the Bookmark Hub.')}
					<span class="block text-xs mt-1 break-all">{error}</span>
				</div>
				<button
					class="px-3.5 py-1.5 rounded-full text-sm font-medium bg-gray-900 hover:bg-gray-850 text-white dark:bg-white dark:hover:bg-gray-100 dark:text-gray-800 transition"
					on:click={load}
				>
					{$i18n.t('Retry')}
				</button>
			</div>
		{:else if embed}
			{#key frameKey}
				<iframe
					id="hub-frame"
					title={$i18n.t('Bookmarks')}
					src={embed.url}
					sandbox={SANDBOX}
					referrerpolicy="no-referrer"
					allow="clipboard-write"
					class="w-full h-full rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-[var(--surface-base)]"
				/>
			{/key}
		{/if}
	</div>
</div>
