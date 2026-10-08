<script lang="ts">
	import dayjs from 'dayjs';
	import { getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import { getBookmarks, removeBookmark, type MessageBookmark } from '$lib/apis/bookmarks';
	import { chatBookmarkIds, mobile, pendingMessageReveal, showSidebar } from '$lib/stores';
	import { snippetParts } from '$lib/utils/search-snippet';
	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	/** 收藏: the replies a person kept, newest first. Opening one goes to its chat at that reply. */
	export let show = false;

	const i18n = getContext('i18n');

	let bookmarks: MessageBookmark[] | null = null;
	let error = '';
	let query = '';
	let removing: string | null = null;

	const load = async () => {
		bookmarks = null;
		error = '';
		try {
			bookmarks = await getBookmarks(localStorage.token);
		} catch (e) {
			bookmarks = [];
			error = typeof e === 'string' && e ? e : '收藏没有加载出来';
		}
	};

	$: if (show) {
		query = '';
		void load();
	}

	$: needle = query.trim().toLowerCase();
	$: shown = (bookmarks ?? []).filter(
		(bookmark) =>
			!needle ||
			(bookmark.excerpt ?? '').toLowerCase().includes(needle) ||
			bookmark.chat_title.toLowerCase().includes(needle)
	);

	const open = async (bookmark: MessageBookmark) => {
		show = false;
		pendingMessageReveal.set({ chatId: bookmark.chat_id, messageId: bookmark.message_id });
		if ($mobile) showSidebar.set(false);
		await goto(`/c/${bookmark.chat_id}`);
	};

	const remove = async (bookmark: MessageBookmark) => {
		if (removing) return;
		removing = bookmark.id;
		try {
			await removeBookmark(localStorage.token, bookmark.id);
			bookmarks = (bookmarks ?? []).filter((item) => item.id !== bookmark.id);
			chatBookmarkIds.update((state) => {
				if (state.chatId !== bookmark.chat_id) return state;
				const ids = new Set(state.ids);
				ids.delete(bookmark.message_id);
				return { chatId: state.chatId, ids };
			});
		} catch (e) {
			toast.error(typeof e === 'string' && e ? e : '没有删掉，请稍后再试');
		} finally {
			removing = null;
		}
	};
</script>

<Modal size="lg" bind:show>
	<div>
		<div class="flex justify-between dark:text-gray-300 px-5 pt-4 pb-1">
			<div class="text-lg font-medium self-center">收藏</div>
			<button
				class="self-center"
				aria-label={$i18n.t('Close')}
				on:click={() => {
					show = false;
				}}
			>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
					<path
						fill-rule="evenodd"
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
						clip-rule="evenodd"
					/>
				</svg>
			</button>
		</div>

		<div class="flex flex-col w-full px-5 pb-4 dark:text-gray-200">
			<div class="flex w-full mt-2 items-center">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="ml-1 mr-3 w-4 h-4 shrink-0 text-gray-500"
					aria-hidden="true"
				>
					<path
						fill-rule="evenodd"
						d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z"
						clip-rule="evenodd"
					/>
				</svg>
				<input
					class="w-full text-sm pr-4 py-1 outline-hidden bg-transparent"
					bind:value={query}
					placeholder="搜索收藏"
				/>
			</div>
			<hr class="border-gray-100 dark:border-gray-850 my-2" />

			<div class="max-h-[60vh] overflow-y-auto scrollbar-hidden">
				{#if bookmarks === null}
					<div class="flex justify-center py-8"><Spinner className="size-5" /></div>
				{:else if error}
					<div class="py-8 text-center text-sm text-gray-500">{error}</div>
				{:else if bookmarks.length === 0}
					<div class="py-8 text-center text-sm leading-6 text-gray-500 dark:text-gray-400">
						还没有收藏。<br />在回复下方的「更多」菜单里点「收藏」，好的回答就会留在这里。
					</div>
				{:else if shown.length === 0}
					<div class="py-8 text-center text-sm text-gray-500">{$i18n.t('No results found')}</div>
				{:else}
					<div class="flex flex-col gap-0.5 pb-1">
						{#each shown as bookmark (bookmark.id)}
							<div
								class="group flex items-start gap-2 rounded-xl px-3 py-2 transition hover:bg-gray-50 dark:hover:bg-gray-850"
								data-halo-bookmark={bookmark.id}
							>
								<button
									type="button"
									class="min-w-0 flex-1 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/50 rounded-lg"
									on:click={() => open(bookmark)}
								>
									<div class="line-clamp-3 break-words text-sm leading-[1.45] text-gray-800 dark:text-gray-100">
										{#if needle}
											{#each snippetParts(bookmark.excerpt ?? '', query) as piece}{#if piece.match}<mark
														class="rounded-sm bg-amber-200/70 px-px text-gray-900 dark:bg-amber-400/30 dark:text-amber-100"
														>{piece.text}</mark
													>{:else}{piece.text}{/if}{/each}
										{:else}
											{bookmark.excerpt || '（没有文字内容）'}
										{/if}
									</div>
									<div class="mt-1 flex min-w-0 items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
										<span class="truncate">{bookmark.chat_title}</span>
										{#if bookmark.chat_archived}
											<span
												class="shrink-0 rounded px-1 py-0.5 text-2xs leading-none ring-1 ring-inset ring-gray-200 dark:ring-gray-700"
												>{$i18n.t('Archived')}</span
											>
										{/if}
										<span class="shrink-0">· {dayjs(bookmark.created_at * 1000).format('YYYY-MM-DD')}</span>
									</div>
								</button>
								<button
									type="button"
									class="shrink-0 rounded-lg px-2 py-1 text-xs text-gray-400 opacity-100 transition hover:bg-gray-100 hover:text-gray-700 disabled:opacity-40 sm:opacity-0 sm:group-hover:opacity-100 sm:focus:opacity-100 dark:hover:bg-gray-800 dark:hover:text-gray-200"
									disabled={removing === bookmark.id}
									aria-label="取消收藏"
									on:click={() => remove(bookmark)}>取消收藏</button
								>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	</div>
</Modal>
