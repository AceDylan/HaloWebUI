<script lang="ts">
	import { mobile, showOfficialQuotas, showSidebar, user } from '$lib/stores';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	export let compact = false;
	export let inline = false;
	export let sidebarStyle: 'flat' | 'card' = 'flat';
	export let buttonClass = '';
	export let onOpen: () => void = () => {};

	const openQuotas = () => {
		onOpen();
		if ($mobile) {
			showSidebar.set(false);
		}
		showOfficialQuotas.set(true);
	};
</script>

{#if $user?.role === 'admin'}
	{#if compact}
		<div class="halo-rail-quota-wrap flex justify-center">
			<Tooltip content="官方额度">
				<button
					type="button"
					class="{buttonClass} halo-quota-trigger-compact relative mx-auto"
					aria-haspopup="dialog"
					aria-label="官方额度"
					data-halo-official-quotas-trigger="compact"
					on:click={openQuotas}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.8"
						class="size-[19px]"
						aria-hidden="true"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M4.75 16.25a8.25 8.25 0 1 1 14.5 0"
						/>
						<path stroke-linecap="round" stroke-linejoin="round" d="M12 13.5 15.75 9.25" />
						<circle cx="12" cy="13.5" r="1.25" fill="currentColor" stroke="none" />
					</svg>
					<span
						class="pointer-events-none absolute bottom-1.5 left-1/2 flex -translate-x-1/2 items-center gap-[2px]"
						aria-hidden="true"
					>
						<span class="size-[3.5px] rounded-full bg-amber-500"></span>
						<span class="size-[3.5px] rounded-full bg-cyan-500"></span>
						<span class="size-[3.5px] rounded-full bg-emerald-500"></span>
					</span>
				</button>
			</Tooltip>
		</div>
	{:else if inline}
		<Tooltip content="官方额度">
			<button
				type="button"
				class={sidebarStyle === 'card'
					? 'halo-quota-trigger halo-quota-trigger--inline halo-quota-trigger--card shrink-0'
					: 'halo-quota-trigger halo-quota-trigger--inline shrink-0'}
				aria-haspopup="dialog"
				aria-label="查看官方订阅额度"
				title="官方额度"
				data-halo-official-quotas-trigger="expanded"
				on:click={openQuotas}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.85"
					class="size-4 shrink-0 text-gray-600 dark:text-gray-300"
					aria-hidden="true"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M4.75 16.25a8.25 8.25 0 1 1 14.5 0"
					/>
					<path stroke-linecap="round" stroke-linejoin="round" d="M12 13.5 15.75 9.25" />
					<circle cx="12" cy="13.5" r="1.25" fill="currentColor" stroke="none" />
				</svg>
				<span class="text-xs font-medium whitespace-nowrap text-gray-800 dark:text-gray-100">
					额度
				</span>
				<span class="flex shrink-0 items-center gap-[3px]" aria-hidden="true">
					<span class="size-[5px] rounded-full bg-amber-500"></span>
					<span class="size-[5px] rounded-full bg-cyan-500"></span>
					<span class="size-[5px] rounded-full bg-emerald-500"></span>
				</span>
			</button>
		</Tooltip>
	{:else}
		<div class="mb-1.5">
			<button
				type="button"
				class={sidebarStyle === 'card'
					? `${buttonClass} halo-quota-trigger halo-quota-trigger--card group text-left`
					: 'halo-quota-trigger group w-full text-left'}
				aria-haspopup="dialog"
				aria-label="查看官方订阅额度"
				data-halo-official-quotas-trigger="expanded"
				on:click={openQuotas}
			>
				<span
					class="halo-quota-trigger__icon flex size-6 shrink-0 items-center justify-center rounded-lg"
					aria-hidden="true"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.85"
						class="size-[15px]"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M4.75 16.25a8.25 8.25 0 1 1 14.5 0"
						/>
						<path stroke-linecap="round" stroke-linejoin="round" d="M12 13.5 15.75 9.25" />
						<circle cx="12" cy="13.5" r="1.25" fill="currentColor" stroke="none" />
					</svg>
				</span>

				<span class="min-w-0 flex-1 truncate text-[13px] font-medium text-gray-800 dark:text-gray-100">
					官方额度
				</span>

				<span class="flex shrink-0 items-center gap-1.5" aria-hidden="true">
					<span class="flex items-center gap-1">
						<span class="size-1.5 rounded-full bg-amber-500 ring-2 ring-amber-500/20"></span>
						<span class="size-1.5 rounded-full bg-cyan-500 ring-2 ring-cyan-500/20"></span>
						<span class="size-1.5 rounded-full bg-emerald-500 ring-2 ring-emerald-500/20"></span>
					</span>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="none"
						stroke="currentColor"
						stroke-width="1.8"
						class="size-3.5 text-gray-400 transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-gray-600 dark:text-gray-500 dark:group-hover:text-gray-300"
					>
						<path stroke-linecap="round" stroke-linejoin="round" d="M7.5 5.25 12.25 10 7.5 14.75" />
					</svg>
				</span>
			</button>
		</div>
	{/if}
{/if}
