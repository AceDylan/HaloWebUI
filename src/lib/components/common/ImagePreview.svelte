<script lang="ts">
	import { getContext, onDestroy } from 'svelte';
	import type { Writable } from 'svelte/store';
	import panzoom, { type PanZoom } from 'panzoom';
	import { lockBodyScroll, unlockBodyScroll } from '$lib/utils/body-scroll-lock';
	import { downloadImageFile } from '$lib/utils/image-download';

	const i18n: Writable<any> = getContext('i18n');

	export let show = false;
	export let src = '';
	export let alt = '';
	// Extra buttons in the top bar (e.g. "send to chat"); each closes the preview first.
	export let actions: { id: string; label: string; run: () => void }[] = [];

	let previewElement = null;
	let isAttached = false;

	let instance: PanZoom;

	let sceneParentElement: HTMLElement;
	let sceneElement: HTMLElement;

	// Whether the image is zoomed in: the zoom button zooms in from 1x and resets otherwise
	// (it only reset before, so on a phone it looked like it did nothing).
	let zoomed = false;

	$: if (sceneElement) {
		zoomed = false;
		instance = panzoom(sceneElement, {
			bounds: true,
			boundsPadding: 0.1,

			zoomSpeed: 0.065
		});
		instance.on('transform', () => {
			zoomed = instance.getTransform().scale > 1.01;
		});
	}
	const toggleZoom = () => {
		if (!instance) return;
		if (zoomed) {
			instance.moveTo(0, 0);
			instance.zoomAbs(0, 0, 1);
			return;
		}
		// panzoom takes points relative to the overlay, which covers the viewport.
		instance.smoothZoom(window.innerWidth / 2, window.innerHeight / 2, 2);
	};

	const downloadImage = () => {
		downloadImageFile(src, alt).catch((error) => console.error('Error downloading image:', error));
	};

	const handleKeyDown = (event: KeyboardEvent) => {
		if (event.key === 'Escape') {
			show = false;
		}
	};

	const attachPreview = () => {
		if (!previewElement || isAttached) return;

		document.body.appendChild(previewElement);
		window.addEventListener('keydown', handleKeyDown);
		lockBodyScroll();
		isAttached = true;
	};

	const detachPreview = () => {
		if (!previewElement || !isAttached) return;

		window.removeEventListener('keydown', handleKeyDown);

		if (document.body.contains(previewElement)) {
			document.body.removeChild(previewElement);
		}

		unlockBodyScroll();
		isAttached = false;
	};

	$: if (show && previewElement) {
		attachPreview();
	} else if (previewElement) {
		detachPreview();
	}

	onDestroy(() => {
		show = false;
		detachPreview();
	});
</script>

{#if show}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		bind:this={previewElement}
		data-image-preview
		class="modal fixed top-0 right-0 left-0 bottom-0 bg-black text-white w-full min-h-screen h-screen flex justify-center z-9999 overflow-hidden overscroll-contain"
	>
		<!-- panzoom listens for touchstart on the whole overlay and cancels it, which on a phone
		     also cancels the click of any button here; the bar keeps its touches to itself. -->
		<div
			class=" absolute left-0 w-full flex justify-between select-none z-10 pt-[env(safe-area-inset-top)]"
			data-image-preview-bar
			on:touchstart|stopPropagation
		>
			<div class="shrink-0">
				<button
					class=" p-3.5 sm:p-5"
					aria-label={$i18n.t('Close')}
					on:pointerdown={(e) => {
						e.stopImmediatePropagation();
						e.preventDefault();
						show = false;
					}}
					on:click={(e) => {
						show = false;
					}}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="2"
						stroke="currentColor"
						class="w-6 h-6"
					>
						<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
					</svg>
				</button>
			</div>

			<div class="flex min-w-0 items-center">
				{#each actions as action (action.id)}
					<button
						type="button"
						class="mx-0.5 shrink-0 whitespace-nowrap rounded-full bg-white/15 px-3 py-1.5 text-sm font-medium backdrop-blur transition hover:bg-white/25 sm:mx-1"
						data-image-preview-action={action.id}
						on:pointerdown={(e) => {
							e.stopImmediatePropagation();
							e.preventDefault();
						}}
						on:click={() => {
							show = false;
							action.run();
						}}
					>
						{action.label}
					</button>
				{/each}
				<button
					class=" shrink-0 p-3.5 sm:p-5"
					aria-label={$i18n.t(zoomed ? 'Reset zoom' : 'Zoom in')}
					title={$i18n.t(zoomed ? 'Reset zoom' : 'Zoom in')}
					data-image-preview-zoom={zoomed ? 'reset' : 'in'}
					on:pointerdown={(e) => {
						e.stopImmediatePropagation();
						e.preventDefault();
					}}
					on:click={toggleZoom}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="2"
						stroke="currentColor"
						class="w-6 h-6"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M9 9V4.5M9 9H4.5M9 9 3.75 3.75M9 15v4.5M9 15H4.5M9 15l-5.25 5.25M15 9h4.5M15 9V4.5M15 9l5.25-5.25M15 15h4.5M15 15v4.5m0-4.5 5.25 5.25"
						/>
					</svg>
				</button>
				<button
					class=" shrink-0 p-3.5 sm:p-5"
					aria-label={$i18n.t('Download')}
					data-image-preview-download
					on:pointerdown={(e) => {
						// Keep the press away from the pan/zoom layer; the click (mouse, touch or
						// keyboard) downloads once.
						e.stopImmediatePropagation();
						e.preventDefault();
					}}
					on:click={downloadImage}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="w-6 h-6"
					>
						<path
							d="M10.75 2.75a.75.75 0 0 0-1.5 0v8.614L6.295 8.235a.75.75 0 1 0-1.09 1.03l4.25 4.5a.75.75 0 0 0 1.09 0l4.25-4.5a.75.75 0 0 0-1.09-1.03l-2.955 3.129V2.75Z"
						/>
						<path
							d="M3.5 12.75a.75.75 0 0 0-1.5 0v2.5A2.75 2.75 0 0 0 4.75 18h10.5A2.75 2.75 0 0 0 18 15.25v-2.5a.75.75 0 0 0-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5Z"
						/>
					</svg>
				</button>
			</div>
		</div>
		<div bind:this={sceneElement} class="flex h-full max-h-full justify-center items-center">
			<img {src} {alt} class=" mx-auto h-full object-scale-down select-none" draggable="false" />
		</div>
	</div>
{/if}
