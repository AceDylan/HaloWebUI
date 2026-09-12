<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import { toast } from 'svelte-sonner';

	import { getSqliteTables, executeSqlQuery } from '$lib/apis/terminal';
	import HaloSelect from '$lib/components/common/HaloSelect.svelte';

	const i18n = getContext<Writable<i18nType>>('i18n');

	export let path: string;
	export let onClose: () => void = () => {};

	interface ColumnInfo {
		name: string;
		type: string;
		notnull: boolean;
		pk: boolean;
	}

	interface TableInfo {
		name: string;
		columns: ColumnInfo[];
	}

	interface QueryResult {
		columns: string[];
		rows: any[][];
		rowCount: number;
	}

	let tables: TableInfo[] = [];
	let selectedTable: string | null = null;
	let loadingTables = true;

	let query = '';
	let queryLimit = 100;
	let executing = false;
	let result: QueryResult | null = null;
	let queryError = '';

	// Column detail popover
	let hoveredTable: string | null = null;

	async function loadTables() {
		loadingTables = true;
		try {
			tables = await getSqliteTables(localStorage.token, path);
		} catch (e: any) {
			toast.error($i18n.t(typeof e === 'string' ? e : 'Failed to load tables'));
		} finally {
			loadingTables = false;
		}
	}

	function selectTable(tableName: string) {
		selectedTable = tableName;
		query = `SELECT * FROM [${tableName}] LIMIT ${queryLimit}`;
		executeQuery();
	}

	async function executeQuery() {
		if (!query.trim()) return;
		executing = true;
		queryError = '';
		result = null;
		try {
			result = await executeSqlQuery(localStorage.token, path, query, queryLimit);
		} catch (e: any) {
			queryError = typeof e === 'string' ? e : 'Query execution failed';
		} finally {
			executing = false;
		}
	}

	function handleQueryKeydown(e: KeyboardEvent) {
		if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
			e.preventDefault();
			executeQuery();
		}
	}

	function getFileName(p: string): string {
		return p.split('/').pop() || p;
	}

	onMount(() => {
		loadTables();
	});
</script>

<div class="flex flex-col h-full min-h-0">
	<!-- Header bar -->
	<div
		class="flex items-center justify-between px-3 py-1.5 bg-gray-50 dark:bg-gray-800/50 border-b border-gray-200 dark:border-gray-700 flex-shrink-0"
	>
		<div class="flex items-center gap-2 min-w-0">
			<svg
				class="w-4 h-4 text-amber-500 flex-shrink-0"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
			>
				<ellipse cx="12" cy="5" rx="9" ry="3" />
				<path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5" />
				<path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3" />
			</svg>
			<span class="text-sm font-mono truncate text-gray-600 dark:text-gray-300">
				{getFileName(path)}
			</span>
			<span class="text-2xs text-gray-400 bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded"
				>SQLite</span
			>
		</div>
		<button
			class="px-2 py-1 text-xs rounded-lg text-gray-500 hover:bg-gray-200 dark:hover:bg-gray-700 transition"
			on:click={onClose}
		>
			{$i18n.t('Close')}
		</button>
	</div>

	<!-- Main content: sidebar + editor/results -->
	<div class="flex flex-1 min-h-0">
		<!-- Left: Table list -->
		<div
			class="w-48 flex-shrink-0 border-r border-gray-200 dark:border-gray-700 overflow-y-auto bg-gray-50/50 dark:bg-gray-800/30"
		>
			<div class="px-2 py-1.5 text-2xs font-semibold uppercase tracking-wider text-gray-400">
				{$i18n.t('Tables')}
				{#if !loadingTables}
					<span class="font-normal">({tables.length})</span>
				{/if}
			</div>
			{#if loadingTables}
				<div class="flex items-center justify-center py-6 text-gray-400">
					<svg class="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
						<circle
							class="opacity-25"
							cx="12"
							cy="12"
							r="10"
							stroke="currentColor"
							stroke-width="4"
						/>
						<path
							class="opacity-75"
							fill="currentColor"
							d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
						/>
					</svg>
				</div>
			{:else if tables.length === 0}
				<div class="px-2 py-3 text-xs text-gray-400 text-center">
					{$i18n.t('No tables found')}
				</div>
			{:else}
				{#each tables as table}
					<div class="relative">
						<button
							class="w-full text-left px-2 py-1 text-xs truncate hover:bg-gray-100 dark:hover:bg-gray-700 transition
								{selectedTable === table.name
								? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 font-medium'
								: 'text-gray-600 dark:text-gray-300'}"
							on:click={() => selectTable(table.name)}
							on:mouseenter={() => (hoveredTable = table.name)}
							on:mouseleave={() => (hoveredTable = null)}
						>
							<span class="mr-1 opacity-60">
								<svg
									class="w-3 h-3 inline -mt-0.5"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
								>
									<rect x="3" y="3" width="18" height="18" rx="2" />
									<path d="M3 9h18M3 15h18M9 3v18" />
								</svg>
							</span>
							{table.name}
							<span class="text-2xs text-gray-400 ml-0.5">({table.columns.length})</span>
						</button>
						<!-- Column tooltip on hover -->
						{#if hoveredTable === table.name}
							<div
								class="absolute left-full top-0 ml-1 z-50 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-2 min-w-[180px] max-w-[280px]"
							>
								<div class="text-2xs font-semibold text-gray-500 mb-1 uppercase">
									{table.name}
								</div>
								{#each table.columns as col}
									<div class="flex items-center gap-1 text-2xs py-0.5">
										{#if col.pk}
											<span class="text-amber-500 flex-shrink-0" title="Primary Key">
												<svg class="w-2.5 h-2.5" viewBox="0 0 24 24" fill="currentColor">
													<path d="M7 14l5-5 5 5z" />
												</svg>
											</span>
										{:else}
											<span class="w-2.5 flex-shrink-0"></span>
										{/if}
										<span class="text-gray-700 dark:text-gray-200 truncate">{col.name}</span>
										<span class="text-gray-400 ml-auto text-2xs flex-shrink-0"
											>{col.type || 'any'}</span
										>
										{#if col.notnull}
											<span class="text-red-400 text-[9px] flex-shrink-0">NN</span>
										{/if}
									</div>
								{/each}
							</div>
						{/if}
					</div>
				{/each}
			{/if}
		</div>

		<!-- Right: Query editor + results -->
		<div class="flex flex-col flex-1 min-w-0 min-h-0">
			<!-- Query editor -->
			<div class="flex-shrink-0 border-b border-gray-200 dark:border-gray-700">
				<div class="flex items-stretch">
					<textarea
						class="flex-1 px-3 py-2 font-mono text-xs bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-200 resize-none outline-none min-h-[60px] max-h-[120px]"
						placeholder={$i18n.t('Enter SQL query... (Ctrl+Enter to execute)')}
						spellcheck="false"
						bind:value={query}
						on:keydown={handleQueryKeydown}
					/>
					<div
						class="flex flex-col gap-1 p-1.5 bg-gray-50 dark:bg-gray-800/50 border-l border-gray-200 dark:border-gray-700"
					>
						<button
							class="px-3 py-1.5 text-xs rounded-lg bg-blue-500 text-white hover:bg-blue-600 transition disabled:opacity-50 whitespace-nowrap"
							disabled={executing || !query.trim()}
							on:click={executeQuery}
						>
							{#if executing}
								<svg class="animate-spin h-3 w-3 inline mr-1" fill="none" viewBox="0 0 24 24">
									<circle
										class="opacity-25"
										cx="12"
										cy="12"
										r="10"
										stroke="currentColor"
										stroke-width="4"
									/>
									<path
										class="opacity-75"
										fill="currentColor"
										d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
									/>
								</svg>
							{/if}
							{$i18n.t('Execute')}
						</button>
						<div class="flex items-center gap-1">
							<label for="qlimit" class="text-2xs text-gray-400 whitespace-nowrap"
								>{$i18n.t('Limit')}</label
							>
							<HaloSelect
								bind:value={queryLimit}
								options={[
									{ value: 50, label: '50' },
									{ value: 100, label: '100' },
									{ value: 500, label: '500' },
									{ value: 1000, label: '1000' }
								]}
								className="text-2xs"
							/>
						</div>
					</div>
				</div>
			</div>

			<!-- Results area -->
			<div class="flex-1 min-h-0 overflow-auto">
				{#if queryError}
					<div
						class="p-3 text-sm text-red-500 bg-red-50 dark:bg-red-900/10 border-b border-red-200 dark:border-red-800/30"
					>
						<span class="font-medium">{$i18n.t('Error')}:</span>
						{queryError}
					</div>
				{/if}

				{#if executing}
					<div class="flex items-center justify-center py-12 text-gray-400 text-sm">
						<svg class="animate-spin h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24">
							<circle
								class="opacity-25"
								cx="12"
								cy="12"
								r="10"
								stroke="currentColor"
								stroke-width="4"
							/>
							<path
								class="opacity-75"
								fill="currentColor"
								d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
							/>
						</svg>
						{$i18n.t('Executing query...')}
					</div>
				{:else if result}
					{#if result.columns.length === 0}
						<div class="flex items-center justify-center py-8 text-gray-400 text-sm">
							{$i18n.t('Query executed successfully (no results)')}
						</div>
					{:else}
						<!-- Row count bar -->
						<div
							class="px-3 py-1 text-2xs text-gray-400 bg-gray-50 dark:bg-gray-800/30 border-b border-gray-100 dark:border-gray-800 sticky top-0"
						>
							{result.rowCount}
							{$i18n.t('rows')}
							{#if result.rowCount >= queryLimit}
								<span class="text-amber-500 ml-1">({$i18n.t('limit reached')})</span>
							{/if}
						</div>
						<table class="w-full text-xs border-collapse">
							<thead class="bg-gray-50 dark:bg-gray-800/50 sticky top-[22px]">
								<tr>
									<th
										class="px-2 py-1.5 text-left font-medium text-gray-400 border-b border-r border-gray-200 dark:border-gray-700 w-10 text-center"
										>#</th
									>
									{#each result.columns as col}
										<th
											class="px-2 py-1.5 text-left font-medium text-gray-600 dark:text-gray-300 border-b border-r border-gray-200 dark:border-gray-700 whitespace-nowrap"
										>
											{col}
										</th>
									{/each}
								</tr>
							</thead>
							<tbody>
								{#each result.rows as row, rowIdx}
									<tr
										class="hover:bg-blue-50/50 dark:hover:bg-blue-900/10 {rowIdx % 2 === 1
											? 'bg-gray-50/50 dark:bg-gray-800/20'
											: ''}"
									>
										<td
											class="px-2 py-1 text-center text-gray-300 dark:text-gray-600 border-r border-gray-100 dark:border-gray-800 tabular-nums"
										>
											{rowIdx + 1}
										</td>
										{#each row as cell}
											<td
												class="px-2 py-1 border-r border-gray-100 dark:border-gray-800 max-w-[300px] truncate font-mono
												{cell === null ? 'text-gray-300 dark:text-gray-600 italic' : 'text-gray-700 dark:text-gray-200'}"
												title={cell === null ? 'NULL' : String(cell)}
											>
												{cell === null ? 'NULL' : cell}
											</td>
										{/each}
									</tr>
								{/each}
							</tbody>
						</table>
					{/if}
				{:else if !queryError}
					<div class="flex flex-col items-center justify-center py-12 text-gray-400 text-sm gap-2">
						<svg
							class="w-8 h-8 opacity-30"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.5"
						>
							<ellipse cx="12" cy="5" rx="9" ry="3" />
							<path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5" />
							<path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3" />
						</svg>
						{$i18n.t('Select a table or write a query')}
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>
