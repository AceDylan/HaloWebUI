<script lang="ts">
	import { getContext } from 'svelte';
	import { writable } from 'svelte/store';
	import { page } from '$app/stores';
	import { WEBUI_NAME } from '$lib/stores';
	import { isFramed } from '$lib/utils/hub-embed';

	// The root layout provides i18n; fall back to English if the boundary renders before it.
	const i18n = getContext<any>('i18n') ?? writable<any>(null);
	const t = (key: string, fallback: string) => {
		const translated = $i18n?.t?.(key);
		return translated && translated !== key ? translated : fallback;
	};

	// In the Bookmark Hub's frame, Back belongs to the Hub (it would leave this tab); "Back to home" stays.
	const framed = typeof window !== 'undefined' && isFramed();

	$: notFound = $page.status === 404;
	$: title = notFound ? t('Page not found', 'Page not found') : $page.error?.message || '';
</script>

<svelte:head>
	<title>{$page.status} · {$WEBUI_NAME}</title>
</svelte:head>

<div
	class="halo-lost flex min-h-screen w-full items-center justify-center bg-[var(--surface-base)] px-6 text-gray-900 dark:text-gray-100"
>
	<div class="w-full max-w-md text-center" role="alert">
		<div class="halo-lost__mark" aria-hidden="true">
			<span class="halo-lost__orbit"></span>
			<span class="halo-lost__ring"></span>
			<span class="halo-lost__planet"></span>
		</div>
		<div class="halo-lost__code">{$page.status}</div>
		<h1 class="halo-lost__title font-display">{title}</h1>
		<p class="mt-2 text-sm text-gray-500 dark:text-gray-400">
			{#if notFound}
				{t(
					'The page you are looking for does not exist or has been moved.',
					'The page you are looking for does not exist or has been moved.'
				)}
			{:else}
				{t(
					'Something went wrong while loading this page.',
					'Something went wrong while loading this page.'
				)}
			{/if}
		</p>
		<div class="mt-7 flex flex-wrap items-center justify-center gap-2">
			<a href="/" class="workspace-primary-button">
				{t('Back to home', 'Back to home')}
			</a>
			{#if !framed}
				<button type="button" class="workspace-secondary-button" on:click={() => history.back()}>
					{t('Go back', 'Go back')}
				</button>
			{/if}
		</div>
	</div>
</div>
