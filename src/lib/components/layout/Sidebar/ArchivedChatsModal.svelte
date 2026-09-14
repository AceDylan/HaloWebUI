<script lang="ts">
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import { getContext, createEventDispatcher, onDestroy } from 'svelte';
	import localizedFormat from 'dayjs/plugin/localizedFormat';

	dayjs.extend(localizedFormat);

	const dispatch = createEventDispatcher();

	import {
		archiveChatById,
		deleteChatById,
		getAllArchivedChats,
		getArchivedChatCount,
		getArchivedChatList
	} from '$lib/apis/chats';

	import Modal from '$lib/components/common/Modal.svelte';
	import Pagination from '$lib/components/common/Pagination.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import UnarchiveAllConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	const i18n = getContext('i18n');

	export let show = false;

	// The archived list is fetched a page at a time: an account with thousands of
	// archived chats used to send every one of them (titles and messages) down the
	// wire the moment this modal opened.
	const PER_PAGE = 20;
	const SEARCH_DEBOUNCE_MS = 300;

	let chats = [];
	let total = 0;
	let page = 1;

	let searchValue = '';
	let searchQuery = ''; // the debounced value the server filters on
	let searchTimeout = null;

	let loading = false;
	let loadError = '';
	let unarchivingAll = false;

	// Only the newest request may write to the list; a slow page that lands after
	// the person has moved on is dropped.
	let requestId = 0;
	let loadedKey = '';

	let showUnarchiveAllConfirmDialog = false;

	const loadPage = async () => {
		const id = ++requestId;
		loading = true;
		loadError = '';

		try {
			const [items, count] = await Promise.all([
				getArchivedChatList(localStorage.token, {
					page,
					limit: PER_PAGE,
					query: searchQuery
				}),
				getArchivedChatCount(localStorage.token, searchQuery)
			]);

			if (id !== requestId) {
				return;
			}

			// Unarchiving or deleting can empty the page we are standing on; fall
			// back to the last page that still has rows instead of showing nothing.
			const clamped = Math.max(1, Math.ceil(count / PER_PAGE));
			if (page > clamped) {
				page = clamped;
				loadedKey = `${page}:${searchQuery}`;
				await loadPage();
				return;
			}

			chats = items;
			total = count;
		} catch (error) {
			if (id !== requestId) {
				return;
			}

			chats = [];
			total = 0;
			loadError = `${error}`;
		} finally {
			if (id === requestId) {
				loading = false;
			}
		}
	};

	const reloadCurrentPage = async () => {
		loadedKey = `${page}:${searchQuery}`;
		await loadPage();
	};

	const searchInputHandler = () => {
		clearTimeout(searchTimeout);
		searchTimeout = setTimeout(() => {
			const next = searchValue.trim();
			if (next === searchQuery) {
				return;
			}

			page = 1;
			searchQuery = next;
		}, SEARCH_DEBOUNCE_MS);
	};

	const unarchiveChatHandler = async (chatId) => {
		try {
			await archiveChatById(localStorage.token, chatId);
		} catch (error) {
			toast.error(`${error}`);
		}

		await reloadCurrentPage();
		dispatch('change');
	};

	const deleteChatHandler = async (chatId) => {
		try {
			await deleteChatById(localStorage.token, chatId);
		} catch (error) {
			toast.error(`${error}`);
		}

		await reloadCurrentPage();
	};

	const exportChatsHandler = async () => {
		const chats = await getAllArchivedChats(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (!chats) {
			return;
		}

		let blob = new Blob([JSON.stringify(chats)], {
			type: 'application/json'
		});
		saveAs(blob, `${$i18n.t('archived-chat-export')}-${Date.now()}.json`);
	};

	const unarchiveAllHandler = async () => {
		// Walk the list a page at a time instead of holding all of it: each chat
		// leaves the archive as it is unarchived, so the first page keeps refilling
		// until nothing is left. Ids already tried guard against a chat that
		// refuses to move, which would otherwise loop forever.
		const attempted = new Set();
		unarchivingAll = true;

		try {
			for (;;) {
				const batch = await getArchivedChatList(localStorage.token, {
					page: 1,
					limit: PER_PAGE
				});
				const pending = batch.filter((chat) => !attempted.has(chat.id));

				if (pending.length === 0) {
					break;
				}

				for (const chat of pending) {
					attempted.add(chat.id);
					await archiveChatById(localStorage.token, chat.id);
				}
			}
		} catch (error) {
			toast.error(`${error}`);
		}

		unarchivingAll = false;
		page = 1;
		await reloadCurrentPage();
		dispatch('change');
	};

	$: if (show) {
		const key = `${page}:${searchQuery}`;
		if (key !== loadedKey) {
			loadedKey = key;
			loadPage();
		}
	} else if (loadedKey !== '') {
		// Closing resets the view so the next open starts at the newest page.
		loadedKey = '';
		page = 1;
		searchValue = '';
		searchQuery = '';
		chats = [];
		total = 0;
		loadError = '';
		requestId += 1;
		loading = false;
	}

	onDestroy(() => {
		clearTimeout(searchTimeout);
	});
</script>

<UnarchiveAllConfirmDialog
	bind:show={showUnarchiveAllConfirmDialog}
	message={$i18n.t('Are you sure you want to unarchive all archived chats?')}
	confirmLabel={$i18n.t('Unarchive All')}
	on:confirm={() => {
		unarchiveAllHandler();
	}}
/>

<Modal size="lg" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-5 pt-4 pb-1">
			<div class=" text-lg font-medium self-center">
				{$i18n.t('Archived Chats')}
				{#if total > 0}
					<span class="text-sm font-normal text-gray-500 dark:text-gray-400">{total}</span>
				{/if}
			</div>
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
						on:input={searchInputHandler}
						placeholder={$i18n.t('Search Chats')}
					/>
				</div>
			</div>
			<hr class="border-gray-100 dark:border-gray-850 my-2" />
			<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				<div class="w-full">
					<div class="text-left text-sm w-full mb-3 max-h-[22rem] overflow-y-auto">
						{#if loading && chats.length === 0}
							<div class="w-full py-8">
								<Spinner className="size-5" />
							</div>
						{:else if loadError}
							<div
								class="flex flex-col items-start gap-2 w-full py-6 text-gray-600 dark:text-gray-400"
							>
								<div class="line-clamp-3">{loadError}</div>
								<button
									class="px-3.5 py-1.5 font-medium hover:bg-black/5 dark:hover:bg-white/5 outline outline-1 outline-gray-300 dark:outline-gray-800 rounded-3xl"
									on:click={() => {
										reloadCurrentPage();
									}}
								>
									{$i18n.t('Retry')}
								</button>
							</div>
						{:else if chats.length === 0}
							<div class="text-left text-sm w-full py-6">
								{searchQuery
									? $i18n.t('No results found')
									: $i18n.t('You have no archived conversations.')}
							</div>
						{:else}
							<div class="relative overflow-x-auto {loading ? 'opacity-50' : ''}">
								<table class="w-full text-sm text-left text-gray-600 dark:text-gray-400 table-auto">
									<thead
										class="text-xs text-gray-700 uppercase bg-transparent dark:text-gray-200 border-b-2 border-gray-50 dark:border-gray-850"
									>
										<tr>
											<th scope="col" class="px-3 py-2"> {$i18n.t('Name')} </th>
											<th scope="col" class="px-3 py-2 hidden md:flex">
												{$i18n.t('Created At')}
											</th>
											<th scope="col" class="px-3 py-2 text-right" />
										</tr>
									</thead>
									<tbody>
										{#each chats as chat, idx}
											<tr
												class="bg-transparent {idx !== chats.length - 1 &&
													'border-b'} dark:bg-gray-900 border-gray-50 dark:border-gray-850 text-xs"
											>
												<td class="px-3 py-1 w-2/3">
													<a href="/c/{chat.id}" target="_blank">
														<div class=" underline line-clamp-1">
															{chat.title}
														</div>
													</a>
												</td>

												<td class=" px-3 py-1 hidden md:flex h-[2.5rem]">
													<div class="my-auto">
														{dayjs(chat.created_at * 1000).format('LLL')}
													</div>
												</td>

												<td class="px-3 py-1 text-right">
													<div class="flex justify-end w-full">
														<Tooltip content={$i18n.t('Unarchive Chat')}>
															<button
																class="self-center w-fit text-sm px-2 py-2 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
																on:click={async () => {
																	unarchiveChatHandler(chat.id);
																}}
															>
																<svg
																	xmlns="http://www.w3.org/2000/svg"
																	fill="none"
																	viewBox="0 0 24 24"
																	stroke-width="1.5"
																	stroke="currentColor"
																	class="size-4"
																>
																	<path
																		stroke-linecap="round"
																		stroke-linejoin="round"
																		d="M9 8.25H7.5a2.25 2.25 0 0 0-2.25 2.25v9a2.25 2.25 0 0 0 2.25 2.25h9a2.25 2.25 0 0 0 2.25-2.25v-9a2.25 2.25 0 0 0-2.25-2.25H15m0-3-3-3m0 0-3 3m3-3V15"
																	/>
																</svg>
															</button>
														</Tooltip>

														<Tooltip content={$i18n.t('Delete Chat')}>
															<button
																class="self-center w-fit text-sm px-2 py-2 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
																on:click={async () => {
																	deleteChatHandler(chat.id);
																}}
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
																		d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
																	/>
																</svg>
															</button>
														</Tooltip>
													</div>
												</td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						{/if}
					</div>

					{#if total > PER_PAGE}
						<Pagination bind:page count={total} perPage={PER_PAGE} />
					{/if}

					{#if total > 0 || searchQuery}
						<div class="flex flex-wrap text-sm font-medium gap-1.5 mt-2 m-1 justify-end w-full">
							<button
								class=" px-3.5 py-1.5 font-medium hover:bg-black/5 dark:hover:bg-white/5 outline outline-1 outline-gray-300 dark:outline-gray-800 rounded-3xl disabled:opacity-50 disabled:cursor-not-allowed"
								disabled={unarchivingAll}
								on:click={() => {
									showUnarchiveAllConfirmDialog = true;
								}}
							>
								{$i18n.t('Unarchive All Archived Chats')}
							</button>

							<button
								class="px-3.5 py-1.5 font-medium hover:bg-black/5 dark:hover:bg-white/5 outline outline-1 outline-gray-300 dark:outline-gray-800 rounded-3xl disabled:opacity-50 disabled:cursor-not-allowed"
								disabled={unarchivingAll}
								on:click={() => {
									exportChatsHandler();
								}}
							>
								{$i18n.t('Export All Archived Chats')}
							</button>
						</div>
					{/if}
				</div>
			</div>
		</div>
	</div>
</Modal>
