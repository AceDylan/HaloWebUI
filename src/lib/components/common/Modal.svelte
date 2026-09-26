<script lang="ts">
	import { onDestroy } from 'svelte';
	import { fade } from 'svelte/transition';

	import { flyAndScale } from '$lib/utils/transitions';
	import { lockBodyScroll, unlockBodyScroll } from '$lib/utils/body-scroll-lock';
	export let show = true;
	export let size = 'md';
	export let containerClassName = 'p-3';
	export let className = 'bg-white/95 dark:bg-gray-900/95 backdrop-blur-sm rounded-2xl';
	export let dismissible = true; // 是否允许点击背景关闭

	let modalElement: HTMLDivElement | null = null;
	let isAttached = false;
	// Focus moves into the dialog while it is open and back where it was when it
	// closes. Otherwise keys meant for the dialog (Esc to close it) also reach
	// the element behind it, e.g. the chat composer when the dialog was opened
	// with a keyboard shortcut.
	let previouslyFocused: HTMLElement | null = null;

	const attachModal = () => {
		if (!modalElement || isAttached) return;
		previouslyFocused =
			document.activeElement instanceof HTMLElement && document.activeElement !== document.body
				? document.activeElement
				: null;
		document.body.appendChild(modalElement);
		window.addEventListener('keydown', handleKeyDown);
		lockBodyScroll();
		isAttached = true;
		// After the content had its chance to autofocus a field.
		requestAnimationFrame(() => {
			if (isAttached && modalElement && !modalElement.contains(document.activeElement)) {
				modalElement.focus({ preventScroll: true });
			}
		});
	};

	const detachModal = () => {
		if (!modalElement || !isAttached) return;
		window.removeEventListener('keydown', handleKeyDown);
		const focusWasInside = modalElement.contains(document.activeElement);
		if (modalElement.parentNode === document.body) {
			document.body.removeChild(modalElement);
		}
		unlockBodyScroll();
		isAttached = false;
		const restore = previouslyFocused;
		previouslyFocused = null;
		if (
			restore?.isConnected &&
			(focusWasInside || !document.activeElement || document.activeElement === document.body)
		) {
			restore.focus({ preventScroll: true });
		}
	};

	const sizeToWidth = (size: string) => {
		if (size === 'full') {
			return 'w-full';
		}
		if (size === 'xs') {
			return 'w-[16rem]';
		} else if (size === 'sm') {
			return 'w-[30rem]';
		} else if (size === 'md') {
			return 'w-[42rem]';
		} else if (size === 'lg') {
			return 'w-[56rem]';
		} else if (size === 'xl') {
			return 'w-[70rem]';
		} else if (size === '2xl') {
			return 'w-[84rem]';
		} else if (size === '3xl') {
			return 'w-[100rem]';
		} else {
			return 'w-[56rem]';
		}
	};

	const handleKeyDown = (event: KeyboardEvent) => {
		if (event.key === 'Escape' && isTopModal() && dismissible) {
			console.log('Escape');
			show = false;
		}
	};

	const isTopModal = () => {
		const modals = document.getElementsByClassName('modal');
		return modals.length && modals[modals.length - 1] === modalElement;
	};

	$: if (show && modalElement) {
		attachModal();
	} else if (modalElement) {
		detachModal();
	}

	onDestroy(() => {
		show = false;
		detachModal();
	});
</script>

{#if show}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
	<div
		bind:this={modalElement}
		aria-modal="true"
		role="dialog"
		tabindex="-1"
		class="modal outline-hidden fixed top-0 right-0 left-0 bottom-0 bg-black/30 dark:bg-black/60 w-full h-screen max-h-[100dvh] {containerClassName}  flex justify-center z-9999 overflow-y-auto overscroll-contain"
		style="scrollbar-gutter: stable;"
		in:fade={{ duration: 10 }}
		on:mousedown={() => {
			if (dismissible) {
				show = false;
			}
		}}
	>
		<div
			class="m-auto max-w-full {sizeToWidth(size)} {size !== 'full'
				? 'mx-2'
				: ''} shadow-3xl min-h-fit scrollbar-hidden {className} border border-white dark:border-gray-850"
			in:flyAndScale
			on:mousedown={(e) => {
				e.stopPropagation();
			}}
		>
			<slot />
		</div>
	</div>
{/if}

<style>
	.modal-content {
		animation: scaleUp 0.1s ease-out forwards;
	}

	@keyframes scaleUp {
		from {
			transform: scale(0.985);
			opacity: 0;
		}
		to {
			transform: scale(1);
			opacity: 1;
		}
	}
</style>
