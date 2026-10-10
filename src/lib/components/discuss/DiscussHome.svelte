<script lang="ts">
	import { afterUpdate, onDestroy, onMount, tick } from 'svelte';
	import { goto, replaceState } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import '$lib/components/teams/teams.css';
	import './discuss.css';
	import { config, mobile, models, showSidebar } from '$lib/stores';
	import {
		createDiscussion,
		DiscussApiError,
		deleteDiscussion,
		listDiscussions,
		type Discussion,
		type DiscussMode,
		type DiscussionSummary
	} from '$lib/apis/discussions';
	import { listLibrary, searchTemplates, type LibraryEntry } from '$lib/apis/assistant-library';
	import { v4 as uuidv4 } from 'uuid';
	import { discussionSeatModels } from '$lib/utils/discussion-seats';
	import { originLabel, takeHandoff, type HandoffOrigin } from '$lib/utils/handoff';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import HandoffBack from '$lib/components/common/HandoffBack.svelte';
	import LoadMore from '$lib/components/common/LoadMore.svelte';
	import { appendPage, cursorAfter, mergeHead } from '$lib/utils/paged';
	import { uploadErrorText, uploadFileReliably } from '$lib/utils/reliable-upload';
	import { isVideoFile, videoContactSheet } from '$lib/utils/video-contact-sheet';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import UploadProgress from '$lib/components/common/UploadProgress.svelte';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import ModeEmblem from '$lib/components/scifi/ModeEmblem.svelte';
	import ModeDock from '$lib/components/scifi/ModeDock.svelte';
	import ModeFlow from '$lib/components/scifi/ModeFlow.svelte';
	import { clearModeDraft, setModeDraft } from '$lib/components/scifi/mode-relay';
	import { warp } from '$lib/components/scifi/scifi';
	import { now, timeAgo } from '$lib/components/teams/clock';
	import SeatAvatar from './SeatAvatar.svelte';
	import SeatPicker from './SeatPicker.svelte';
	import {
		isLive,
		MAX_ROUNDS,
		MAX_SEATS,
		MIN_SEATS,
		MODES,
		modeSpec,
		modelById,
		modelRef,
		seatHue,
		STATUS_LABEL,
		type SeatDraft
	} from './model';

	const LAST_KEY = 'halo.discuss.last';

	let question = '';
	let mode: DiscussMode = 'roundtable';
	let seats: SeatDraft[] = [];
	let rounds = 2;
	let moderator = '';
	let research = false;
	// 主持人安排 (the default): the moderator reads the question and chooses the format, the rounds,
	// the seats and their roles; off, the user sets the table
	let smart = true;
	// 自动匹配助手: each question gets each seat a fitting assistant (on by default)
	let autoMatch = true;
	let library: LibraryEntry[] = [];
	let creating = false;
	// Handed over from a chat (its model menu, its + menu, a reply): the conversation as background
	// for every seat, and the way back.
	let background = '';
	let origin: HandoffOrigin | null = null;
	// Files for the question: images (for the models that read images) and documents (their text
	// goes to every seat). Uploaded as soon as they are picked, with a progress ring.
	type Attachment = { key: string; name: string; image: boolean; preview?: string; progress: number; id?: string; error?: string };
	const MAX_FILES = 4;
	let attachments: Attachment[] = [];
	let fileInput: HTMLInputElement;
	$: uploading = attachments.some((a) => !a.id && !a.error);
	// the dock takes the question, its uploaded files and its background to another mode
	afterUpdate(() =>
		setModeDraft('discuss', question, {
			context: background,
			from: origin,
			files: attachments
				.filter((a) => a.id)
				.map((a) => ({ id: a.id!, name: a.name, type: a.image ? ('image' as const) : ('file' as const) }))
		})
	);
	const attach = async (list: FileList | File[] | null | undefined) => {
		// A video also brings its frames as one picture, for the seats that read images.
		const files = (
			await Promise.all(
				Array.from(list ?? []).map(async (file) =>
					isVideoFile(file) ? [file, await videoContactSheet(file)] : [file]
				)
			)
		)
			.flat()
			.filter((file): file is File => !!file);
		const room = MAX_FILES - attachments.length;
		if (files.length > room) toast.info(`最多 ${MAX_FILES} 个附件`);
		await Promise.all(
			files.slice(0, Math.max(0, room)).map(async (file) => {
				const image = file.type.startsWith('image/');
				const item: Attachment = {
					key: `${Date.now()}-${Math.random()}`,
					name: file.name,
					image,
					preview: image ? URL.createObjectURL(file) : undefined,
					progress: 0
				};
				attachments = [...attachments, item];
				try {
					const { file: res } = await uploadFileReliably(localStorage.token, file, {
						...(image ? { process: false } : {}),
						onProgress: ({ percent }) => {
							item.progress = percent;
							attachments = attachments;
						}
					});
					if (!res?.id) throw new Error('上传失败');
					item.id = res.id;
				} catch (e: any) {
					item.error = uploadErrorText(e);
				}
				attachments = attachments;
			})
		);
	};
	const detach = (key: string) => {
		const item = attachments.find((a) => a.key === key);
		if (item?.preview) URL.revokeObjectURL(item.preview);
		attachments = attachments.filter((a) => a.key !== key);
	};
	let composer: HTMLTextAreaElement;
	let isMac = false;

	// the history a page at a time (newest first); filter, search and the live count on the server
	const PAGE = 30;
	let items: DiscussionSummary[] = [];
	let more = false;
	let loadingMore = false;
	let total: number | null = null;
	let liveTotal = 0;
	let searched = '';
	let filtered: 'all' | 'live' | 'ended' = 'all';
	let searchTimer: ReturnType<typeof setTimeout> | null = null;
	let loaded = false;
	let loadError = '';
	let filter: 'all' | 'live' | 'ended' = 'all';
	let query = '';
	let pendingDelete: DiscussionSummary | null = null;
	let showDelete = false;
	let timer: ReturnType<typeof setInterval> | null = null;

	// Text models that can sit at the table (the chat's model menu offers the same ones)
	$: choices = discussionSeatModels(($models ?? []) as any[], $config?.hermes_agent_model_ids);
	$: spec = modeSpec(mode);
	$: if (spec.fixedRounds) rounds = spec.rounds;
	$: seatsValid = seats.length >= MIN_SEATS && seats.length <= MAX_SEATS && seats.every((s) => modelById(choices, s.model));
	$: canStart = !creating && !uploading && !!question.trim() && (smart || seatsValid) && !!moderator;
	$: moderatorChoices = choices;
	$: webSearchEnabled = $config?.features?.enable_web_search !== false;

	const pickDefaults = () => {
		if (!choices.length) return;
		let saved: any = null;
		try {
			saved = JSON.parse(localStorage.getItem(LAST_KEY) || 'null');
		} catch {
			saved = null;
		}
		const incoming = takeHandoff(typeof sessionStorage === 'undefined' ? null : sessionStorage, 'discuss');
		const params = new URLSearchParams(window.location.search);
		const fromUrl = (params.get('models') || '')
			.split(',')
			.map((s) => s.trim())
			.filter((ref) => ref && modelById(choices, ref));
		const savedSeats: SeatDraft[] = Array.isArray(saved?.seats)
			? saved.seats.filter((s: any) => s?.model && modelById(choices, s.model))
			: [];
		if (fromUrl.length >= MIN_SEATS) {
			seats = fromUrl.slice(0, MAX_SEATS).map((ref) => ({ model: modelRef(modelById(choices, ref)!), role: '' }));
		} else if (savedSeats.length >= MIN_SEATS) {
			seats = savedSeats.slice(0, MAX_SEATS).map((s) => ({
				model: s.model,
				role: String(s.role || ''),
				...(s.assist === 'pick' || s.assist === 'generic' || s.assist === 'auto' ? { assist: s.assist } : {}),
				...(s.assist === 'pick' && s.assistant ? { assistant: s.assistant, assistantName: s.assistantName } : {}),
				...(s.duty ? { duty: String(s.duty).slice(0, 120) } : {})
			}));
		} else {
			seats = choices.slice(0, Math.min(3, choices.length)).map((m) => ({ model: modelRef(m), role: '' }));
		}
		// models ticked in the chat take the first seats (two of them: exactly those)
		const handed = (incoming?.models ?? [])
			.map((ref) => modelById(choices, ref))
			.filter((m): m is NonNullable<typeof m> => !!m)
			.map((m) => modelRef(m));
		if (handed.length) {
			const rest = seats.filter((s) => !handed.includes(s.model));
			seats = [
				...handed.slice(0, MAX_SEATS).map((model) => ({ model, role: '' })),
				...(handed.length >= MIN_SEATS ? [] : rest.slice(0, MIN_SEATS - handed.length))
			];
		}
		if (incoming) {
			if (incoming.text) question = incoming.text;
			background = incoming.context;
			origin = incoming.from;
			attachments = incoming.files.map((f) => ({
				key: `handoff-${f.id}`,
				name: f.name,
				image: f.type === 'image',
				preview: f.type === 'image' ? `${WEBUI_API_BASE_URL}/files/${f.id}/content` : undefined,
				progress: 100,
				id: f.id
			}));
		}
		if (saved?.mode && MODES.some((m) => m.value === saved.mode)) mode = saved.mode;
		research = saved?.research === true;
		autoMatch = saved?.autoMatch !== false;
		// models ticked in a chat or named in the link: the user has chosen the table
		smart = saved?.smart !== false && !handed.length && fromUrl.length < MIN_SEATS;
		// 「用于讨论」 from the assistant library: the first seat speaks with that assistant
		const picked = (params.get('assistant') || '').trim();
		if (/^(model|builtin):/.test(picked) && seats.length) {
			smart = false;
			seats = seats.map((s, i) => (i === 0 ? { ...s, assist: 'pick', assistant: picked, assistantName: undefined } : s));
			resolveNames();
		}
		if (Number.isInteger(saved?.rounds)) rounds = Math.max(1, Math.min(MAX_ROUNDS, saved.rounds));
		else rounds = modeSpec(mode).rounds;
		const strong = choices.find((m) => /claude|gpt/i.test(m.name ?? m.id));
		moderator =
			saved?.moderator && modelById(choices, saved.moderator)
				? saved.moderator
				: strong
					? modelRef(strong)
					: seats[0]?.model ?? '';
		const q = params.get('q');
		if (q && !question) question = q.slice(0, 8000);
		// read once: a reload or a later visit starts from the saved setup, not these
		if (params.has('q') || params.has('models') || params.has('assistant')) {
			try {
				replaceState('/discuss', {});
			} catch {
				// before the router is ready: harmless, the parameters are only read here
			}
		}
	};
	/** Names of picked assistants the page does not know yet (a link from the library, a saved setup). */
	const resolveNames = async () => {
		const missing = seats.filter((s) => s.assist === 'pick' && s.assistant && !s.assistantName).map((s) => s.assistant!);
		if (!missing.length) return;
		const names = new Map(library.map((a) => [a.ref, a.name]));
		const templates = missing.filter((ref) => ref.startsWith('builtin:'));
		if (templates.length) {
			try {
				for (const t of await searchTemplates(localStorage.token, { refs: templates })) names.set(t.ref, t.name);
			} catch {
				// shown by its reference
			}
		}
		seats = seats.map((s) => (s.assist === 'pick' && s.assistant && !s.assistantName && names.has(s.assistant) ? { ...s, assistantName: names.get(s.assistant) } : s));
	};
	const loadLibrary = async () => {
		try {
			library = (await listLibrary(localStorage.token)).assistants;
		} catch {
			library = [];
		}
		resolveNames();
	};

	let defaultsPicked = false;
	$: if (!defaultsPicked && choices.length) {
		defaultsPicked = true;
		pickDefaults();
	}

	const setMode = (value: DiscussMode) => {
		mode = value;
		rounds = modeSpec(value).rounds;
	};

	const resize = () => {
		if (!composer) return;
		composer.style.height = 'auto';
		composer.style.height = `${Math.min(composer.scrollHeight, 320)}px`;
	};

	// One key per question as sent: a retry after a lost response gets the same discussion back,
	// never a second one. A changed question or setup is a new request with a new key.
	let attempt: { payload: string; key: string } | null = null;
	const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

	const start = async () => {
		if (!canStart) return;
		creating = true;
		const form = {
			question: question.trim(),
			mode,
			smart,
			seats: smart
				? []
				: seats.map((s) => ({
						model: s.model,
						role: s.role.trim(),
						...(s.assist === 'pick' && s.assistant ? { assist: 'pick' as const, assistant: s.assistant } : s.assist === 'generic' ? { assist: 'generic' as const } : {}),
						...(s.duty?.trim() ? { duty: s.duty.trim() } : {})
					})),
			auto_match: smart || autoMatch,
			rounds,
			moderator,
			research,
			files: attachments.filter((a) => a.id).map((a) => a.id!),
			context: background
				? { text: background, title: origin?.title ?? '', chat_id: origin?.kind === 'chat' ? origin.id : null }
				: null
		};
		const payload = JSON.stringify(form);
		if (attempt?.payload !== payload) {
			attempt = { payload, key: uuidv4() };
		}
		try {
			const key = attempt.key;
			// a dropped connection (a phone between networks) is tried again with the same key
			const send = async (tries: number): Promise<Discussion> => {
				try {
					return await createDiscussion(localStorage.token, { ...form, client_key: key });
				} catch (e: any) {
					if (e instanceof DiscussApiError || tries >= 2) throw e;
					await sleep(1500 * (tries + 1));
					return send(tries + 1);
				}
			};
			const res = await send(0);
			attempt = null;
			if (res.deduplicated) toast.info('这个问题刚刚已经开始讨论了，直接打开它');
			attachments.forEach((a) => a.preview && URL.revokeObjectURL(a.preview));
			attachments = [];
			try {
				localStorage.setItem(LAST_KEY, JSON.stringify({ mode, seats, rounds, moderator, research, autoMatch, smart }));
			} catch {
				// storage unavailable: defaults next time
			}
			await goto(`/discuss/${res.id}`);
		} catch (e: any) {
			toast.error(e instanceof DiscussApiError ? e.message || '没能开始讨论' : '网络不稳，没能开始讨论；再点一次不会重复创建');
		} finally {
			creating = false;
		}
	};

	const QUICK = [
		{ mode: 'roundtable' as DiscussMode, title: '技术选型', text: '5 个人的团队做内部工具，后端数据库用 Postgres 还是 MongoDB？' },
		{ mode: 'review' as DiscussMode, title: '方案评审', text: '帮我评审这个方案，指出最大的风险和缺口：\n\n（把方案贴在这里）' },
		{ mode: 'debate' as DiscussMode, title: '正反辩论', text: 'AI 编程助手会让初级程序员成长得更慢吗？' },
		{ mode: 'brainstorm' as DiscussMode, title: '头脑风暴', text: '一个面向大学生的记账 App，怎样让人坚持用下去？' }
	];
	const useQuick = async (q: (typeof QUICK)[number]) => {
		setMode(q.mode);
		question = q.text;
		await tick();
		resize();
		composer?.focus();
	};

	const keyOf = (d: DiscussionSummary): [number, string] => [d.updated_at, d.id];
	const statusOf = (f: typeof filter) => (f === 'all' ? undefined : f);
	// the first page: afresh (a new filter or search), or folded into the pages already read
	const load = async (afresh = false) => {
		const q = searched;
		const f = filtered;
		try {
			const fresh = afresh || !loaded;
			const page = await listDiscussions(localStorage.token, {
				limit: PAGE,
				q,
				status: statusOf(f),
				...(fresh ? {} : { count: false })
			});
			if (q !== searched || f !== filtered) return; // a newer one went out meanwhile
			if (fresh) {
				items = page.items;
				more = !!page.next;
			} else {
				({ items, more } = mergeHead(items, page.items, !!page.next, more, (d) => d.id, keyOf));
			}
			if (page.total !== null) total = page.total;
			liveTotal = page.live ?? 0;
			loadError = '';
		} catch (e: any) {
			loadError = e?.message || '加载失败';
		} finally {
			loaded = true;
		}
	};
	const loadMore = async () => {
		const last = items[items.length - 1];
		if (loadingMore || !more || !last) return;
		loadingMore = true;
		const q = searched;
		const f = filtered;
		try {
			const page = await listDiscussions(localStorage.token, {
				limit: PAGE,
				q,
				status: statusOf(f),
				before: cursorAfter(keyOf(last))
			});
			if (q !== searched || f !== filtered) return;
			items = appendPage(items, page.items, (d) => d.id);
			more = !!page.next;
		} catch (e: any) {
			toast.error(e?.message || '加载失败');
		} finally {
			loadingMore = false;
		}
	};
	// a filter at once, a search a moment after typing: both over the whole history
	$: if (filter !== filtered) {
		filtered = filter;
		load(true);
	}
	$: if (query.trim() !== searched) {
		if (searchTimer) clearTimeout(searchTimer);
		const wanted = query.trim();
		searchTimer = setTimeout(() => {
			searched = wanted;
			load(true);
		}, 300);
	}

	const FILTERS = [
		{ value: 'all', label: '全部' },
		{ value: 'live', label: '进行中' },
		{ value: 'ended', label: '已结束' }
	] as const;
	// a run that ended while the 进行中 filter is on leaves it at the next refresh
	$: shown = items;
	$: liveCount = Math.max(liveTotal, items.filter((d) => isLive(d.status) || d.running).length);

	const askDelete = (d: DiscussionSummary) => {
		pendingDelete = d;
		showDelete = true;
	};
	const confirmDelete = async () => {
		const d = pendingDelete;
		pendingDelete = null;
		if (!d) return;
		try {
			await deleteDiscussion(localStorage.token, d.id);
			items = items.filter((x) => x.id !== d.id);
			if (total !== null) total = Math.max(0, total - 1);
			toast.success('已删除');
		} catch (e: any) {
			toast.error(e?.message || '删除失败');
		}
	};

	onMount(() => {
		isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
		warp(520);
		load();
		loadLibrary();
		// while anything is under way, the first page again (never every page read)
		timer = setInterval(() => {
			if (!document.hidden && liveCount > 0) load();
		}, 4000);
		tick().then(resize);
	});
	onDestroy(() => {
		if (timer) clearInterval(timer);
		if (searchTimer) clearTimeout(searchTimer);
		clearModeDraft('discuss');
	});
</script>

<div class="tm-ambient relative flex h-screen max-h-[100dvh] w-full flex-col" data-teams-ui data-discuss-ui data-discuss-home>
	<nav class="flex flex-wrap items-center gap-2 px-3 pt-2 pb-1">
		<div class="{$mobile ? '' : 'hidden'} flex flex-none items-center">
			<button
				class="rounded-xl p-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
				on:click={() => showSidebar.set(!$showSidebar)}
				aria-label="切换侧栏"><MenuLines /></button
			>
		</div>
		<h1 class="sr-only">讨论台</h1>
		<ModeDock current="discuss" />
		{#if origin}
			<HandoffBack {origin} />
		{/if}
	</nav>

	<div class="tm-scroll flex-1 overflow-y-auto px-4 pb-16">
		<div class="mx-auto flex max-w-3xl flex-col pt-6 sm:pt-14">
			<header class="halo-mode-hero tm-rise relative mb-6 flex flex-col gap-3">
				<ModeEmblem mode="discuss" stats={[{ k: 'SESSIONS', v: total ?? items.length }, { k: 'LIVE', v: liveCount }]} />
				<div class="flex items-center gap-2">
					<span class="tm-eyebrow halo-mode-eyebrow">Halo Roundtable</span>
					<span class="h-3 w-px bg-gray-300 dark:bg-gray-700" aria-hidden="true" />
					<span class="text-xs text-gray-500 dark:text-gray-400">多模型讨论</span>
				</div>
				<h2 class="halo-mode-title tm-display text-[28px] font-semibold leading-[1.15] text-gray-950 sm:text-[36px] dark:text-white">
					让几个模型把问题讨论透
				</h2>
				<ModeFlow
					label="讨论怎么进行"
					steps={smart
						? ['主持人读题', '安排方式、轮数与席位', '各自发言、互相交锋', '主持人给结论']
						: ['选 2–5 个席位', '同一轮各自发言', '互相补充、交锋', '主持人给结论']}
				/>
				<p class="hidden max-w-xl text-sm leading-relaxed text-gray-500 sm:block dark:text-gray-400">
					写下问题，主持人会先读题，像协作台的负责人一样安排：用圆桌、各自回答、辩论、评审还是头脑风暴，讨论几轮，请哪几个模型（2–5 位），各自担任什么角色、配什么助手。同一轮里大家同时发言，最后由主持人给出结论，并把共识和分歧分开列出来。也可以切到「自己安排」手动选。
				</p>
			</header>

			<form
				class="tm-rise composer tm-card relative flex flex-col"
				style="--i:1"
				on:submit|preventDefault={start}
				on:dragover|preventDefault
				on:drop|preventDefault={(e) => attach(e.dataTransfer?.files)}
				data-discuss-composer
				data-scifi-conduit
			>
				<label for="discuss-question" class="sr-only">要讨论的问题</label>
				<textarea
					id="discuss-question"
					bind:this={composer}
					bind:value={question}
					rows="3"
					maxlength="8000"
					class="tm-scroll w-full resize-none bg-transparent px-5 pt-4 pb-2 text-[15px] leading-relaxed text-gray-900 outline-none placeholder:text-gray-400 dark:text-gray-100 dark:placeholder:text-gray-500"
					placeholder="写下要讨论的问题，比如：小团队的内部工具，后端用 Postgres 还是 MongoDB？"
					on:input={resize}
					on:paste={(e) => {
						const files = e.clipboardData?.files;
						if (files?.length) {
							e.preventDefault();
							attach(files);
						}
					}}
					on:keydown={(e) => {
						if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
							e.preventDefault();
							start();
						}
					}}
				/>
				{#if attachments.length}
					<ul class="flex flex-wrap items-center gap-2 px-4 pb-2" aria-label="附件" data-discuss-attachments>
						{#each attachments as a (a.key)}
							<li class="relative" data-attachment-state={a.error ? 'failed' : a.id ? 'ready' : 'uploading'}>
								{#if a.image}
									<div class="relative size-12 overflow-hidden rounded-xl ring-1 ring-gray-200/70 dark:ring-white/10">
										<img src={a.preview} alt={a.name} class="size-full object-cover" />
										{#if !a.id && !a.error}
											<UploadProgress progress={a.progress} ringClassName="size-8" className="absolute inset-0 bg-black/50 text-white" />
										{/if}
									</div>
								{:else}
									<span class="dc-chip max-w-[14rem] !pr-6">
										{#if !a.id && !a.error}
											<UploadProgress progress={a.progress} ringClassName="size-4" showPercent={false} />
										{/if}
										<span class="truncate" title={a.name}>{a.name}</span>
										{#if !a.id && !a.error}<span class="tm-num shrink-0 text-gray-400">{a.progress < 100 ? `${a.progress}%` : '处理中'}</span>{/if}
									</span>
								{/if}
								{#if a.error}
									<span class="absolute inset-x-0 -bottom-4 truncate text-[10px] text-red-500" title={a.error}>{a.error}</span>
								{/if}
								<button
									type="button"
									class="absolute -top-1.5 -right-1.5 grid size-4 place-items-center rounded-full bg-gray-900 text-[10px] text-white ring-2 ring-white dark:bg-gray-100 dark:text-gray-900 dark:ring-gray-900"
									aria-label="去掉 {a.name}"
									on:click={() => detach(a.key)}>×</button
								>
							</li>
						{/each}
					</ul>
				{/if}

				{#if background}
					<div class="px-4 pb-2" data-discuss-context>
						<span class="dc-chip relative max-w-full !pr-6" title={background.slice(0, 600)}>
							<svg class="size-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
								><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg
							>
							<span class="truncate">带上{origin ? originLabel(origin) : '之前的对话'}作背景</span>
							<span class="tm-num shrink-0 text-gray-400">{background.length} 字</span>
							<button
								type="button"
								class="absolute right-1 top-1/2 grid size-4 -translate-y-1/2 place-items-center rounded-full text-gray-400 hover:bg-gray-500/15 hover:text-gray-700 dark:hover:text-gray-200"
								aria-label="不带对话背景"
								on:click={() => (background = '')}
								data-discuss-context-remove>×</button
							>
						</span>
					</div>
				{/if}

				<div class="flex flex-col gap-3 border-t border-gray-100 px-4 pt-3 pb-3 dark:border-gray-800/70">
					<div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
						<div class="tm-segment w-fit" role="radiogroup" aria-label="谁来安排讨论" data-discuss-planner>
							<button type="button" role="radio" aria-checked={smart} on:click={() => (smart = true)} data-discuss-smart="on"
								>主持人安排</button
							>
							<button type="button" role="radio" aria-checked={!smart} on:click={() => (smart = false)} data-discuss-smart="off"
								>自己安排</button
							>
						</div>
						{#if smart}
							<span class="text-[11.5px] leading-snug text-gray-500 dark:text-gray-400" data-discuss-smart-hint
								>主持人读完问题再定讨论方式、轮数、参与模型和各自的角色与助手</span
							>
						{/if}
					</div>
					{#if !smart}
					<div class="tm-scroll tm-fade-x -mx-1 flex items-center gap-1.5 overflow-x-auto px-1" role="radiogroup" aria-label="讨论方式">
						{#each MODES as m}
							<button
								type="button"
								class="dc-chip shrink-0"
								role="radio"
								aria-checked={mode === m.value}
								data-on={mode === m.value}
								title={m.hint}
								on:click={() => setMode(m.value)}
								data-discuss-mode={m.value}>{m.label}</button
							>
						{/each}
						<span class="hidden shrink-0 pl-1 text-[11px] text-gray-400 sm:inline dark:text-gray-500">{spec.hint}</span>
					</div>

					<SeatPicker bind:seats {choices} mode={spec} {autoMatch} {library} />
					{/if}
					<input bind:this={fileInput} type="file" multiple class="hidden" on:change={(e) => { attach(e.currentTarget.files); e.currentTarget.value = ''; }} data-discuss-file-input />

					<div class="flex flex-wrap items-center gap-2">
						<button
							type="button"
							class="dc-chip"
							disabled={attachments.length >= MAX_FILES}
							title="附带文件或图片：文档的文字给每位参与者，图片给能看图的模型（也可以粘贴或拖进来）"
							on:click={() => fileInput?.click()}
							data-discuss-attach
							><svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
								><path d="M10.5 4.5 5.4 9.6a1.6 1.6 0 0 0 2.3 2.3l5.2-5.2a3 3 0 0 0-4.3-4.3L3.4 7.6a4.4 4.4 0 0 0 6.2 6.2l4-4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" /></svg
							>附件</button
						>
						{#if !smart}
						<div class="dc-chip !pr-1 !pl-2.5" data-discuss-rounds>
							<span>轮数</span>
							<button
								type="button"
								class="grid size-5 place-items-center rounded-full hover:bg-gray-500/10 disabled:opacity-30"
								disabled={spec.fixedRounds || rounds <= 1}
								on:click={() => (rounds = Math.max(1, rounds - 1))}
								aria-label="少一轮">−</button
							>
							<b class="tm-num w-3 text-center text-gray-800 dark:text-gray-100">{rounds}</b>
							<button
								type="button"
								class="grid size-5 place-items-center rounded-full hover:bg-gray-500/10 disabled:opacity-30"
								disabled={spec.fixedRounds || rounds >= MAX_ROUNDS}
								on:click={() => (rounds = Math.min(MAX_ROUNDS, rounds + 1))}
								aria-label="多一轮">+</button
							>
						</div>
						{/if}
						<label
							class="dc-chip !py-1 !pr-1.5"
							title={smart ? '主持人：先读问题安排讨论方式、轮数和席位，所有人发言后写结论' : '主持人：所有人发言后写结论，列出共识与分歧'}
							data-discuss-moderator
						>
							<span>主持人</span>
							<select bind:value={moderator} class="dc-select max-w-[9rem] truncate">
								{#each moderatorChoices as m (m.id)}
									<option value={modelRef(m)}>{m.name ?? m.id}</option>
								{/each}
							</select>
						</label>
						{#if !smart}
						<button
							type="button"
							class="dc-chip"
							aria-pressed={autoMatch}
							title="开始时按问题、讨论方式和席位职责，为每个模型匹配一个助手（用它的完整设定发言，模型不变）；指定了助手的席位保持不变"
							on:click={() => (autoMatch = !autoMatch)}
							data-discuss-automatch-toggle
						>
							<svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
								><circle cx="8" cy="5.5" r="2.6" stroke="currentColor" stroke-width="1.3" /><path
									d="M3 13.5c.6-2.6 2.6-4 5-4s4.4 1.4 5 4"
									stroke="currentColor"
									stroke-width="1.3"
									stroke-linecap="round"
								/></svg
							>
							自动匹配助手
						</button>
						{/if}
						{#if webSearchEnabled}
							<button
								type="button"
								class="dc-chip"
								aria-pressed={research}
								title="开始前用联网搜索查一次资料，所有参与者看同一份资料并标注引用 [n]（多花约半分钟）"
								on:click={() => (research = !research)}
								data-discuss-research-toggle
							>
								<svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
									><circle cx="8" cy="8" r="6.2" stroke="currentColor" stroke-width="1.3" /><path
										d="M1.8 8h12.4M8 1.8c1.8 2 1.8 10.4 0 12.4M8 1.8c-1.8 2-1.8 10.4 0 12.4"
										stroke="currentColor"
										stroke-width="1.1"
									/></svg
								>
								联网查资料
							</button>
						{/if}
						<div class="ml-auto flex items-center gap-2">
							<kbd class="hidden rounded-md px-1.5 py-0.5 font-mono text-[11px] text-gray-400 sm:inline-block">{isMac ? '⌘' : 'Ctrl'} ↵</kbd>
							<button type="submit" class="tm-btn-primary" disabled={!canStart} data-discuss-start>
								{#if creating}
									<span class="size-3.5 animate-spin rounded-full border-2 border-current border-r-transparent" aria-hidden="true" />开始中…
								{:else}
									开始讨论
									<svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
										><path d="M3 8h9.5M8.5 4l4 4-4 4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" /></svg
									>
								{/if}
							</button>
						</div>
					</div>
				</div>
			</form>
			<p class="mt-2 px-1 text-[11px] leading-relaxed text-gray-400 dark:text-gray-500">
				{#if smart}
					主持人先安排一次、为席位配助手一次，之后每轮每位参与者调用一次模型，最后主持人再总结一次（席位与轮数由主持人按问题定：简单问题 2–3 位 1–2 轮，复杂问题最多 5 位 4 轮）。
				{:else}
					每轮每位参与者调用一次模型，最后主持人再调用一次（{seats.length} 位 × {rounds} 轮 + 1 = 约 {seats.length * rounds + 1} 次）。
				{/if}
				Hermes 不参加讨论——它是要跑工具的代理；讨论结束后可以把结论「交给 Hermes」去核查或执行。
			</p>

			<section class="tm-rise mt-6" style="--i:2" aria-label="快速开始">
				<div class="mb-2"><span class="tm-eyebrow">快速开始</span></div>
				<ul class="grid grid-cols-2 gap-2 sm:grid-cols-4">
					{#each QUICK as q}
						<li>
							<button
								type="button"
								class="tm-card-quiet tm-hover flex h-full w-full flex-col items-start gap-1 px-3 py-2.5 text-left"
								on:click={() => useQuick(q)}
								title={q.text}
							>
								<span class="text-[13px] font-medium text-gray-900 dark:text-gray-100">{q.title}</span>
								<span class="text-[11.5px] text-gray-500 dark:text-gray-400">{modeSpec(q.mode).label} · {modeSpec(q.mode).hint}</span>
							</button>
						</li>
					{/each}
				</ul>
			</section>

			<section class="tm-rise mt-10" style="--i:3" aria-label="我的讨论">
				<div class="mb-3 flex flex-wrap items-center gap-3">
					<h3 class="tm-display text-lg font-semibold text-gray-900 dark:text-gray-50">我的讨论</h3>
					<span class="tm-num text-sm text-gray-400">{total ?? items.length}</span>
					<input
						type="search"
						bind:value={query}
						placeholder="搜索标题或问题"
						class="ml-auto w-full rounded-full border border-gray-200/70 bg-transparent px-3.5 py-1.5 text-xs outline-none focus:border-blue-400/60 sm:w-56 dark:border-gray-800"
					/>
				</div>
				<div class="tm-segment mb-3 w-fit" role="tablist">
					{#each FILTERS as f}
						<button type="button" role="tab" aria-selected={filter === f.value} on:click={() => (filter = f.value)}
							>{f.label}{#if f.value === 'live' && liveCount}<span class="tm-num ml-1 opacity-60">{liveCount}</span>{/if}</button
						>
					{/each}
				</div>

				{#if !loaded}
					<div class="flex flex-col gap-2">
						{#each [0, 1, 2] as i}
							<div class="tm-card h-[4.5rem] animate-pulse opacity-60" style="animation-delay: {i * 120}ms" />
						{/each}
					</div>
				{:else if loadError}
					<p class="text-sm text-red-600 dark:text-red-300">{loadError}</p>
				{:else if !shown.length}
					<div class="flex flex-col items-center gap-2 py-12 text-center text-sm text-gray-400 dark:text-gray-500">
						{searched || filtered !== 'all' ? '没有符合条件的讨论' : '还没有讨论。写下一个问题，让几个模型一起想。'}
					</div>
				{:else}
					<ul class="flex flex-col gap-2" data-discuss-list>
						{#each shown as d (d.id)}
							{@const live = isLive(d.status) || d.running}
							<li class="group tm-card tm-hover relative flex items-center gap-3 px-4 py-3" data-discuss-row={d.id}>
								<div class="flex shrink-0 -space-x-2">
									{#each (d.seats ?? []).slice(0, 4) as seat, i}
										<SeatAvatar model={seat.model} name={seat.label} hue={seatHue(i)} state={live ? 'streaming' : 'idle'} size={22} />
									{/each}
								</div>
								<a href="/discuss/{d.id}" class="min-w-0 flex-1 after:absolute after:inset-0" data-sveltekit-preload-data="off">
									<div class="flex min-w-0 items-center gap-2">
										<span class="truncate text-[14px] font-medium text-gray-900 dark:text-gray-100">{d.title}</span>
									</div>
									<div class="mt-0.5 truncate text-xs text-gray-500 dark:text-gray-400">
										{d.preview || d.question}
									</div>
									<div class="mt-1 flex items-center gap-1.5 text-[11px] text-gray-400 dark:text-gray-500">
										<span>{modeSpec(d.mode).label}</span>
										<span aria-hidden="true">·</span>
										<span>{d.seats?.length ?? 0} 位</span>
										{#if d.asks > 1}<span aria-hidden="true">·</span><span>{d.asks} 问</span>{/if}
										<span aria-hidden="true">·</span>
										<span>{timeAgo(d.updated_at, $now)}</span>
									</div>
								</a>
								<span
									class="relative shrink-0 rounded-full px-2 py-0.5 text-[11px] {live
										? 'bg-blue-500/10 text-blue-600 dark:text-blue-300'
										: d.status === 'error'
											? 'bg-red-500/10 text-red-600 dark:text-red-300'
											: 'bg-gray-500/10 text-gray-500 dark:text-gray-400'}"
									>{live ? (d.status === 'concluding' ? '总结中' : '讨论中') : STATUS_LABEL[d.status] ?? d.status}</span
								>
								<button
									type="button"
									class="relative shrink-0 rounded-lg p-1.5 text-gray-400 opacity-60 hover:bg-red-500/10 hover:text-red-600 group-hover:opacity-100 max-sm:opacity-100"
									aria-label="删除「{d.title}」"
									on:click={() => askDelete(d)}
									><svg class="size-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true"
										><path d="M3 4.5h10M6.5 4.5V3h3v1.5M5 4.5l.5 8.5h5l.5-8.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" /></svg
									></button
								>
							</li>
						{/each}
					</ul>
					<LoadMore {more} loading={loadingMore} onMore={loadMore} {total} shown={items.length} />
				{/if}
			</section>
		</div>
	</div>
</div>

<ConfirmDialog
	bind:show={showDelete}
	title="删除这个讨论？"
	message={`「${pendingDelete?.title ?? ''}」和其中所有发言、结论都会删除（它也是一个对话，会一起从侧栏消失）。`}
	confirmLabel="删除"
	on:confirm={confirmDelete}
/>

<style>
	.composer {
		border-radius: 1.4rem;
		transition:
			box-shadow 0.3s var(--tm-ease),
			border-color 0.3s ease;
	}
	.composer:focus-within {
		border-color: hsl(var(--tm-accent) / 0.45);
		box-shadow:
			0 0 0 4px hsl(var(--tm-accent) / 0.1),
			var(--tm-shadow-lift);
	}
</style>
