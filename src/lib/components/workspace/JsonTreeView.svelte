<script lang="ts">
	export let data: any;
	export let key: string = '';
	export let depth: number = 0;
	export let rootExpanded: boolean = true;

	// Top level starts expanded; nested levels start collapsed
	let expanded = depth === 0 ? rootExpanded : false;

	function getType(val: any): string {
		if (val === null) return 'null';
		if (Array.isArray(val)) return 'array';
		return typeof val;
	}

	function getPreview(val: any, type: string): string {
		if (type === 'object') {
			const keys = Object.keys(val);
			return `{${keys.length}}`;
		}
		if (type === 'array') {
			return `[${val.length}]`;
		}
		return '';
	}

	function toggle() {
		expanded = !expanded;
	}

	$: type = getType(data);
	$: isExpandable = type === 'object' || type === 'array';
	$: entries = isExpandable
		? type === 'array'
			? data.map((v: any, i: number) => [String(i), v])
			: Object.entries(data)
		: [];
</script>

<div class="json-tree" style="padding-left: {depth > 0 ? 16 : 0}px;">
	<div class="flex items-start gap-1 py-0.5 leading-5">
		{#if isExpandable}
			<button
				class="flex-shrink-0 w-4 h-5 flex items-center justify-center text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
				on:click={toggle}
			>
				<svg
					class="w-3 h-3 transition-transform {expanded ? 'rotate-90' : ''}"
					fill="currentColor"
					viewBox="0 0 20 20"
				>
					<path
						fill-rule="evenodd"
						d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z"
						clip-rule="evenodd"
					/>
				</svg>
			</button>
		{:else}
			<span class="flex-shrink-0 w-4"></span>
		{/if}

		{#if key !== ''}
			<span class="json-key text-purple-600 dark:text-purple-400 font-medium">"{key}"</span>
			<span class="text-gray-400 dark:text-gray-500 mx-0.5">:</span>
		{/if}

		{#if isExpandable}
			<button
				class="text-gray-400 dark:text-gray-500 text-xs hover:text-gray-600 dark:hover:text-gray-300 cursor-pointer"
				on:click={toggle}
			>
				{#if type === 'object'}
					<span class="text-gray-500 dark:text-gray-400"
						>{'{'}
						<span class="text-gray-400 dark:text-gray-500 text-2xs ml-0.5">
							{Object.keys(data).length}
							{Object.keys(data).length === 1 ? 'key' : 'keys'}
						</span>
						{'}'}</span
					>
				{:else}
					<span class="text-gray-500 dark:text-gray-400"
						>{'['}
						<span class="text-gray-400 dark:text-gray-500 text-2xs ml-0.5">
							{data.length}
							{data.length === 1 ? 'item' : 'items'}
						</span>
						{']'}</span
					>
				{/if}
			</button>
		{:else if type === 'string'}
			<span class="json-string text-green-600 dark:text-green-400">"{data}"</span>
		{:else if type === 'number'}
			<span class="json-number text-blue-600 dark:text-blue-400">{data}</span>
		{:else if type === 'boolean'}
			<span class="json-boolean text-orange-500 dark:text-orange-400">{data}</span>
		{:else if type === 'null'}
			<span class="json-null text-gray-400 dark:text-gray-500 italic">null</span>
		{:else}
			<span class="text-gray-600 dark:text-gray-300">{String(data)}</span>
		{/if}
	</div>

	{#if isExpandable && expanded}
		<div class="border-l border-gray-200 dark:border-gray-700 ml-2">
			{#each entries as [k, v]}
				<svelte:self data={v} key={k} depth={depth + 1} />
			{/each}
		</div>
	{/if}
</div>

<style>
	.json-tree {
		font-family: 'JetBrains Mono', 'Fira Code', 'SF Mono', Consolas, monospace;
		font-size: 12px;
		line-height: 1.5;
	}
	.json-string {
		word-break: break-all;
	}
</style>
