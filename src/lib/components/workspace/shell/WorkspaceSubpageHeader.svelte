<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';

	const i18n: Writable<any> = getContext('i18n');

	export let titleKey = '';
	export let descKey = '';
	export let backHref = '';
	export let backLabelKey = 'Back';
</script>

<!-- Halo: no card around it. A quiet "← Back" over the title, which takes the display face. -->
<section class="halo-subpage-head">
	{#if backHref}
		<a class="halo-back" href={backHref}>
			<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
				<path
					fill-rule="evenodd"
					d="M17 10a.75.75 0 0 1-.75.75H5.612l4.158 3.96a.75.75 0 1 1-1.04 1.08l-5.5-5.25a.75.75 0 0 1 0-1.08l5.5-5.25a.75.75 0 1 1 1.04 1.08L5.612 9.25H16.25A.75.75 0 0 1 17 10Z"
					clip-rule="evenodd"
				/>
			</svg>
			<span>{$i18n.t(backLabelKey)}</span>
		</a>
	{/if}

	<div class="min-w-0">
		<div class="halo-subpage-title">{$i18n.t(titleKey)}</div>
		{#if descKey}
			<p class="halo-settings-desc">{$i18n.t(descKey)}</p>
		{/if}
	</div>
</section>
