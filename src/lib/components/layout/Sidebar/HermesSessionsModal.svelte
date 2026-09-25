<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';

	import { mobile, showSidebar } from '$lib/stores';
	import { getHermesSessions, importHermesSession, type HermesSession } from '$lib/apis/hermes';
	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	dayjs.extend(relativeTime);

	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	export let show = false;

	// Surfaces a person talks to hermes on; the backend enforces the same set.
	const SOURCES = [
		{ id: 'telegram', label: 'Telegram' },
		{ id: 'qqbot', label: 'QQ' },
		{ id: 'cli', label: 'CLI' }
	];

	// Each surface keeps hundreds of sessions. Read one page at a time and walk
	// forward with the cursor the server hands back — hermes reports no total,
	// so there is no page count to number a pager with.
	const PAGE_SIZE = 20;

	let source = 'telegram';
	let sessions: HermesSession[] = [];
	let nextOffset = 0;
	let hasMore = false;
	let loading = false;
	let loadingMore = false;
	let error = '';
	let loadedFor = '';
	let importing: string | null = null;
	// Only the newest request may write to the list: switching tabs mid-flight
	// must not let the previous surface's rows land on the new one.
	let requestId = 0;

	const load = async (append = false) => {
		const wanted = source;
		const seq = ++requestId;
		const offset = append ? nextOffset : 0;
		if (append) {
			loadingMore = true;
		} else {
			loading = true;
			error = '';
			sessions = [];
			nextOffset = 0;
			hasMore = false;
		}
		try {
			const page = await getHermesSessions(localStorage.token, wanted, {
				limit: PAGE_SIZE,
				offset
			});
			if (seq !== requestId) return;
			// hermes repeats pinned conversations across windows, and a repeated
			// id would also break the keyed #each below.
			const seen = new Set<string>();
			sessions = [...(append ? sessions : []), ...page.sessions].filter((session) => {
				if (seen.has(session.id)) return false;
				seen.add(session.id);
				return true;
			});
			nextOffset = page.next_offset;
			hasMore = page.has_more;
			error = '';
		} catch (e) {
			if (seq !== requestId) return;
			if (append) {
				// Keep the rows already on screen; only the next page failed.
				hasMore = true;
				toast.error(`${e}`);
			} else {
				sessions = [];
				hasMore = false;
				error = `${e}`;
			}
		} finally {
			if (seq === requestId) {
				loading = false;
				loadingMore = false;
			}
		}
	};

	const loadMore = () => {
		if (!hasMore || loading || loadingMore) return;
		load(true);
	};

	/** Re-read the current surface from its first page. */
	const reload = () => {
		loadedFor = '';
	};

	// Fetch on open and whenever the source tab changes; forget on close so the
	// next open shows fresh data. `loadedFor` is claimed before awaiting so this
	// statement cannot fire the same load twice.
	$: if (!show && loadedFor) {
		loadedFor = '';
	}
	$: if (show && loadedFor !== source) {
		loadedFor = source;
		load();
	}

	// Pull the next page in as its marker scrolls into view; the button below it
	// stays the way to do it where IntersectionObserver is unavailable.
	const autoLoad = (node: HTMLElement) => {
		if (typeof IntersectionObserver === 'undefined') return {};
		const observer = new IntersectionObserver(
			(entries) => {
				if (entries.some((entry) => entry.isIntersecting)) loadMore();
			},
			{ rootMargin: '160px' }
		);
		observer.observe(node);
		return { destroy: () => observer.disconnect() };
	};

	const when = (value: number | string | null | undefined) => {
		if (value === null || value === undefined || value === '') return '';
		const parsed = typeof value === 'number' ? dayjs.unix(value) : dayjs(value);
		return parsed.isValid() ? parsed.fromNow() : '';
	};

	const openSession = async (session: HermesSession) => {
		importing = session.id;
		try {
			const result = await importHermesSession(localStorage.token, session.id);
			if (result?.created) {
				dispatch('change');
			}
			show = false;
			if ($mobile) {
				showSidebar.set(false);
			}
			await goto(`/c/${result.chat_id}`);
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			importing = null;
		}
	};
</script>

<Modal size="lg" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-5 pt-4 pb-1">
			<div class=" text-lg font-medium self-center">{$i18n.t('Hermes Sessions')}</div>
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
			<div class="flex items-center gap-1 mt-1">
				{#each SOURCES as item}
					<button
						class="rounded-full px-3 py-1 text-xs font-medium transition {source === item.id
							? 'bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-fg)]'
							: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-850 dark:text-gray-300 dark:hover:bg-gray-800'}"
						aria-pressed={source === item.id}
						on:click={() => {
							source = item.id;
						}}
					>
						{item.label}
					</button>
				{/each}
				<div class="flex-1"></div>
				<button
					class="rounded-full px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-850"
					disabled={loading || loadingMore}
					on:click={reload}
				>
					{$i18n.t('Refresh')}
				</button>
			</div>
			<hr class="border-gray-100 dark:border-gray-850 my-2" />

			<div class="max-h-[60vh] overflow-y-auto scrollbar-hidden">
				{#if loading}
					<div class="flex justify-center py-8"><Spinner className="size-5" /></div>
				{:else if error}
					<div class="flex flex-col items-center gap-2 py-8 text-sm text-gray-500">
						<div class="max-w-full truncate">{error}</div>
						<button
							class="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800"
							on:click={reload}
						>
							{$i18n.t('Retry')}
						</button>
					</div>
				{:else}
					<!-- A page can come back empty while more remain — hermes hands over
					     stretches of the empty shells dropped server-side — so "nothing
					     here" is only true once the walk is over. -->
					{#if sessions.length === 0 && !hasMore}
						<div class="py-8 text-center text-sm text-gray-500">
							{$i18n.t('No hermes sessions')}
						</div>
					{/if}
					{#each sessions as session (session.id)}
						<!-- The whole row opens the session; the pill on the right only states what
						     will happen, so the touch target is the full width. -->
						<button
							type="button"
							class="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/50 disabled:cursor-wait dark:hover:bg-gray-850"
							disabled={importing !== null}
							aria-busy={importing === session.id}
							on:click={() => openSession(session)}
						>
							<div class="min-w-0 flex-1">
								<div class="truncate text-sm font-medium">
									{session.title || session.preview || session.id}
								</div>
								<div
									class="mt-0.5 flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400"
								>
									<span>💬 {session.message_count}</span>
									{#if when(session.last_active)}
										<span>· {when(session.last_active)}</span>
									{/if}
									{#if session.title && session.preview}
										<span class="truncate">· {session.preview}</span>
									{/if}
								</div>
							</div>
							<!-- A quiet label, not a button: a column of solid blue pills drew the
							     eye away from the session titles. -->
							<span
								class="shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium transition {session.imported
									? 'text-gray-500 dark:text-gray-400'
									: 'text-primary-700 ring-1 ring-inset ring-primary-200 dark:text-primary-300 dark:ring-primary-800'}"
							>
								{#if importing === session.id}
									<Spinner className="size-3" />
								{:else if session.imported}
									{$i18n.t('Open')}
								{:else}
									{$i18n.t('Import and open')}
								{/if}
							</span>
						</button>
					{/each}

					{#if hasMore}
						<div class="flex justify-center py-3" use:autoLoad>
							{#if loadingMore}
								<Spinner className="size-4" />
							{:else}
								<button
									class="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600 transition hover:bg-gray-200 dark:bg-gray-850 dark:text-gray-300 dark:hover:bg-gray-800"
									on:click={loadMore}
								>
									{$i18n.t('Load more')}
								</button>
							{/if}
						</div>
					{/if}
				{/if}
			</div>
		</div>
	</div>
</Modal>
