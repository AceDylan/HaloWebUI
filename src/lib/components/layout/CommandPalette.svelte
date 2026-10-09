<script lang="ts">
	import { tick, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';

	import { getChatListBySearchText } from '$lib/apis/chats';
	import {
		chats,
		config,
		mobile,
		models,
		pendingMessageReveal,
		showArchivedChats,
		showBookmarks,
		showCommandPalette,
		showSidebar,
		user
	} from '$lib/stores';
	import { CHAT_KIND_LABEL } from '$lib/utils/chat-kind';
	import { paletteItems, type PaletteChat, type PaletteItem } from '$lib/utils/command-palette';
	import { libraryDestinations, modeDestinations } from '$lib/utils/destinations';
	import { snippetParts } from '$lib/utils/search-snippet';
	import SidebarModeIcon from './Sidebar/SidebarModeIcon.svelte';

	/**
	 * ⌘K / Ctrl+K: one box to go anywhere — a mode or a library page, any chat (full-text, archived
	 * ones too, opening at the message the words are in), or a new chat on some model. Arrow keys
	 * and Enter, or tap; Esc closes.
	 */

	let query = '';
	let index = 0;
	let input: HTMLInputElement | null = null;
	let hits: PaletteChat[] | null = null;
	let searchTimer: ReturnType<typeof setTimeout> | null = null;
	let searchSeq = 0;
	let listEl: HTMLElement | null = null;

	const close = () => showCommandPalette.set(false);

	$: if ($showCommandPalette) void opened();
	const opened = async () => {
		query = '';
		hits = null;
		index = 0;
		await tick();
		input?.focus();
	};

	const cancelSearch = () => {
		searchSeq += 1;
		if (searchTimer) clearTimeout(searchTimer);
		searchTimer = null;
	};
	onDestroy(cancelSearch);
	const search = (text: string, visible: boolean) => {
		cancelSearch();
		hits = null;
		const q = text.trim();
		if (!visible || !q) return;
		const seq = searchSeq;
		searchTimer = setTimeout(async () => {
			searchTimer = null;
			const found = await getChatListBySearchText(localStorage.token, q, 1).catch(() => null);
			if (seq === searchSeq && Array.isArray(found)) hits = found;
		}, 200);
	};
	$: search(query, $showCommandPalette);

	$: items = paletteItems({
		query,
		destinations: [...modeDestinations($config, $user), ...libraryDestinations($user)],
		admin: $user?.role === 'admin',
		recent: Array.isArray($chats) ? ($chats as PaletteChat[]) : [],
		hits,
		models: ($models ?? []) as any[]
	});
	$: if (index >= items.length) index = Math.max(0, items.length - 1);

	const choose = async (item: PaletteItem | undefined) => {
		if (!item) return;
		close();
		if ($mobile) showSidebar.set(false);
		if (item.open === 'bookmarks') return showBookmarks.set(true);
		if (item.open === 'archived') return showArchivedChats.set(true);
		if (item.messageId) {
			pendingMessageReveal.set({ chatId: item.id.slice('chat:'.length), messageId: item.messageId });
		}
		if (item.href) await goto(item.href);
	};

	const onKeydown = async (event: KeyboardEvent) => {
		if (event.key === 'Escape') {
			event.preventDefault();
			close();
		} else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
			event.preventDefault();
			if (!items.length) return;
			index = (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
			await tick();
			listEl?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
		} else if (event.key === 'Enter' && !event.isComposing) {
			event.preventDefault();
			await choose(items[index]);
		}
	};

	const iconOf = (item: PaletteItem) => {
		if (item.section === '对话') return item.kind === 'discuss' || item.kind === 'discuss_dispatch' ? 'discuss' : 'chat';
		if (item.section === '用模型开新对话') return 'chat';
		const key = item.id.slice('go:'.length);
		return key === 'new' ? 'chat' : key;
	};
</script>

{#if $showCommandPalette}
	<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
	<div
		class="fixed inset-0 z-[9999] flex items-start justify-center bg-black/30 px-3 pt-[10vh] backdrop-blur-[2px] max-sm:pt-3"
		on:click|self={close}
		data-command-palette
	>
		<div
			class="flex max-h-[min(70vh,560px)] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-gray-200/70 bg-white/95 shadow-2xl dark:border-gray-800 dark:bg-gray-900/95"
			role="dialog"
			aria-modal="true"
			aria-label="命令面板"
		>
			<div class="flex items-center gap-2 border-b border-gray-100 px-4 py-3 dark:border-gray-800">
				<svg class="size-4 shrink-0 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"
					><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg
				>
				<input
					bind:this={input}
					bind:value={query}
					on:keydown={onKeydown}
					class="min-w-0 flex-1 bg-transparent text-[15px] text-gray-900 outline-hidden placeholder:text-gray-400 dark:text-gray-100"
					placeholder="搜对话、去哪个页面、用哪个模型开新对话…"
					role="combobox"
					aria-expanded="true"
					aria-controls="command-palette-list"
					aria-activedescendant={items[index] ? `cp-${index}` : undefined}
					autocomplete="off"
					spellcheck="false"
					data-command-palette-input
				/>
				<kbd class="hidden rounded border border-gray-200 px-1.5 text-2xs text-gray-400 sm:inline dark:border-gray-700">Esc</kbd>
			</div>
			<ul
				id="command-palette-list"
				class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 py-2"
				role="listbox"
				bind:this={listEl}
			>
				{#each items as item, i (item.id)}
					{#if i === 0 || items[i - 1].section !== item.section}
						<li class="px-2 pt-2 pb-1 text-2xs font-medium text-gray-400" role="presentation">
							{item.section}{item.section === '对话' && query.trim() && hits === null ? ' · 搜索中…' : ''}
						</li>
					{/if}
					<!-- svelte-ignore a11y-click-events-have-key-events -->
					<li
						id="cp-{i}"
						role="option"
						aria-selected={i === index}
						class="flex cursor-pointer items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm max-sm:py-2.5 {i ===
						index
							? 'bg-gray-100 dark:bg-gray-800'
							: ''}"
						on:mousemove={() => (index = i)}
						on:click={() => choose(item)}
						data-command-palette-item={item.id}
					>
						<span class="shrink-0 text-gray-400"><SidebarModeIcon mode={iconOf(item)} className="size-4" /></span>
						<span class="min-w-0 flex-1">
							<span class="block truncate text-gray-900 dark:text-gray-100">{item.label}</span>
							{#if item.hint}
								<span class="block truncate text-xs text-gray-500 dark:text-gray-400">
									{#if item.section === '对话'}
										{#each snippetParts(item.hint, query) as piece}{#if piece.match}<mark
													class="rounded-sm bg-amber-200/70 px-px text-gray-900 dark:bg-amber-400/30 dark:text-amber-100"
													>{piece.text}</mark
												>{:else}{piece.text}{/if}{/each}
									{:else}
										{item.hint}
									{/if}
								</span>
							{/if}
						</span>
						{#if item.kind && CHAT_KIND_LABEL[item.kind]}
							<span class="shrink-0 rounded px-1 py-0.5 text-2xs leading-none text-gray-500 ring-1 ring-inset ring-gray-200 dark:text-gray-400 dark:ring-gray-700">
								{CHAT_KIND_LABEL[item.kind]}
							</span>
						{/if}
						{#if item.archived}
							<span class="shrink-0 text-2xs text-gray-400">已归档</span>
						{/if}
					</li>
				{:else}
					<li class="px-3 py-6 text-center text-sm text-gray-500 dark:text-gray-400" role="presentation">
						{hits === null && query.trim() ? '搜索中…' : '没有找到'}
					</li>
				{/each}
			</ul>
			<div class="hidden items-center gap-3 border-t border-gray-100 px-4 py-2 text-2xs text-gray-400 sm:flex dark:border-gray-800">
				<span>↑↓ 选择</span><span>Enter 打开</span><span>Esc 关闭</span>
			</div>
		</div>
	</div>
{/if}
