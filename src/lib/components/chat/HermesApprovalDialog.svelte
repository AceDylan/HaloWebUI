<script lang="ts">
	import { createEventDispatcher, getContext, onDestroy, onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import { flyAndScale } from '$lib/utils/transitions';
	import { lockBodyScroll, unlockBodyScroll } from '$lib/utils/body-scroll-lock';
	import type { HermesApprovalRequest } from '$lib/utils/hermes';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher<{ choose: string }>();

	export let show = false;
	export let request: HermesApprovalRequest | null = null;

	// Dialog order and wording for what hermes accepts on the approval endpoint.
	// "session" is the hermes session = this chat, so it reads as "this chat".
	const CHOICE_ORDER = ['deny', 'once', 'session', 'always'];
	const labelFor = (choice: string) =>
		({
			once: $i18n.t('Allow once'),
			session: $i18n.t('Allow for this chat'),
			always: $i18n.t('Always allow'),
			deny: $i18n.t('Deny')
		})[choice] ?? choice;

	$: choices = CHOICE_ORDER.filter((choice) =>
		(request?.choices ?? ['once', 'deny']).includes(choice)
	);

	// Countdown to the auto-deny so the person knows how long they have.
	let now = Date.now() / 1000;
	let clock: ReturnType<typeof setInterval> | null = null;
	$: remaining =
		request?.timeout && request?.requested_at
			? Math.max(0, Math.round(request.requested_at + request.timeout - now))
			: null;

	let modalElement: HTMLDivElement | null = null;
	let mounted = false;
	let attached = false;

	const choose = (choice: string) => {
		if (!show) return;
		show = false;
		dispatch('choose', choice);
	};

	const handleKeyDown = (event: KeyboardEvent) => {
		if (event.key === 'Escape') {
			event.preventDefault();
			choose('deny');
		} else if (event.key === 'Enter' && !event.shiftKey && !event.metaKey && !event.ctrlKey) {
			event.preventDefault();
			choose('once');
		}
	};

	const attach = () => {
		if (!modalElement || attached) return;
		document.body.appendChild(modalElement);
		window.addEventListener('keydown', handleKeyDown);
		lockBodyScroll();
		attached = true;
		now = Date.now() / 1000;
		clock = setInterval(() => {
			now = Date.now() / 1000;
		}, 1000);
	};

	const detach = () => {
		if (clock) {
			clearInterval(clock);
			clock = null;
		}
		if (!modalElement || !attached) return;
		window.removeEventListener('keydown', handleKeyDown);
		if (document.body.contains(modalElement)) {
			document.body.removeChild(modalElement);
		}
		unlockBodyScroll();
		attached = false;
	};

	onMount(() => {
		mounted = true;
	});

	$: if (mounted) {
		if (show && modalElement) {
			attach();
		} else if (modalElement) {
			detach();
		}
	}

	onDestroy(() => {
		show = false;
		detach();
	});
</script>

{#if show}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		bind:this={modalElement}
		data-halo-hermes-approval-dialog
		class="fixed inset-0 z-99999999 flex h-screen max-h-[100dvh] w-full justify-center overflow-hidden overscroll-contain bg-black/60"
		in:fade={{ duration: 10 }}
		on:mousedown={() => choose('deny')}
	>
		<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
		<div
			class="m-auto mx-2 w-[36rem] max-w-full rounded-2xl border border-white bg-white/95 shadow-3xl backdrop-blur-sm dark:border-gray-900 dark:bg-gray-950/95"
			role="dialog"
			aria-modal="true"
			aria-labelledby="hermes-approval-title"
			in:flyAndScale
			on:mousedown={(e) => e.stopPropagation()}
		>
			<div class="flex flex-col px-6 py-5 sm:px-7">
				<div class="flex items-start gap-3">
					<div
						class="flex size-9 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
						aria-hidden="true"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							class="size-5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="m6.75 7.5 3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0 0 21 18V6a2.25 2.25 0 0 0-2.25-2.25H5.25A2.25 2.25 0 0 0 3 6v12a2.25 2.25 0 0 0 2.25 2.25Z"
							/>
						</svg>
					</div>
					<div class="min-w-0 flex-1">
						<div
							id="hermes-approval-title"
							class="text-base font-semibold text-gray-900 dark:text-gray-100"
						>
							{request?.title || $i18n.t('Hermes asks to run a command')}
						</div>
						<div class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t('The task is paused until you answer.')}
							{#if remaining !== null}
								<span class="tabular-nums">
									· {$i18n.t('Auto-denied in {{seconds}}s', { seconds: remaining })}
								</span>
							{/if}
						</div>
					</div>
				</div>

				{#if request?.description}
					<p class="mt-4 whitespace-pre-wrap text-sm leading-6 text-gray-700 dark:text-gray-300">
						{request.description}
					</p>
				{/if}

				{#if request?.command}
					<pre
						data-halo-hermes-approval-command
						class="mt-3 max-h-56 overflow-auto rounded-xl border border-gray-200/70 bg-gray-50 px-3.5 py-3 font-mono text-[13px] leading-5 text-gray-800 whitespace-pre-wrap break-all dark:border-gray-800 dark:bg-gray-900 dark:text-gray-200">{request.command}</pre>
				{/if}

				<div class="mt-5 grid gap-2 sm:grid-cols-[auto_1fr] sm:items-center">
					<div class="flex flex-wrap justify-end gap-2 sm:col-span-2">
						{#each choices as choice (choice)}
							<button
								type="button"
								data-halo-hermes-approval-choice={choice}
								class="rounded-xl px-4 py-2 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/50 {choice ===
								'once'
									? 'bg-primary-600 text-white hover:bg-primary-700 dark:bg-primary-500 dark:hover:bg-primary-400'
									: choice === 'deny'
										? 'bg-gray-100 text-gray-800 hover:bg-gray-200 dark:bg-gray-850 dark:text-white dark:hover:bg-gray-800'
										: 'border border-gray-200 bg-white text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-800'}"
								on:click={() => choose(choice)}
							>
								{labelFor(choice)}
							</button>
						{/each}
					</div>
					<div class="text-2xs text-gray-400 dark:text-gray-500 sm:col-span-2 sm:text-right">
						{$i18n.t('Enter = allow once · Esc = deny')}
					</div>
				</div>
			</div>
		</div>
	</div>
{/if}
