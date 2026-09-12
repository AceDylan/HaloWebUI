<script>
	import DOMPurify from 'dompurify';
	import fileSaver from 'file-saver';
	import { getContext, createEventDispatcher, onMount, onDestroy, tick } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		deleteFolderById,
		updateFolderIsExpandedById,
		updateFolderNameById
	} from '$lib/apis/folders';
	import { getChatsByFolderId } from '$lib/apis/chats';
	import { chatId, selectedAssistantScene } from '$lib/stores';

	import FolderOpen from '$lib/components/icons/FolderOpen.svelte';
	import Folder from '$lib/components/icons/Folder.svelte';
	import EllipsisHorizontal from '$lib/components/icons/EllipsisHorizontal.svelte';
	import Collapsible from '../../common/Collapsible.svelte';
	import ChatItem from './ChatItem.svelte';
	import FolderMenu from './Folders/FolderMenu.svelte';
	import DeleteConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';

	const { saveAs } = fileSaver;
	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let open = false;
	export let folders;
	export let folderId;
	export let className = '';
	export let uiStyle = 'flat';
	export let shiftKey = false;
	export let folderOptions = [];

	let folderElement;
	let edit = false;
	let name = '';
	let showDeleteConfirm = false;
	let isExpandedUpdateTimeout;

	const getFolderChatCount = (sourceFolders, id) => {
		const target = sourceFolders[id] ?? {};
		const directCount = target.items?.chats?.length ?? 0;
		const childCount = (target.childrenIds ?? []).reduce((count, childId) => {
			return count + getFolderChatCount(sourceFolders, childId);
		}, 0);

		return directCount + childCount;
	};

	const folderContainsChat = (sourceFolders, id, activeChatId) => {
		if (!activeChatId) {
			return false;
		}

		const target = sourceFolders[id] ?? {};
		if ((target.items?.chats ?? []).some((chat) => chat.id === activeChatId)) {
			return true;
		}

		return (target.childrenIds ?? []).some((childId) =>
			folderContainsChat(sourceFolders, childId, activeChatId)
		);
	};

	$: folder = folders[folderId] ?? {};
	$: folderIcon = folder?.meta?.icon || '';
	$: chatCount = getFolderChatCount(folders, folderId);
	$: hasActiveChat = folderContainsChat(folders, folderId, $chatId);

	onMount(async () => {
		open = folder.is_expanded;

		if (folder?.new) {
			delete folders[folderId].new;
			await tick();
			editHandler();
		}
	});

	onDestroy(() => {
		clearTimeout(isExpandedUpdateTimeout);
	});

	const deleteHandler = async () => {
		const res = await deleteFolderById(localStorage.token, folderId).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Folder deleted successfully'));
			dispatch('update');
		}
	};

	const nameUpdateHandler = async () => {
		name = name.trim();
		if (name === '') {
			toast.error($i18n.t('Folder name cannot be empty'));
			return;
		}

		if (name === folder.name) {
			edit = false;
			return;
		}

		const currentName = folder.name;
		folders[folderId].name = name;

		const res = await updateFolderNameById(localStorage.token, folderId, name).catch((error) => {
			toast.error(`${error}`);
			folders[folderId].name = currentName;
			return null;
		});

		if (res) {
			toast.success($i18n.t('Folder name updated successfully'));
			dispatch('update');
		}
	};

	const isExpandedUpdateHandler = async () => {
		await updateFolderIsExpandedById(localStorage.token, folderId, open).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
	};

	const isExpandedUpdateDebounceHandler = () => {
		clearTimeout(isExpandedUpdateTimeout);
		isExpandedUpdateTimeout = setTimeout(() => {
			isExpandedUpdateHandler();
		}, 500);
	};

	$: if (folderId) {
		isExpandedUpdateDebounceHandler(open);
	}

	const editHandler = async () => {
		await tick();
		name = folder.name;
		edit = true;
		await tick();

		document.getElementById(`folder-${folderId}-input`)?.focus();
	};

	const exportHandler = async () => {
		const chats = await getChatsByFolderId(localStorage.token, folderId).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (!chats) {
			return;
		}

		const blob = new Blob([JSON.stringify(chats)], {
			type: 'application/json'
		});

		saveAs(blob, `folder-${folder.name}-export-${Date.now()}.json`);
	};

	const selectFolderChat = (assistantId) => {
		if ($selectedAssistantScene && $selectedAssistantScene.id !== assistantId) {
			selectedAssistantScene.set(null);
		}
	};
</script>

<DeleteConfirmDialog
	bind:show={showDeleteConfirm}
	title={$i18n.t('Delete folder?')}
	on:confirm={() => {
		deleteHandler();
	}}
>
	<div class=" text-sm text-gray-700 dark:text-gray-300 flex-1 line-clamp-3">
		{@html DOMPurify.sanitize(
			$i18n.t('This will delete <strong>{{NAME}}</strong> and <strong>all its contents</strong>.', {
				NAME: folder.name
			})
		)}
	</div>
</DeleteConfirmDialog>

<div bind:this={folderElement} class="relative {className}">
	<Collapsible
		bind:open
		className="w-full"
		buttonClassName="w-full"
		hide={(folder?.childrenIds ?? []).length === 0 && (folder.items?.chats ?? []).length === 0}
		on:change={() => {
			dispatch('change');
		}}
	>
		<div class="w-full group">
			<!-- svelte-ignore a11y-no-static-element-interactions -->
			<div
				id="folder-{folderId}-button"
				class="relative flex min-h-[34px] w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition {hasActiveChat
					? 'bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-fg)]'
					: 'text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-850'}"
				on:dblclick={() => {
					editHandler();
				}}
			>
				<div
					class="flex size-6 shrink-0 items-center justify-center rounded-md {hasActiveChat
						? 'text-[var(--sidebar-active-fg)]'
						: 'text-gray-500 dark:text-gray-400'}"
					aria-hidden="true"
				>
					{#if folderIcon}
						<span class="text-sm leading-none">{folderIcon}</span>
					{:else if open}
						<FolderOpen className="size-4" strokeWidth="2" />
					{:else}
						<Folder className="size-4" strokeWidth="2" />
					{/if}
				</div>

				<div class="min-w-0 flex-1 translate-y-[0.5px] justify-start text-start">
					{#if edit}
						<input
							id="folder-{folderId}-input"
							type="text"
							bind:value={name}
							on:focus={(e) => {
								e.target.select();
							}}
							on:blur={() => {
								nameUpdateHandler();
								edit = false;
							}}
							on:click={(e) => {
								e.stopPropagation();
							}}
							on:mousedown={(e) => {
								e.stopPropagation();
							}}
							on:keydown={(e) => {
								if (e.key === 'Enter') {
									nameUpdateHandler();
									edit = false;
								}
							}}
							class="h-full w-full bg-transparent text-[13px] font-semibold text-gray-800 outline-hidden dark:text-gray-100"
						/>
					{:else}
						<div class="line-clamp-1 text-[13px] font-medium leading-5">
							{folder.name}
						</div>
					{/if}
				</div>

				{#if chatCount > 0}
					<span
						class="flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full px-1.5 text-2xs font-medium tabular-nums {hasActiveChat
							? 'bg-white/60 text-[var(--sidebar-active-fg)] dark:bg-black/25'
							: 'bg-gray-200/70 text-gray-500 dark:bg-gray-800 dark:text-gray-400'}"
					>
						{chatCount}
					</span>
				{/if}

				<!-- svelte-ignore a11y-no-static-element-interactions -->
				<div
					class="z-10 flex shrink-0 items-center self-center rounded-md p-0.5 text-gray-400 opacity-70 transition hover:bg-gray-100 hover:text-gray-700 hover:opacity-100 dark:text-gray-500 dark:hover:bg-gray-800 dark:hover:text-gray-200"
					on:pointerup={(e) => {
						e.stopPropagation();
					}}
				>
					<FolderMenu
						on:rename={() => {
							setTimeout(() => {
								editHandler();
							}, 200);
						}}
						on:delete={() => {
							showDeleteConfirm = true;
						}}
						on:export={() => {
							exportHandler();
						}}
					>
						<button
							class="flex size-7 items-center justify-center rounded-md touch-auto"
							aria-label={$i18n.t('Folder options')}
							on:click={() => {}}
						>
							<EllipsisHorizontal className="size-4" strokeWidth="2.5" />
						</button>
					</FolderMenu>
				</div>
			</div>
		</div>

		<div slot="content" class="w-full">
			{#if (folder?.childrenIds ?? []).length > 0 || (folder.items?.chats ?? []).length > 0}
				<div
					class="ml-4 mt-0.5 mb-1 flex flex-col gap-0.5 overflow-y-auto border-s border-gray-200/80 py-0.5 pl-2 scrollbar-hidden dark:border-gray-800/90"
				>
					{#if folder?.childrenIds}
						{@const children = folder.childrenIds
							.map((id) => folders[id])
							.filter(Boolean)
							.sort((a, b) =>
								a.name.localeCompare(b.name, undefined, {
									numeric: true,
									sensitivity: 'base'
								})
							)}

						{#each children as childFolder (`${folderId}-${childFolder.id}`)}
							<svelte:self
								{folders}
								{uiStyle}
								{shiftKey}
								{folderOptions}
								folderId={childFolder.id}
								on:update={(e) => {
									dispatch('update', e.detail);
								}}
								on:change={(e) => {
									dispatch('change', e.detail);
								}}
							/>
						{/each}
					{/if}

					{#if folder.items?.chats}
						{#each folder.items.chats as chat (chat.id)}
							<ChatItem
								{uiStyle}
								variant="folder"
								id={chat.id}
								title={chat.title}
								assistantId={chat.assistant_id ?? null}
								folderId={folderId}
								{folderOptions}
								{shiftKey}
								selected={chat.id === $chatId}
								on:select={() => {
									selectFolderChat(chat.assistant_id ?? null);
								}}
								on:change={(e) => {
									dispatch('change', e.detail);
								}}
							/>
						{/each}
					{/if}
				</div>
			{/if}
		</div>
	</Collapsible>
</div>
