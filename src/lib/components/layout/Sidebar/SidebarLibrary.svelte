<script lang="ts">
	import { onDestroy, tick } from 'svelte';
	import { afterNavigate } from '$app/navigation';
	import { page } from '$app/stores';
	import { user } from '$lib/stores';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import SidebarModeIcon from './SidebarModeIcon.svelte';
	import { isAt, libraryDestinations, type Destination } from '$lib/utils/destinations';
	import { computeSidePopoverPosition } from '$lib/utils/sidebar-layout';

	/**
	 * What used to be the workspace, now that the image studio is a mode of its own: 助手 (my
	 * assistants | built-in templates), 提示词 and (admins) 定时 — Hermes' scheduled jobs — side by
	 * side under the modes in the open sidebar, or collapsed into one popover trigger in the rail.
	 */
	export let compact = false;
	export let dense = false;
	export let actionItemClass = '';
	export let iconButtonClass = '';
	export let onNavigate: () => void = () => {};
	export let onOpen: () => void = () => {};

	$: path = $page?.url?.pathname ?? '';
	$: links = libraryDestinations($user).map((link) => ({ ...link, active: isAt(link, path) }));
	$: anyActive = links.some((link) => link.active);

	let popoverOpen = false;
	let triggerEl: HTMLButtonElement | null = null;
	let popoverEl: HTMLDivElement | null = null;
	let popoverLeft = 68;
	let popoverTop = 240;
	let listenersBound = false;

	const shortSubtitle = (link: Destination): string => {
		const idx = link.title.indexOf('：');
		return idx >= 0 ? link.title.slice(idx + 1) : link.title;
	};

	function portalToBody(node: HTMLElement) {
		document.body.appendChild(node);
		return {
			destroy() {
				node.remove();
			}
		};
	}

	const updatePopoverPosition = () => {
		if (!triggerEl || typeof window === 'undefined') return;
		const rect = triggerEl.getBoundingClientRect();
		const panelWidth = popoverEl?.offsetWidth || 216;
		const panelHeight = popoverEl?.offsetHeight || links.length * 54 + 34;
		const pos = computeSidePopoverPosition(
			rect,
			{ width: panelWidth, height: panelHeight },
			{ width: window.innerWidth, height: window.innerHeight }
		);
		popoverLeft = pos.left;
		popoverTop = pos.top;
	};

	const handleOutsideEvent = (event: Event) => {
		const target = event.target as Node | null;
		if (!target) return;
		if (triggerEl?.contains(target) || popoverEl?.contains(target)) {
			return;
		}
		closePopover();
	};

	const handleKeyDown = (event: KeyboardEvent) => {
		if (event.key === 'Escape') {
			event.stopPropagation();
			closePopover();
			triggerEl?.focus();
		}
	};

	const handleResize = () => {
		closePopover();
	};

	const bindGlobalListeners = (bind: boolean) => {
		if (typeof window === 'undefined') return;
		if (bind === listenersBound) return;
		listenersBound = bind;
		const fn = (bind ? window.addEventListener : window.removeEventListener).bind(window);
		fn('pointerdown', handleOutsideEvent, true);
		fn('click', handleOutsideEvent, true);
		fn('keydown', handleKeyDown);
		fn('resize', handleResize);
	};

	const closePopover = () => {
		if (!popoverOpen && !listenersBound) return;
		popoverOpen = false;
		bindGlobalListeners(false);
	};

	const togglePopover = async () => {
		if (popoverOpen) {
			closePopover();
			return;
		}
		onOpen();
		popoverOpen = true;
		updatePopoverPosition();
		bindGlobalListeners(true);
		await tick();
		if (popoverOpen) {
			updatePopoverPosition();
		}
	};

	$: if ((!compact || links.length <= 1) && popoverOpen) {
		closePopover();
	}

	if (typeof afterNavigate === 'function') {
		afterNavigate(() => {
			closePopover();
		});
	}

	onDestroy(() => {
		bindGlobalListeners(false);
	});
</script>

{#if compact}
	{#if links.length === 1}
		{@const link = links[0]}
		<Tooltip content={link.title}>
			<a
				class={iconButtonClass}
				href={link.href}
				aria-label={link.title}
				aria-current={link.active ? 'page' : undefined}
				draggable="false"
				on:click={onNavigate}
				data-sidebar-library={link.key}
			>
				<SidebarModeIcon mode={link.key} />
			</a>
		</Tooltip>
	{:else if links.length > 1}
		<Tooltip content={`工具库（${links.map((l) => l.label).join(' / ')}）`}>
			<button
				bind:this={triggerEl}
				type="button"
				class="{iconButtonClass} relative"
				aria-haspopup="menu"
				aria-expanded={popoverOpen}
				aria-current={anyActive ? 'page' : undefined}
				aria-label={`工具库（${links.map((l) => l.label).join('、')}）`}
				data-sidebar-library-trigger
				on:click={togglePopover}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.85"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="size-5"
					aria-hidden="true"
				>
					<rect x="3" y="3" width="7.5" height="7.5" rx="2" />
					<rect x="13.5" y="3" width="7.5" height="7.5" rx="2" />
					<rect x="3" y="13.5" width="7.5" height="7.5" rx="2" />
					<rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2" />
				</svg>
			</button>
		</Tooltip>

		{#if popoverOpen}
			<div
				use:portalToBody
				bind:this={popoverEl}
				role="menu"
				aria-label="工具库"
				data-sidebar-library-popover
				class="halo-rail-popover fixed z-[70] w-[216px] rounded-2xl p-1.5"
				style="left: {popoverLeft}px; top: {popoverTop}px;"
			>
				<div class="px-2.5 pt-1 pb-1 text-[11px] font-medium text-gray-400 dark:text-gray-500">
					工具库
				</div>
				<div class="flex flex-col gap-0.5">
					{#each links as link (link.key)}
						<a
							role="menuitem"
							href={link.href}
							data-sidebar-library={link.key}
							aria-current={link.active ? 'page' : undefined}
							draggable="false"
							class="halo-rail-popover__item flex items-start gap-2.5 rounded-xl px-2.5 py-2 text-left transition"
							class:is-active={link.active}
							on:click={() => {
								closePopover();
								onNavigate();
							}}
						>
							<span class="mt-0.5 shrink-0 text-gray-500 dark:text-gray-400">
								<SidebarModeIcon mode={link.key} className="size-4" />
							</span>
							<span class="min-w-0 flex-1">
								<span
									class="block text-[13px] font-medium leading-tight text-gray-800 dark:text-gray-100"
									data-sidebar-library-label
								>
									{link.label}
								</span>
								<span class="mt-0.5 block truncate text-[11px] text-gray-500 dark:text-gray-400">
									{shortSubtitle(link)}
								</span>
							</span>
						</a>
					{/each}
				</div>
			</div>
		{/if}
	{/if}
{:else if links.length}
	<div
		class="grid gap-1 px-2 text-gray-700 dark:text-gray-200"
		style="grid-template-columns: repeat({links.length}, minmax(0, 1fr))"
		data-sidebar-library-row
	>
		{#each links as link (link.key)}
			<a
				class="{actionItemClass} halo-library-chip min-w-0"
				class:halo-library-chip--dense={dense}
				href={link.href}
				title={link.title}
				aria-current={link.active ? 'page' : undefined}
				draggable="false"
				on:click={onNavigate}
				data-sidebar-library={link.key}
			>
				<SidebarModeIcon mode={link.key} />
				<span class="truncate">{link.label}</span>
			</a>
		{/each}
	</div>
{/if}

<style>
	/* Three to a row in a ~240px sidebar: the full-width row's padding, gap and 18px icon left
	   「提示词」 room for one character, so the chips centre a smaller icon and drop the slack. */
	.halo-library-chip {
		justify-content: center;
		gap: 0.375rem;
		padding: 0.4375rem 0.375rem;
		font-size: 0.8125rem;
		font-weight: 500;
	}
	.halo-library-chip--dense {
		gap: 0.3125rem;
		padding: 0.3125rem 0.375rem;
		font-size: 0.78125rem;
	}
	.halo-library-chip :global(svg) {
		width: 1rem;
		height: 1rem;
	}
</style>
