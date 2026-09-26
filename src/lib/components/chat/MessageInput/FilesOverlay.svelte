<script lang="ts">
	import { getContext, onDestroy } from 'svelte';
	import type { Writable } from 'svelte/store';
	import { showSidebar } from '$lib/stores';
	import AddFilesPlaceholder from '$lib/components/AddFilesPlaceholder.svelte';
	import { lockBodyScroll, unlockBodyScroll } from '$lib/utils/body-scroll-lock';

	const i18n: Writable<any> = getContext('i18n');

	export let show = false;
	let overlayElement = null;
	let isAttached = false;

	const attachOverlay = () => {
		if (!overlayElement || isAttached) return;

		document.body.appendChild(overlayElement);
		lockBodyScroll();
		isAttached = true;
	};

	const detachOverlay = () => {
		if (!overlayElement || !isAttached) return;

		if (document.body.contains(overlayElement)) {
			document.body.removeChild(overlayElement);
		}

		unlockBodyScroll();
		isAttached = false;
	};

	$: if (show && overlayElement) {
		attachOverlay();
	} else if (overlayElement) {
		detachOverlay();
	}

	onDestroy(() => {
		detachOverlay();
	});
</script>

{#if show}
	<div
		bind:this={overlayElement}
		class="fixed {$showSidebar
			? 'left-0 md:left-[260px] md:w-[calc(100%-260px)]'
			: 'left-0'}  fixed top-0 right-0 bottom-0 w-full h-full flex z-9999 touch-none pointer-events-none"
		id="dropzone"
		role="region"
		aria-label={$i18n.t('Drag and Drop Container')}
	>
		<div class="absolute w-full h-full backdrop-blur-sm bg-gray-800/40 flex justify-center">
			<div class="m-auto pt-64 flex flex-col justify-center">
				<div class="max-w-md">
					<AddFilesPlaceholder />
				</div>
			</div>
		</div>
	</div>
{/if}
