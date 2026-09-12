<script lang="ts">
	import { getContext } from 'svelte';
	import { writable } from 'svelte/store';
	import { page } from '$app/stores';
	import { WEBUI_NAME } from '$lib/stores';

	// The root layout provides i18n; fall back to English if the boundary renders before it.
	const i18n = getContext<any>('i18n') ?? writable<any>(null);
	const t = (key: string, fallback: string) => {
		const translated = $i18n?.t?.(key);
		return translated && translated !== key ? translated : fallback;
	};

	$: notFound = $page.status === 404;
	$: title = notFound ? t('Page not found', 'Page not found') : $page.error?.message || '';
</script>

<svelte:head>
	<title>{$page.status} · {$WEBUI_NAME}</title>
</svelte:head>

<div
	class="flex min-h-screen w-full items-center justify-center bg-[var(--surface-base)] px-6 text-gray-900 dark:text-gray-100"
>
	<div class="w-full max-w-md text-center" role="alert">
		<div class="text-6xl font-semibold tracking-tight text-gray-300 dark:text-gray-700">
			{$page.status}
		</div>
		<h1 class="mt-3 text-xl font-semibold">{title}</h1>
		<p class="mt-2 text-sm text-gray-600 dark:text-gray-400">
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
		<div class="mt-6 flex flex-wrap items-center justify-center gap-2">
			<a
				href="/"
				class="inline-flex items-center justify-center rounded-xl bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-primary-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/40 dark:bg-primary-500 dark:hover:bg-primary-400"
			>
				{t('Back to home', 'Back to home')}
			</a>
			<button
				type="button"
				class="inline-flex items-center justify-center rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/40 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-800"
				on:click={() => history.back()}
			>
				{t('Go back', 'Go back')}
			</button>
		</div>
	</div>
</div>
