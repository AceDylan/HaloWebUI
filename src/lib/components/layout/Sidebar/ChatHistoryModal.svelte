<script lang="ts">
	import dayjs from 'dayjs';
	import { getContext } from 'svelte';
	import localizedFormat from 'dayjs/plugin/localizedFormat';

	dayjs.extend(localizedFormat);

	import { goto } from '$app/navigation';
	import { CHAT_KIND_LABEL, CHAT_KIND_TITLE, chatHref } from '$lib/utils/chat-kind';

	import { getChatList, getChatListBySearchText } from '$lib/apis/chats';
	import { folders as folderStore, pendingMessageReveal } from '$lib/stores';
	import { snippetParts } from '$lib/utils/search-snippet';

	import Modal from '$lib/components/common/Modal.svelte';
	import Loader from '$lib/components/common/Loader.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n = getContext('i18n');

	export let show = false;

	let chats: Array<Record<string, any>> | null = null;
	let page = 1;
	let searchValue = '';
	let allChatsLoaded = false;
	let chatListLoading = false;
	let searchDebounceTimeout: ReturnType<typeof setTimeout> | null = null;

	// History means everything: chats inside folders are listed too, with the
	// folder name next to them.
	const fetchChatPage = async (targetPage: number) => {
		const query = searchValue.trim();
		return query
			? await getChatListBySearchText(localStorage.token, query, targetPage).catch(() => [])
			: await getChatList(localStorage.token, targetPage, { includeFolders: true }).catch(() => []);
	};

	const folderNameOf = (folderId: string | null | undefined): string | null => {
		if (!folderId) return null;
		return ($folderStore ?? []).find((folder) => folder.id === folderId)?.name ?? null;
	};

	const initList = async () => {
		chatListLoading = true;
		page = 1;
		allChatsLoaded = false;

		const newChats = await fetchChatPage(page);
		allChatsLoaded = newChats.length === 0;
		chats = newChats;
		chatListLoading = false;
	};

	const loadMoreChats = async () => {
		if (chatListLoading || allChatsLoaded) {
			return;
		}
		chatListLoading = true;
		page += 1;

		const newChats = await fetchChatPage(page);
		allChatsLoaded = newChats.length === 0;
		chats = [...(chats ?? []), ...newChats];
		chatListLoading = false;
	};

	const searchHandler = () => {
		if (searchDebounceTimeout) {
			clearTimeout(searchDebounceTimeout);
		}
		chats = null;
		searchDebounceTimeout = setTimeout(() => {
			void initList();
		}, 500);
	};

	const openChat = async (chat: Record<string, any>) => {
		show = false;
		// A search hit opens at the message the words were found in.
		pendingMessageReveal.set(
			searchValue.trim() && chat.message_id && chat.kind !== 'discuss'
				? { chatId: chat.id, messageId: chat.message_id }
				: null
		);
		await goto(chatHref(chat.id, chat.kind));
	};

	$: if (show) {
		searchValue = '';
		chats = null;
		void initList();
	}
</script>

<Modal size="lg" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-5 pt-4 pb-1">
			<div class=" text-lg font-medium self-center">{$i18n.t('Chat History')}</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-5 h-5"
				>
					<path
						fill-rule="evenodd"
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
						clip-rule="evenodd"
					/>
				</svg>
			</button>
		</div>

		<div class="flex flex-col w-full px-5 pb-4 dark:text-gray-200">
			<div class=" flex w-full mt-2 space-x-2">
				<div class="flex flex-1">
					<div class=" self-center ml-1 mr-3">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 20 20"
							fill="currentColor"
							class="w-4 h-4"
						>
							<path
								fill-rule="evenodd"
								d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z"
								clip-rule="evenodd"
							/>
						</svg>
					</div>
					<input
						class=" w-full text-sm pr-4 py-1 rounded-r-xl outline-hidden bg-transparent"
						bind:value={searchValue}
						on:input={searchHandler}
						placeholder={$i18n.t('Search Chats')}
					/>
				</div>
			</div>
			<hr class="border-gray-100 dark:border-gray-850 my-2" />

			<div class="max-h-[22rem] overflow-y-auto">
				{#if chats === null}
					<div class="w-full flex justify-center py-4 text-xs animate-pulse items-center gap-2">
						<Spinner className=" size-4" />
						<div class=" ">Loading...</div>
					</div>
				{:else if chats.length === 0}
					<div class="text-left text-sm w-full my-4 text-gray-500 dark:text-gray-400">
						{$i18n.t('No results found')}
					</div>
				{:else}
					<div class="flex flex-col gap-0.5 pr-1 pb-2">
						{#each chats as chat}
							<a
								class="flex items-center justify-between gap-3 rounded-xl px-3 py-2 text-sm hover:bg-gray-100 dark:hover:bg-gray-850 transition"
								href={chatHref(chat.id, chat.kind)}
								draggable="false"
								on:click|preventDefault={() => {
									void openChat(chat);
								}}
							>
								<div class="min-w-0 flex-1 text-left">
									<div class="line-clamp-1 text-gray-800 dark:text-gray-100">
										{chat.title}
									</div>
									{#if searchValue.trim() && chat.snippet}
										<div
											class="mt-0.5 line-clamp-2 break-words text-xs leading-[1.4] text-gray-500 dark:text-gray-400"
											data-halo-search-snippet
										>
											{#each snippetParts(chat.snippet, searchValue) as piece}{#if piece.match}<mark
														class="rounded-sm bg-amber-200/70 px-px text-gray-900 dark:bg-amber-400/30 dark:text-amber-100"
														>{piece.text}</mark
													>{:else}{piece.text}{/if}{/each}
										</div>
									{/if}
								</div>
								{#if chat.kind && CHAT_KIND_LABEL[chat.kind]}
									<span
										class="shrink-0 rounded px-1 py-0.5 text-2xs leading-none text-gray-500 ring-1 ring-inset ring-gray-200 dark:text-gray-400 dark:ring-gray-700"
										title={CHAT_KIND_TITLE[chat.kind]}
										data-halo-chat-kind={chat.kind}
									>
										{CHAT_KIND_LABEL[chat.kind]}
									</span>
								{/if}
								{#if folderNameOf(chat.folder_id)}
									<span
										class="max-w-[8rem] shrink-0 truncate rounded-md bg-gray-200/70 px-1.5 py-0.5 text-[10px] leading-none text-gray-500 dark:bg-gray-800/80 dark:text-gray-400"
										title={folderNameOf(chat.folder_id)}
									>
										{folderNameOf(chat.folder_id)}
									</span>
								{/if}
								<div class="shrink-0 text-xs text-gray-600 dark:text-gray-400 whitespace-nowrap">
									{dayjs(chat.updated_at * 1000).format('LL')}
								</div>
							</a>
						{/each}

						{#if !allChatsLoaded}
							<Loader
								on:visible={() => {
									if (!chatListLoading) {
										void loadMoreChats();
									}
								}}
							>
								<div
									class="w-full flex justify-center py-1 text-xs animate-pulse items-center gap-2"
								>
									<Spinner className=" size-4" />
									<div class=" ">Loading...</div>
								</div>
							</Loader>
						{/if}
					</div>
				{/if}
			</div>
		</div>
	</div>
</Modal>
