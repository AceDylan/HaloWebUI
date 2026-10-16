<script lang="ts">
	/**
	 * 视频工作台 (/workspace/videos). The workbench writes a brief — what you want, how it should be
	 * made (做法), frame, length, narration, subtitles, reference files — and hands it to a new chat
	 * with Hermes, sent at once: Hermes itself or a runner (codex, reclaude …, by the command in
	 * front) makes the video with its video-studio skill and hands it over as MEDIA. Every video a
	 * reply or a runner's report hands over lands in the library (backend utils/video_library.py),
	 * which comes a page at a time and loads each player only when it scrolls into view.
	 */
	import { afterUpdate, onDestroy, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { goto, replaceState } from '$app/navigation';

	import { config, models } from '$lib/stores';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import { ensureModels } from '$lib/services/models';
	import { deleteLibraryVideo, getVideoPage, type LibraryVideo } from '$lib/apis/video-studio';
	import { uploadFileReliably } from '$lib/utils/reliable-upload';
	import { isHermesAgentModel } from '$lib/utils/hermes';
	import { getModelSelectionId } from '$lib/utils/model-identity';
	import { formatFileSize } from '$lib/utils';
	import { handOff, takeHandoff, type HandoffOrigin } from '$lib/utils/handoff';
	import {
		VIDEO_FRAMES,
		VIDEO_LENGTHS,
		VIDEO_MAKERS,
		VIDEO_RECIPES,
		VIDEO_VOICES,
		attachmentKind,
		buildVideoBrief,
		normalizeVideoSettings,
		type VideoSettings
	} from '$lib/utils/video-brief';
	import { clearModeDraft, setModeDraft } from '$lib/components/scifi/mode-relay';
	import HandoffBack from '$lib/components/common/HandoffBack.svelte';
	import LoadMore from '$lib/components/common/LoadMore.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import UploadProgress from '$lib/components/common/UploadProgress.svelte';
	import SidebarModeIcon from '$lib/components/layout/Sidebar/SidebarModeIcon.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import ArrowDownTray from '$lib/components/icons/ArrowDownTray.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	const SETTINGS_KEY = 'halo.videoStudio.settings';
	const MAX_ATTACHMENTS = 8;
	const PAGE = 24;

	type Tab = 'workbench' | 'library';
	let tab: Tab = 'workbench';

	// ---- workbench -----------------------------------------------------------------------------
	let idea = '';
	let settings: VideoSettings = normalizeVideoSettings(null);
	let origin: HandoffOrigin | null = null;
	let ideaBox: HTMLTextAreaElement;
	let fileInput: HTMLInputElement;

	type Attachment = {
		key: string;
		id: string;
		name: string;
		kind: 'image' | 'video' | 'audio' | 'file';
		preview?: string;
		uploading?: boolean;
		progress?: number;
	};
	let attachments: Attachment[] = [];

	$: hermes = (($models ?? []) as any[]).find((m) => isHermesAgentModel(m, $config?.hermes_agent_model_ids)) ?? null;
	let modelsChecked = false;
	$: uploading = attachments.some((a) => a.uploading);
	$: ready = attachments.filter((a) => !a.uploading && a.id);
	$: brief = buildVideoBrief({
		...settings,
		idea: idea.trim() || '（在左边写下想要的视频）',
		attachments: ready.map((a) => ({ name: a.name, kind: a.kind }))
	});
	$: recipe = VIDEO_RECIPES.find((r) => r.key === settings.recipe) ?? VIDEO_RECIPES[0];
	$: maker = VIDEO_MAKERS.find((m) => m.key === settings.maker) ?? VIDEO_MAKERS[0];
	$: blocked = !hermes
		? modelsChecked
			? '没有可用的 Hermes 模型：视频由 Hermes 或 runner 制作'
			: '正在读取模型…'
		: uploading
			? '附件还在上传'
			: !idea.trim()
				? '先写下想要的视频'
				: '';

	const saveSettings = () => {
		try {
			localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
		} catch {
			/* private mode: the choices just are not remembered */
		}
	};

	const addFiles = async (list: Iterable<File> | null | undefined) => {
		const picked = Array.from(list ?? []);
		const room = MAX_ATTACHMENTS - attachments.length;
		if (picked.length > room) toast.info(`最多 ${MAX_ATTACHMENTS} 个附件`);
		await Promise.all(
			picked.slice(0, Math.max(0, room)).map(async (file) => {
				const kind = attachmentKind(file.type, file.name);
				const item: Attachment = {
					key: `${file.name}-${file.size}-${Math.random().toString(36).slice(2)}`,
					id: '',
					name: file.name,
					kind,
					preview: kind === 'image' ? URL.createObjectURL(file) : undefined,
					uploading: true,
					progress: 0
				};
				attachments = [...attachments, item];
				try {
					// Hermes and the runners read the original file on the host: nothing to extract here
					// (the chat uploads for Hermes the same way).
					const { file: stored } = await uploadFileReliably(localStorage.token, file, {
						process: false,
						onProgress: ({ percent }) => {
							if (!item.uploading || item.progress === percent) return;
							item.progress = percent;
							attachments = attachments;
						}
					});
					if (!stored?.id) throw new Error('upload failed');
					item.id = stored.id;
					item.uploading = false;
					delete item.progress;
					attachments = attachments;
				} catch (error) {
					console.warn('video studio upload failed', error);
					if (item.preview) URL.revokeObjectURL(item.preview);
					attachments = attachments.filter((a) => a !== item);
					toast.error(`「${file.name}」上传失败`);
				}
			})
		);
	};

	const removeAttachment = (item: Attachment) => {
		if (item.preview) URL.revokeObjectURL(item.preview);
		// The file stays on the server: it may have come from a chat (a handoff), and an upload
		// left behind costs little.
		attachments = attachments.filter((a) => a !== item);
	};

	const start = () => {
		if (blocked || !hermes) return;
		saveSettings();
		const stored = handOff(typeof sessionStorage === 'undefined' ? null : sessionStorage, {
			to: 'chat',
			text: buildVideoBrief({
				...settings,
				idea,
				attachments: ready.map((a) => ({ name: a.name, kind: a.kind }))
			}),
			models: [getModelSelectionId(hermes)],
			files: ready.map((a) => ({ id: a.id, name: a.name, type: a.kind === 'image' ? 'image' : 'file' })),
			from: origin,
			send: true
		});
		if (!stored) {
			toast.error('浏览器不让暂存这次的需求，没法带到对话里');
			return;
		}
		goto('/');
	};

	const onKeydown = (event: KeyboardEvent) => {
		if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
			event.preventDefault();
			start();
		}
	};

	// ---- library -------------------------------------------------------------------------------
	let videos: LibraryVideo[] = [];
	let next: string | null = null;
	let loadingMore = false;
	let libraryLoaded = false;
	let query = '';
	let asked = '';
	let searchTimer: ReturnType<typeof setTimeout> | null = null;
	let playing: LibraryVideo | null = null;
	let playerOpen = false;
	$: if (!playerOpen) playing = null;
	const play = (video: LibraryVideo) => {
		playing = video;
		playerOpen = true;
	};

	const loadFirst = async () => {
		const q = query.trim();
		asked = q;
		try {
			const page = await getVideoPage(localStorage.token, { limit: PAGE, q });
			if (asked !== q) return; // a newer search went out meanwhile
			videos = page.items;
			next = page.next;
		} catch (error) {
			console.warn('video library unavailable', error);
			toast.error('视频库读取失败');
		} finally {
			libraryLoaded = true;
		}
	};

	const loadMore = async () => {
		if (loadingMore || !next) return;
		loadingMore = true;
		const q = asked;
		try {
			const page = await getVideoPage(localStorage.token, { limit: PAGE, before: next, q });
			if (asked !== q) return;
			const seen = new Set(videos.map((v) => v.id));
			videos = [...videos, ...page.items.filter((v) => !seen.has(v.id))];
			next = page.next;
		} catch (error) {
			console.warn('video library page failed', error);
			toast.error('加载失败');
		} finally {
			loadingMore = false;
		}
	};

	$: if (libraryLoaded && query.trim() !== asked) {
		if (searchTimer) clearTimeout(searchTimer);
		searchTimer = setTimeout(loadFirst, 300);
	}

	const remove = async (video: LibraryVideo) => {
		try {
			await deleteLibraryVideo(localStorage.token, video.id);
			videos = videos.filter((v) => v.id !== video.id);
			if (playing?.id === video.id) playerOpen = false;
			toast.success(video.chatId ? '已从视频库移除，对话里的视频还在' : '已从视频库移除');
		} catch (error) {
			console.warn('video remove failed', error);
			toast.error('移除失败');
		}
	};

	const videoTitle = (video: LibraryVideo) => video.chatTitle || video.title || video.name;
	const dateLabel = (ms: number) => {
		const d = new Date(ms);
		return Number.isNaN(d.getTime()) ? '' : d.toLocaleString(undefined, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
	};

	// A player gets its file only when it comes near the screen: a page of 24 would otherwise ask
	// for 24 videos at once.
	const nearScreen = (node: HTMLVideoElement, src: string) => {
		let observer: IntersectionObserver | null = null;
		const load = () => {
			node.src = `${src}#t=0.1`;
			observer?.disconnect();
			observer = null;
		};
		if (typeof IntersectionObserver === 'undefined') load();
		else {
			observer = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && load(), {
				rootMargin: '300px 0px'
			});
			observer.observe(node);
		}
		return { destroy: () => observer?.disconnect() };
	};

	// ---- page ----------------------------------------------------------------------------------
	const setTab = (value: Tab) => {
		tab = value;
		const url = new URL(window.location.href);
		if (value === 'library') url.searchParams.set('tab', 'library');
		else url.searchParams.delete('tab');
		replaceState(`${url.pathname}${url.search}`, {});
	};

	onMount(async () => {
		try {
			settings = normalizeVideoSettings(JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? 'null'));
		} catch {
			settings = normalizeVideoSettings(null);
		}
		if (new URL(window.location.href).searchParams.get('tab') === 'library') tab = 'library';

		// Work handed over from a chat or another mode (the dock, 「交给…」): the draft is the idea,
		// its files the attachments, its conversation background the brief keeps.
		const incoming = takeHandoff(typeof sessionStorage === 'undefined' ? null : sessionStorage, 'video');
		if (incoming) {
			tab = 'workbench';
			idea = [incoming.text, incoming.context ? `背景：\n${incoming.context}` : ''].filter(Boolean).join('\n\n');
			origin = incoming.from;
			attachments = incoming.files.map((f) => ({
				key: f.id,
				id: f.id,
				name: f.name,
				kind: f.type === 'image' ? 'image' : attachmentKind('', f.name),
				preview: f.type === 'image' ? `${WEBUI_API_BASE_URL}/files/${f.id}/content` : undefined
			}));
		}

		void loadFirst();
		if (($models ?? []).length === 0) await ensureModels(localStorage.token, { reason: 'video-studio' }).catch(() => {});
		modelsChecked = true;
		if (tab === 'workbench') ideaBox?.focus();
	});

	afterUpdate(() =>
		setModeDraft('video', idea, {
			from: origin,
			files: ready.map((a) => ({ id: a.id, name: a.name, type: a.kind === 'image' ? 'image' : 'file' }))
		})
	);
	onDestroy(() => {
		clearModeDraft('video');
		if (searchTimer) clearTimeout(searchTimer);
		attachments.forEach((a) => a.preview?.startsWith('blob:') && URL.revokeObjectURL(a.preview));
	});

	const chip =
		'rounded-full border px-3 py-1.5 text-xs font-medium transition disabled:opacity-50 border-gray-200/70 bg-white/80 text-gray-600 hover:border-gray-300 hover:text-gray-900 dark:border-gray-700/60 dark:bg-white/[0.03] dark:text-gray-300 dark:hover:border-gray-600 dark:hover:text-white';
	const chipOn =
		'rounded-full border px-3 py-1.5 text-xs font-medium transition border-gray-900 bg-gray-900 text-white dark:border-white dark:bg-white dark:text-gray-900';
</script>

{#if origin}
	<div class="mb-2 flex" data-video-origin>
		<HandoffBack {origin} className="-ml-2.5" />
	</div>
{/if}

<div class="halo-seg mb-4 flex w-fit max-w-full items-center overflow-x-auto scrollbar-hidden">
	<button class="tab-button {tab === 'workbench' ? 'active' : ''}" on:click={() => setTab('workbench')} data-video-tab="workbench">
		<SidebarModeIcon mode="video" className="size-4" />
		<span>工作台</span>
	</button>
	<button class="tab-button {tab === 'library' ? 'active' : ''}" on:click={() => setTab('library')} data-video-tab="library">
		<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
			><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></svg
		>
		<span>视频库{videos.length ? ` · ${videos.length}${next ? '+' : ''}` : ''}</span>
	</button>
</div>

{#if tab === 'workbench'}
	<form
		class="flex flex-col gap-4 lg:grid lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] lg:items-start"
		on:submit|preventDefault={start}
		data-video-workbench
	>
		<section class="flex min-w-0 flex-col gap-4">
			<!-- svelte-ignore a11y-no-static-element-interactions -->
			<div
				class="glass-item relative p-4 space-y-3"
				data-scifi-conduit
				on:dragover={(event) => {
					if (event.dataTransfer?.types?.includes('Files')) event.preventDefault();
				}}
				on:drop={(event) => {
					if (!event.dataTransfer?.files?.length) return;
					event.preventDefault();
					void addFiles(event.dataTransfer.files);
				}}
			>
				<div class="flex items-center justify-between gap-2">
					<div class="text-sm font-semibold text-gray-900 dark:text-gray-100">想要什么样的视频</div>
					{#if idea.trim()}
						<button
							type="button"
							class="h-8 shrink-0 rounded-full px-2.5 text-xs text-gray-500 transition hover:bg-gray-100 hover:text-gray-800 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
							on:click={() => {
								idea = '';
								ideaBox?.focus();
							}}>清空</button
						>
					{/if}
				</div>
				<textarea
					bind:this={ideaBox}
					bind:value={idea}
					rows="7"
					on:keydown={onKeydown}
					on:paste={(event) => {
						const files = Array.from(event.clipboardData?.files ?? []);
						if (!files.length) return;
						event.preventDefault();
						void addFiles(files);
					}}
					placeholder="主题、给谁看、想传达什么、喜欢的风格……例如：用 60 秒讲清楚 HTTPS 是怎么保护网页的，深色科技风，适合发朋友圈"
					class="min-h-[9rem] max-h-[60vh] w-full resize-y rounded-xl border border-gray-200/60 bg-white/85 p-3 text-base leading-6 text-gray-900 outline-none placeholder:text-gray-400 sm:text-sm dark:border-gray-700/50 dark:bg-gray-900/70 dark:text-gray-100 dark:placeholder:text-gray-500"
					data-video-idea
				/>

				<div class="flex flex-wrap items-center gap-2" data-video-attachments>
					{#each attachments as item (item.key)}
						<div class="relative shrink-0" title={item.name}>
							{#if item.kind === 'image' && item.preview}
								<img src={item.preview} alt={item.name} class="size-14 rounded-xl object-cover ring-1 ring-gray-200/70 dark:ring-white/10" />
							{:else}
								<div class="flex h-14 w-24 flex-col items-center justify-center gap-0.5 rounded-xl bg-gray-100 px-1.5 text-gray-500 ring-1 ring-gray-200/70 dark:bg-gray-800 dark:text-gray-400 dark:ring-white/10">
									<span class="text-[10px] font-semibold uppercase tracking-wide">{item.kind === 'video' ? '视频' : item.kind === 'audio' ? '音频' : '文件'}</span>
									<span class="w-full truncate text-center text-[10px]">{item.name}</span>
								</div>
							{/if}
							{#if item.uploading}
								<UploadProgress progress={item.progress} className="absolute inset-0 rounded-xl bg-black/50 text-white pointer-events-none" ringClassName="size-9" />
							{/if}
							<button
								type="button"
								class="absolute -right-1.5 -top-1.5 rounded-full bg-gray-900 p-0.5 text-white shadow ring-2 ring-white transition hover:bg-gray-700 dark:bg-gray-100 dark:text-gray-900 dark:ring-gray-900"
								aria-label="移除 {item.name}"
								on:click={() => removeAttachment(item)}
							>
								<XMark className="size-3" strokeWidth="2.5" />
							</button>
						</div>
					{/each}
					{#if attachments.length < MAX_ATTACHMENTS}
						<button
							type="button"
							class="inline-flex items-center gap-1.5 rounded-full border border-dashed border-gray-300 px-3 py-1.5 text-xs text-gray-600 transition hover:border-gray-400 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
							on:click={() => fileInput?.click()}
							data-video-add-file
						>
							<span aria-hidden="true">＋</span> 添加参考附件
						</button>
					{/if}
					<span class="text-xs text-gray-500 dark:text-gray-400">
						{uploading ? '上传中…' : attachments.length ? '执行者会先看这些再动手' : '可选 · 图片、视频素材、配乐、脚本文档，可粘贴或拖进来'}
					</span>
					<input
						bind:this={fileInput}
						type="file"
						multiple
						hidden
						on:change={(event) => {
							const input = event.currentTarget;
							void addFiles(input.files);
							input.value = '';
						}}
					/>
				</div>

				<div class="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
					<span class="text-xs text-gray-500 dark:text-gray-400" data-video-blocked={blocked || undefined}>
						{blocked || `交给 ${maker.label} · ${recipe.label} · 约 ${settings.seconds} 秒，在新对话里制作`}
					</span>
					<button type="submit" class="workspace-primary-button w-full sm:w-auto sm:min-w-32" disabled={!!blocked} title={blocked} data-video-start>
						<SidebarModeIcon mode="video" className="size-4" />
						<span>开始制作</span>
					</button>
				</div>
			</div>

			{#if videos.length}
				<div class="glass-item p-4 space-y-3" data-video-recent>
					<div class="flex items-center justify-between">
						<div class="text-sm font-semibold text-gray-900 dark:text-gray-100">最近做好的</div>
						<button type="button" class="text-xs text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200" on:click={() => setTab('library')}>全部视频 →</button>
					</div>
					<div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
						{#each videos.slice(0, 3) as video (video.id)}
							<button type="button" class="group min-w-0 text-left" on:click={() => play(video)}>
								<div class="relative aspect-video overflow-hidden rounded-lg bg-gray-900">
									<!-- svelte-ignore a11y-media-has-caption -->
									<!-- svelte-ignore a11y-media-has-caption -->
							<video use:nearScreen={video.url} class="size-full object-cover" muted playsinline preload="metadata" />
									<span class="absolute inset-0 grid place-items-center bg-black/10 opacity-80 transition group-hover:bg-black/25">
										<span class="grid size-8 place-items-center rounded-full bg-white/90 text-gray-900 shadow">▶</span>
									</span>
								</div>
								<div class="mt-1 truncate text-xs text-gray-600 dark:text-gray-300">{videoTitle(video)}</div>
							</button>
						{/each}
					</div>
				</div>
			{/if}
		</section>

		<section class="flex min-w-0 flex-col gap-4">
			<div class="glass-item p-4 space-y-4" data-video-settings>
				<div class="space-y-2">
					<div class="text-sm font-semibold text-gray-900 dark:text-gray-100">做法</div>
					<div class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-2 xl:grid-cols-3">
						{#each VIDEO_RECIPES as r (r.key)}
							<button
								type="button"
								class="rounded-xl border px-3 py-2 text-left transition {settings.recipe === r.key
									? 'border-gray-900 bg-gray-900 text-white dark:border-white dark:bg-white dark:text-gray-900'
									: 'border-gray-200/70 bg-white/70 text-gray-700 hover:border-gray-300 dark:border-gray-700/60 dark:bg-white/[0.03] dark:text-gray-200 dark:hover:border-gray-600'}"
								aria-pressed={settings.recipe === r.key}
								on:click={() => (settings = { ...settings, recipe: r.key })}
								data-video-recipe={r.key}
							>
								<div class="text-sm font-medium">{r.label}</div>
								<div class="text-[11px] opacity-70">{r.sub}</div>
							</button>
						{/each}
					</div>
					<p class="text-xs leading-relaxed text-gray-500 dark:text-gray-400">{recipe.hint}</p>
				</div>

				<div class="grid gap-4 sm:grid-cols-2">
					<div class="space-y-1.5">
						<div class="text-xs font-medium text-gray-500 dark:text-gray-400">画幅</div>
						<div class="flex flex-wrap gap-1.5">
							{#each VIDEO_FRAMES as f (f.key)}
								<button type="button" class={settings.frame === f.key ? chipOn : chip} on:click={() => (settings = { ...settings, frame: f.key })} title={f.size} data-video-frame={f.key}>
									{f.label} {f.key}
								</button>
							{/each}
						</div>
					</div>
					<div class="space-y-1.5">
						<div class="text-xs font-medium text-gray-500 dark:text-gray-400">时长</div>
						<div class="flex flex-wrap gap-1.5">
							{#each VIDEO_LENGTHS as s}
								<button type="button" class={settings.seconds === s ? chipOn : chip} on:click={() => (settings = { ...settings, seconds: s })} data-video-length={s}>
									{s >= 60 ? `${s / 60} 分钟` : `${s} 秒`}
								</button>
							{/each}
						</div>
					</div>
					<div class="space-y-1.5">
						<div class="text-xs font-medium text-gray-500 dark:text-gray-400">配音</div>
						<div class="flex flex-wrap gap-1.5">
							{#each VIDEO_VOICES as v (v.key)}
								<button type="button" class={settings.voice === v.key ? chipOn : chip} on:click={() => (settings = { ...settings, voice: v.key })} data-video-voice={v.key || 'none'}>
									{v.label}
								</button>
							{/each}
						</div>
					</div>
					<div class="space-y-1.5">
						<div class="text-xs font-medium text-gray-500 dark:text-gray-400">字幕</div>
						<div class="flex flex-wrap gap-1.5">
							<button type="button" class={settings.subtitles ? chipOn : chip} on:click={() => (settings = { ...settings, subtitles: true })}>烧录字幕</button>
							<button type="button" class={!settings.subtitles ? chipOn : chip} on:click={() => (settings = { ...settings, subtitles: false })}>不要字幕</button>
						</div>
					</div>
				</div>

				<div class="space-y-2">
					<div class="text-xs font-medium text-gray-500 dark:text-gray-400">谁来做</div>
					<div class="grid grid-cols-3 gap-1.5 sm:grid-cols-4 lg:grid-cols-3 xl:grid-cols-4">
						{#each VIDEO_MAKERS as m (m.key)}
							<button
								type="button"
								class="min-w-0 rounded-xl border px-2 py-1.5 text-left transition {settings.maker === m.key
									? 'border-gray-900 bg-gray-900 text-white dark:border-white dark:bg-white dark:text-gray-900'
									: 'border-gray-200/70 bg-white/70 text-gray-700 hover:border-gray-300 dark:border-gray-700/60 dark:bg-white/[0.03] dark:text-gray-200 dark:hover:border-gray-600'}"
								aria-pressed={settings.maker === m.key}
								on:click={() => (settings = { ...settings, maker: m.key })}
								data-video-maker={m.key || 'hermes'}
							>
								<div class="truncate text-xs font-semibold">{m.label}</div>
								<div class="truncate text-[10.5px] opacity-70">{m.sub}</div>
							</button>
						{/each}
					</div>
					<p class="text-xs leading-relaxed text-gray-500 dark:text-gray-400">
						{settings.maker
							? `消息前加 /${settings.maker}，由 ${maker.label} 在后台独占制作，做完把成片和报告发回对话。`
							: 'Hermes 自己用视频技能制作，过程和成片都在对话里。'}
					</p>
				</div>
			</div>

			<details class="glass-item p-4 group" data-video-brief>
				<summary class="cursor-pointer select-none text-sm font-semibold text-gray-900 dark:text-gray-100">
					发出去的需求
					<span class="ml-1 text-xs font-normal text-gray-500 dark:text-gray-400">（按上面的选择自动写好）</span>
				</summary>
				<pre class="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-gray-50 p-3 text-xs leading-relaxed text-gray-700 dark:bg-gray-900/70 dark:text-gray-300">{brief}</pre>
			</details>
		</section>
	</form>
{:else}
	<div class="workspace-section space-y-4" data-video-library>
		<div class="flex flex-wrap items-center justify-between gap-2">
			<div class="text-lg font-semibold text-gray-900 dark:text-gray-100">视频库</div>
			<div class="text-xs text-gray-500 dark:text-gray-400">Hermes 对话和 runner 报告交付的视频都会自动收进来</div>
		</div>
		<div class="workspace-search">
			<svg class="size-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"
				><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg
			>
			<input bind:value={query} placeholder="按文件名搜索…" class="flex-1 bg-transparent text-sm outline-none" data-video-search />
		</div>

		{#if videos.length}
			<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-video-grid>
				{#each videos as video (video.id)}
					<div class="glass-item group p-1.5" data-video-card={video.id}>
						<button type="button" class="relative block aspect-video w-full overflow-hidden rounded-lg bg-gray-900" on:click={() => play(video)} aria-label="播放 {videoTitle(video)}">
							<video use:nearScreen={video.url} class="size-full object-cover" muted playsinline preload="metadata" />
							<span class="absolute inset-0 grid place-items-center bg-black/10 transition group-hover:bg-black/25">
								<span class="grid size-10 place-items-center rounded-full bg-white/90 text-gray-900 shadow-lg transition group-hover:scale-105">▶</span>
							</span>
							<span class="absolute left-2 top-2 rounded-full bg-black/55 px-2 py-0.5 text-[10.5px] font-medium text-white backdrop-blur">
								{video.origin === 'runner' ? 'runner' : 'Hermes'}
							</span>
						</button>
						<div class="space-y-1 p-2">
							<div class="line-clamp-2 text-sm font-medium text-gray-800 dark:text-gray-100" title={video.name}>{videoTitle(video)}</div>
							<div class="flex items-center justify-between gap-2 text-xs text-gray-500">
								<span class="truncate">{dateLabel(video.createdAt)}{video.size ? ` · ${formatFileSize(video.size)}` : ''}</span>
								<span class="flex shrink-0 items-center gap-0.5">
									{#if video.chatId}
										<a href="/c/{encodeURIComponent(video.chatId)}" class="rounded-full px-2 py-0.5 hover:bg-gray-100 hover:text-gray-800 dark:hover:bg-gray-800 dark:hover:text-gray-200" title="打开做这个视频的对话" data-video-chat>对话</a>
									{/if}
									<a href={video.url} download={video.name} class="rounded-lg p-1 hover:bg-gray-100 hover:text-gray-800 dark:hover:bg-gray-800 dark:hover:text-gray-200" aria-label="下载" title="下载 {video.name}">
										<ArrowDownTray className="size-3.5" />
									</a>
									<button type="button" class="rounded-lg p-1 hover:bg-gray-100 hover:text-red-600 dark:hover:bg-gray-800 dark:hover:text-red-400" aria-label="从视频库移除" title="从视频库移除（对话里的视频还在）" on:click={() => remove(video)} data-video-delete={video.id}>
										<GarbageBin className="size-3.5" />
									</button>
								</span>
							</div>
						</div>
					</div>
				{/each}
			</div>
			<LoadMore more={!!next} loading={loadingMore} onMore={loadMore} shown={videos.length} />
		{:else}
			<div class="workspace-empty-state">
				<div class="mx-auto flex size-14 items-center justify-center rounded-2xl bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500">
					<SidebarModeIcon mode="video" className="size-7" />
				</div>
				<div class="mt-4 text-base font-semibold text-gray-900 dark:text-gray-100">
					{!libraryLoaded ? '正在读取…' : asked ? '没有找到匹配的视频' : '还没有视频'}
				</div>
				<div class="mt-2 text-sm text-gray-500 dark:text-gray-400">
					{asked ? '换个关键词试试' : '在工作台交给 Hermes 或 runner 做一个，或者在对话里让它们做；交付的视频会自动出现在这里。'}
				</div>
				{#if libraryLoaded && !asked}
					<button type="button" class="workspace-secondary-button mt-5 text-xs" on:click={() => setTab('workbench')}>去工作台</button>
				{/if}
			</div>
		{/if}
	</div>
{/if}

{#if playing}
	<Modal bind:show={playerOpen} size="3xl">
		<div class="space-y-3 p-1" data-video-player>
			<div class="flex items-center justify-between gap-2 px-1">
				<div class="min-w-0 truncate text-sm font-semibold text-gray-900 dark:text-gray-100">{videoTitle(playing)}</div>
				<button type="button" class="rounded-lg p-1 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800" aria-label="关闭" on:click={() => (playerOpen = false)}>
					<XMark className="size-4" />
				</button>
			</div>
			<!-- svelte-ignore a11y-media-has-caption -->
			<video src={playing.url} controls autoplay playsinline class="max-h-[70vh] w-full rounded-xl bg-black" />
			<div class="flex flex-wrap items-center justify-between gap-2 px-1 text-xs text-gray-500">
				<span>{playing.name}{playing.size ? ` · ${formatFileSize(playing.size)}` : ''} · {dateLabel(playing.createdAt)}</span>
				<span class="flex items-center gap-2">
					{#if playing.chatId}
						<a class="workspace-secondary-button text-xs" href="/c/{encodeURIComponent(playing.chatId)}">打开对话</a>
					{/if}
					<a class="workspace-secondary-button text-xs" href={playing.url} download={playing.name}>下载</a>
				</span>
			</div>
		</div>
	</Modal>
{/if}
