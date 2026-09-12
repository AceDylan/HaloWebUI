<script lang="ts">
	import { toast } from 'svelte-sonner';
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import { goto } from '$app/navigation';
	import { onMount, getContext } from 'svelte';
	import { WEBUI_NAME, config, prompts as _prompts, user } from '$lib/stores';

	import {
		createNewPrompt,
		deletePromptById,
		getPrompts,
		getPromptList,
		togglePromptById
	} from '$lib/apis/prompts';

	import PromptMenu from './Prompts/PromptMenu.svelte';
	import EllipsisHorizontal from '../icons/EllipsisHorizontal.svelte';
	import DeleteConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Search from '../icons/Search.svelte';
	import Plus from '../icons/Plus.svelte';
	import ChevronRight from '../icons/ChevronRight.svelte';
	import Spinner from '../common/Spinner.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import { capitalizeFirstLetter } from '$lib/utils';
	import HaloSelect from '$lib/components/common/HaloSelect.svelte';
	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import { DropdownMenu } from 'bits-ui';
	import { flyAndScale } from '$lib/utils/transitions';
	import ArrowUpTray from '$lib/components/icons/ArrowUpTray.svelte';
	import ArrowDownTray from '$lib/components/icons/ArrowDownTray.svelte';

	const i18n = getContext('i18n');
	let promptsImportInputElement: HTMLInputElement;
	let loaded = false;

	let importFiles = '';
	let showMoreMenu = false;
	let query = '';

	let prompts = [];
	let totalCount = 0;
	let currentPage = 1;
	const pageSize = 30;

	let showDeleteConfirm = false;
	let deletePromptItem = null;

	let filteredItems = [];
	let sortBy = 'updated'; // 'name' | 'updated'

	$: totalPages = Math.max(1, Math.ceil(totalCount / pageSize));

	const sortItems = (items: any[]) => {
		return [...items].sort((a, b) => {
			if (sortBy === 'name')
				return (a.name || a.command || '').localeCompare(b.name || b.command || '');
			return (b.updated_at || 0) - (a.updated_at || 0);
		});
	};

	$: filteredItems = sortItems(
		prompts.filter(
			(p) =>
				query === '' ||
				p.command.toLowerCase().includes(query.toLowerCase()) ||
				(p.name || '').toLowerCase().includes(query.toLowerCase()) ||
				(p.tags || []).some((t: string) => t.toLowerCase().includes(query.toLowerCase()))
		)
	);

	const shareHandler = async (prompt) => {
		toast.success($i18n.t('Redirecting you to Open WebUI Community'));

		const url = 'https://openwebui.com';

		const tab = await window.open(`${url}/prompts/create`, '_blank');
		window.addEventListener(
			'message',
			(event) => {
				if (event.origin !== url) return;
				if (event.data === 'loaded') {
					tab.postMessage(JSON.stringify(prompt), '*');
				}
			},
			false
		);
	};

	const cloneHandler = async (prompt) => {
		sessionStorage.prompt = JSON.stringify({
			...prompt,
			name: `${prompt.name || prompt.command} (Clone)`
		});
		goto('/workspace/prompts/create');
	};

	const exportHandler = async (prompt) => {
		let blob = new Blob([JSON.stringify([prompt])], {
			type: 'application/json'
		});
		saveAs(blob, `prompt-export-${Date.now()}.json`);
	};

	const deleteHandler = async (prompt) => {
		await deletePromptById(localStorage.token, prompt.id);
		await init();
	};

	const toggleHandler = async (prompt) => {
		const res = await togglePromptById(localStorage.token, prompt.id);
		if (res) {
			await init();
		}
	};

	const init = async () => {
		const orderBy = sortBy === 'name' ? 'name' : 'updated_at';
		const result = await getPromptList(localStorage.token, currentPage, pageSize, orderBy);
		prompts = result.items;
		totalCount = result.total;
		await _prompts.set(await getPrompts(localStorage.token));
	};

	const goToPage = async (page: number) => {
		if (page < 1 || page > totalPages) return;
		currentPage = page;
		await init();
	};

	onMount(async () => {
		await init();
		loaded = true;
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Prompts')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<DeleteConfirmDialog
		bind:show={showDeleteConfirm}
		title={$i18n.t('Delete prompt?')}
		on:confirm={() => {
			deleteHandler(deletePromptItem);
		}}
	>
		<div class=" text-sm text-gray-500">
			{$i18n.t('This will delete')} <span class="  font-semibold">{deletePromptItem.command}</span>.
		</div>
	</DeleteConfirmDialog>

	<div class="space-y-4">
		<div class="workspace-toolbar-row">
			<div class="workspace-count-pill">
				{totalCount} {$i18n.t('Prompts')}
			</div>

			<div class="workspace-toolbar">
					<div class="workspace-search workspace-toolbar-search">
						<Search className="size-4 text-gray-400" />
						<input
							class="w-full bg-transparent text-sm outline-hidden"
							bind:value={query}
							placeholder={$i18n.t('Search Prompts')}
						/>
					</div>

					<div class="workspace-toolbar-actions">
						<HaloSelect
							bind:value={sortBy}
							options={[
								{ value: 'updated', label: $i18n.t('Recently Updated') },
								{ value: 'name', label: $i18n.t('Name') }
							]}
							className="w-fit max-w-full text-xs"
							on:change={() => {
								currentPage = 1;
								init();
							}}
						/>

						{#if $user?.role === 'admin'}
							<Dropdown bind:show={showMoreMenu} side="bottom" align="end">
								<Tooltip content={$i18n.t('More')}>
									<button
										type="button"
										class="workspace-icon-button px-3 py-2"
										aria-label={$i18n.t('More')}
										aria-haspopup="menu"
										aria-expanded={showMoreMenu}
									>
										<EllipsisHorizontal className="size-4" strokeWidth="2" />
									</button>
								</Tooltip>

								<div slot="content">
									<DropdownMenu.Content
										class="workspace-menu-content"
										sideOffset={8}
										side="bottom"
										align="end"
										transition={flyAndScale}
									>
										<DropdownMenu.Item
											class="workspace-menu-item"
											on:click={() => {
												showMoreMenu = false;
												promptsImportInputElement.click();
											}}
										>
											<ArrowUpTray className="size-4 shrink-0" strokeWidth="2" />
											<span>{$i18n.t('Import Prompts')}</span>
										</DropdownMenu.Item>
										{#if prompts.length}
											<DropdownMenu.Item
												class="workspace-menu-item"
												on:click={async () => {
													showMoreMenu = false;
													let blob = new Blob([JSON.stringify(prompts)], {
														type: 'application/json'
													});
													saveAs(blob, `prompts-export-${Date.now()}.json`);
												}}
											>
												<ArrowDownTray className="size-4 shrink-0" strokeWidth="2" />
												<span>{$i18n.t('Export Prompts')}</span>
											</DropdownMenu.Item>
										{/if}
									</DropdownMenu.Content>
								</div>
							</Dropdown>
						{/if}

						<a class="workspace-primary-button" href="/workspace/prompts/create">
							<Plus className="size-4" />
							<span>{$i18n.t('Create')}</span>
						</a>
					</div>
				</div>
			</div>

			{#if filteredItems.length > 0}
			<div class="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
		{#each filteredItems as prompt}
			<div
				class="glass-item flex space-x-4 cursor-pointer w-full px-4 py-3 transition"
			>
				<div class=" flex flex-1 space-x-4 cursor-pointer w-full">
					<a href={`/workspace/prompts/edit?id=${encodeURIComponent(prompt.id)}`}>
						<div class=" flex-1 flex items-center gap-2 self-center">
							<div
								class=" font-semibold line-clamp-1 capitalize"
								class:opacity-50={prompt.is_active === false}
							>
								{prompt.name}
							</div>
							{#if prompt.is_active === false}
								<span class="text-xs text-gray-400 dark:text-gray-500 shrink-0"
									>{$i18n.t('Disabled')}</span
								>
							{/if}
								<div class=" text-xs overflow-hidden text-ellipsis line-clamp-1">
									{prompt.command}
								</div>
						</div>

						{#if prompt.tags?.length}
							<div class="flex gap-1 mt-0.5 flex-wrap">
								{#each prompt.tags as tag}
									<span
										class="text-2xs px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400"
										>{tag}</span
									>
								{/each}
							</div>
						{/if}

						<div class=" text-xs px-0.5">
							<Tooltip
								content={prompt?.user?.email ?? $i18n.t('Deleted User')}
								className="flex shrink-0"
								placement="top-start"
							>
								<div class="shrink-0 text-gray-500">
									{$i18n.t('By {{name}}', {
										name: capitalizeFirstLetter(
											prompt?.user?.name ?? prompt?.user?.email ?? $i18n.t('Deleted User')
										)
									})}
								</div>
							</Tooltip>
						</div>
					</a>
				</div>
				<div class="flex flex-row gap-0.5 self-center">
					<Tooltip content={prompt.is_active !== false ? $i18n.t('Disable') : $i18n.t('Enable')}>
						<button
							class="self-center w-fit text-sm px-2 py-2 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
							type="button"
							on:click={() => toggleHandler(prompt)}
						>
							{#if prompt.is_active !== false}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="1.5"
									stroke="currentColor"
									class="w-4 h-4 text-green-500"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
									/>
								</svg>
							{:else}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="1.5"
									stroke="currentColor"
									class="w-4 h-4 text-gray-400"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"
									/>
								</svg>
							{/if}
						</button>
					</Tooltip>
					<a
						class="self-center w-fit text-sm px-2 py-2 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
						type="button"
						href={`/workspace/prompts/edit?id=${encodeURIComponent(prompt.id)}`}
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="w-4 h-4"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.863 4.487zm0 0L19.5 7.125"
							/>
						</svg>
					</a>

					<PromptMenu
						shareHandler={() => {
							shareHandler(prompt);
						}}
						cloneHandler={() => {
							cloneHandler(prompt);
						}}
						exportHandler={() => {
							exportHandler(prompt);
						}}
						deleteHandler={async () => {
							deletePromptItem = prompt;
							showDeleteConfirm = true;
						}}
						onClose={() => {}}
					>
						<button
							class="self-center w-fit text-sm p-1.5 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
							type="button"
						>
							<EllipsisHorizontal className="size-5" />
						</button>
					</PromptMenu>
				</div>
			</div>
		{/each}
			</div>
			{:else}
			<div class="workspace-empty-state">
				<p class="text-sm text-gray-500 dark:text-gray-400">
					{query
						? $i18n.t('No prompts found matching your search')
						: $i18n.t('No prompts yet. Create your first prompt to get started.')}
				</p>
			</div>
			{/if}

		{#if totalPages > 1}
			<div class="flex justify-center items-center gap-2">
				<button
					class="px-3 py-1 text-sm rounded-lg {currentPage === 1
						? 'text-gray-400 cursor-not-allowed'
						: 'hover:bg-gray-100 dark:hover:bg-gray-800'}"
					disabled={currentPage === 1}
					on:click={() => goToPage(currentPage - 1)}
				>
					{$i18n.t('Previous')}
				</button>

				<span class="text-sm text-gray-500 tabular-nums">
					{currentPage} / {totalPages}
				</span>

				<button
					class="px-3 py-1 text-sm rounded-lg {currentPage === totalPages
						? 'text-gray-400 cursor-not-allowed'
						: 'hover:bg-gray-100 dark:hover:bg-gray-800'}"
					disabled={currentPage === totalPages}
					on:click={() => goToPage(currentPage + 1)}
				>
					{$i18n.t('Next')}
				</button>
			</div>
		{/if}

		{#if $user?.role === 'admin'}
		<input
			id="prompts-import-input"
			bind:this={promptsImportInputElement}
			bind:files={importFiles}
			type="file"
			accept=".json"
			hidden
			on:change={() => {
				console.log(importFiles);

				const reader = new FileReader();
				reader.onload = async (event) => {
					const savedPrompts = JSON.parse(event.target.result);
					console.log(savedPrompts);

					for (const prompt of savedPrompts) {
						await createNewPrompt(localStorage.token, {
							command:
								prompt.command.charAt(0) === '/' ? prompt.command.slice(1) : prompt.command,
							name: prompt.name || prompt.title || '',
							content: prompt.content
						}).catch((error) => {
							toast.error(`${error}`);
							return null;
						});
					}

					currentPage = 1;
					await init();

					importFiles = [];
					promptsImportInputElement.value = '';
				};

				reader.readAsText(importFiles[0]);
			}}
		/>
		{/if}

		{#if $config?.features.enable_community_sharing}
			<section class="workspace-section space-y-3">
				<div class="text-base font-semibold text-gray-900 dark:text-gray-100">
					{$i18n.t('Made by Open WebUI Community')}
				</div>

				<a
					class="glass-item flex cursor-pointer items-center justify-between w-full px-4 py-3 transition"
					href="https://openwebui.com/#open-webui-community"
					target="_blank"
				>
					<div class=" self-center">
						<div class=" font-semibold line-clamp-1">{$i18n.t('Discover a prompt')}</div>
						<div class=" text-sm line-clamp-1 text-gray-500 dark:text-gray-400">
							{$i18n.t('Discover, download, and explore custom prompts')}
						</div>
					</div>

					<div>
						<div>
							<ChevronRight />
						</div>
					</div>
				</a>
			</section>
		{/if}
	</div>
{:else}
	<div class="w-full h-full flex justify-center items-center">
		<Spinner />
	</div>
{/if}
