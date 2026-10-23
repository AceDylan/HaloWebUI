<script lang="ts">
	/**
	 * 视频工作台 (/workspace/videos). The workbench writes a brief — what you want, how it should be
	 * made (做法), frame, length, narration, subtitles, reference files — and starts it from here
	 * (backend utils/video_tasks.py): the server opens a new Hermes chat with the brief and starts
	 * its turn, Hermes itself or a runner (codex, reclaude …, by the command in front) makes the
	 * video with its video-studio skill and hands it over as MEDIA. The workbench stays: its 制作任务
	 * list follows each video to the end (and plays it) and leads to the chat, which shows the same
	 * task as a card on its reply (?task=<chat id> leads back here). Every video a reply or a
	 * runner's report hands over lands in the library (backend utils/video_library.py), which
	 * comes a page at a time and loads each player only when it scrolls into view.
	 *
	 * 背景音乐: the user's own MP3 (uploaded here or picked again from their earlier uploads) is
	 * decided before the video: the brief has the maker plan to its length and beats and prove
	 * the finished file plays it (video-brief.ts).
	 *
	 * 提示词增强 (utils/studio-prep.ts): gpt-chat reads the request — looks facts up on the web, or
	 * asks 精答 / 讨论 first when the content needs working out, and waits for the answer — and
	 * rewrites it. 开始制作 does not wait for it: the job starts on the server and the brief goes out
	 * at once with its number; the chat's Hermes turn waits for it there (its steps are the reply's
	 * status) and puts the result in the brief, so the page can be left. ✨ 增强 runs it here instead,
	 * to read the result first.
	 */
	import { afterUpdate, onDestroy, onMount, tick } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { replaceState } from '$app/navigation';

	import { config, models } from '$lib/stores';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import { ensureModels } from '$lib/services/models';
	import {
		deleteLibraryVideo,
		getMusicFiles,
		getVideoPage,
		getVideoTask,
		getVideoTasks,
		startVideoTask,
		stopVideoTask,
		videoTaskLive,
		type LibraryVideo,
		type MusicFile,
		type VideoTask
	} from '$lib/apis/video-studio';
	import { uploadFileReliably } from '$lib/utils/reliable-upload';
	import { isHermesAgentModel } from '$lib/utils/hermes';
	import { formatFileSize } from '$lib/utils';
	import { HANDOFF_TEXT_MAX, takeHandoff, type HandoffOrigin } from '$lib/utils/handoff';
	import {
		cancelStudioPrep,
		getStudioPrep,
		startStudioPrep,
		type StudioPrepJob,
		type StudioPrepResult
	} from '$lib/apis/studio-prep';
	import { normalizePrepOptions, prepErrorText, waitForPrep, type PrepOptions } from '$lib/utils/studio-prep';
	import {
		VIDEO_FRAMES,
		VIDEO_LENGTHS,
		VIDEO_MAKERS,
		VIDEO_RECIPES,
		VIDEO_VOICES,
		MUSIC_MAX_SECONDS,
		attachmentKind,
		clockLabel,
		fitVideoBrief,
		musicFileProblem,
		musicSetsLength,
		normalizeVideoSettings,
		videoSettingsText,
		videoPrepIdea,
		type VideoSettings
	} from '$lib/utils/video-brief';
	import { clearModeDraft, setModeDraft } from '$lib/components/scifi/mode-relay';
	import VideoStylePicker from './VideoStylePicker.svelte';
	import VideoTaskCard from './VideoTaskCard.svelte';
	import HandoffBack from '$lib/components/common/HandoffBack.svelte';
	import LoadMore from '$lib/components/common/LoadMore.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import UploadProgress from '$lib/components/common/UploadProgress.svelte';
	import StudioPrepPanel from '$lib/components/common/StudioPrepPanel.svelte';
	import Sparkles from '$lib/components/icons/Sparkles.svelte';
	import SidebarModeIcon from '$lib/components/layout/Sidebar/SidebarModeIcon.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import ArrowDownTray from '$lib/components/icons/ArrowDownTray.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	const SETTINGS_KEY = 'halo.videoStudio.settings';
	const PREP_KEY = 'halo.videoStudio.prep';
	// the enhancement going on in this tab, read again after a visit elsewhere
	const PREP_JOB_KEY = 'halo.videoStudio.prepJob';
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

	// ---- background music: the user's MP3, chosen before the video is made ----------------------
	type Music = {
		id: string;
		name: string;
		size: number;
		seconds: number | null;
		url: string;
		uploading?: boolean;
		progress?: number;
	};
	let music: Music | null = null;
	let musicInput: HTMLInputElement;
	let recentMusic: MusicFile[] = [];

	// ---- 提示词增强 ------------------------------------------------------------------------------
	let prepOptions: PrepOptions = normalizePrepOptions(null);
	let prepJob: StudioPrepJob | null = null;
	// the last enhancement while its text is in the box: what it brought, the words before it
	let prepared: { result: StudioPrepResult; original: string; model: string; fingerprint: string } | null = null;
	let prepStarting = false;
	let destroyed = false;
	$: preparing = prepStarting || prepJob?.status === 'running';
	$: if (prepared && !idea.trim()) prepared = null;
	// a newer pick wins over an older upload or length reading still going
	let musicPick = 0;
	const fileUrl = (id: string) => `${WEBUI_API_BASE_URL}/files/${encodeURIComponent(id)}/content`;

	$: hermes = (($models ?? []) as any[]).find((m) => isHermesAgentModel(m, $config?.hermes_agent_model_ids)) ?? null;
	let modelsChecked = false;
	$: uploading = attachments.some((a) => a.uploading);
	$: musicReady = music && !music.uploading && music.id ? music : null;
	// the music is listed as music, not again as an attachment (a file handed over from a chat)
	$: ready = attachments.filter((a) => !a.uploading && a.id && a.id !== musicReady?.id);
	$: musicTooLong = !!music?.seconds && music.seconds > MUSIC_MAX_SECONDS;
	$: followsMusic = musicSetsLength(music, settings.musicFit);
	$: prepSettings = {
		...settings,
		attachments: ready.map((a) => ({ name: a.name, kind: a.kind })),
		music: musicReady ? { name: musicReady.name, seconds: musicReady.seconds } : null
	};
	$: prepFingerprint = JSON.stringify([videoSettingsText(prepSettings), ready.map((a) => a.id), musicReady?.id]);
	$: prepStale = !!prepared && prepared.fingerprint !== prepFingerprint;
	$: hasReference = ready.some((a) => a.kind === 'image' || a.kind === 'video');
	$: styleProblem = settings.style === 'reference' && !hasReference
		? '请先添加参考图片或视频'
		: settings.style === 'custom' && !settings.customStyle.trim() ? '请先填写自定义风格' : '';
	$: briefOptions = {
		...prepSettings,
		prep: prepared
			? {
					original: prepared.original,
					stale: prepStale,
					notes: prepared.result.notes,
					sources: prepared.result.sources,
					run: prepared.result.run ?? null
				}
			: null
	};
	$: brief = fitVideoBrief({ ...briefOptions, idea: idea.trim() || '（在左边写下想要的视频）' }, HANDOFF_TEXT_MAX);
	$: sentFiles = [
		...ready.map((a) => ({ id: a.id, name: a.name, type: a.kind === 'image' ? 'image' : 'file' })),
		...(musicReady ? [{ id: musicReady.id, name: musicReady.name, type: 'file' }] : [])
	];
	$: lengthSummary = followsMusic
		? `跟音乐${music?.seconds ? ` ${clockLabel(music.seconds)}` : ''}`
		: `约 ${settings.seconds} 秒`;
	$: recipe = VIDEO_RECIPES.find((r) => r.key === settings.recipe) ?? VIDEO_RECIPES[0];
	$: maker = VIDEO_MAKERS.find((m) => m.key === settings.maker) ?? VIDEO_MAKERS[0];
	$: blocked = !hermes
		? modelsChecked
			? '没有可用的 Hermes 模型：视频由 Hermes 或 runner 制作'
			: '正在读取模型…'
		: preparing
			? '正在增强需求…'
		: uploading
			? '附件还在上传'
			: music?.uploading
				? '背景音乐还在上传'
				: !idea.trim()
				? '先写下想要的视频'
				: styleProblem || (brief.length > HANDOFF_TEXT_MAX ? '需求较长，请精简后再制作' : '');

	const saveSettings = () => {
		try {
			localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
		} catch {
			/* private mode: the choices just are not remembered */
		}
	};

	const setPrepOption = (patch: Partial<PrepOptions>) => {
		prepOptions = { ...prepOptions, ...patch };
		try {
			localStorage.setItem(PREP_KEY, JSON.stringify(prepOptions));
		} catch {
			/* not remembered */
		}
	};

	const rememberJob = (id: string | null, original = '', fingerprint = '') => {
		try {
			if (id) sessionStorage.setItem(PREP_JOB_KEY, JSON.stringify({ id, original, fingerprint }));
			else sessionStorage.removeItem(PREP_JOB_KEY);
		} catch {
			/* not resumed after a visit elsewhere */
		}
	};

	/** The job read until it ends; its text into the box when it is done. Returns how it ended
	 * ('stopped': cancelled here, or the page went away). */
	const followPrep = async (job: StudioPrepJob, original: string, fingerprint: string): Promise<'done' | 'failed' | 'stopped'> => {
		prepJob = job;
		const ended = await waitForPrep(localStorage.token, job, {
			onUpdate: (current) => {
				if (prepJob?.id === job.id) prepJob = current;
			},
			stopped: () => destroyed || prepJob?.id !== job.id
		});
		if (destroyed) return 'stopped';
		rememberJob(null);
		if (prepJob?.id !== job.id || ended.status === 'cancelled') return 'stopped';
		if (ended.status === 'done' && ended.result) {
			prepared = { result: ended.result, original, model: ended.model, fingerprint };
			idea = ended.result.idea;
			prepJob = null;
			return 'done';
		}
		prepJob = ended;
		return 'failed';
	};

	const runPrep = async (): Promise<'done' | 'failed' | 'stopped'> => {
		const original = prepared?.original || idea.trim();
		const requestIdea = videoPrepIdea(idea, briefOptions.prep);
		if (requestIdea.length > 6000) { toast.error('需求较长，请精简后再增强'); return 'failed'; }
		const fingerprint = prepFingerprint;
		let job: StudioPrepJob;
		prepStarting = true;
		try {
			job = await startStudioPrep(localStorage.token, {
				kind: 'video',
				idea: requestIdea,
				settings: videoSettingsText(briefOptions),
				research: prepOptions.research,
				deeper: prepOptions.deeper
			});
		} catch (error) {
			prepJob = { id: '', kind: 'video', status: 'error', idea: original, steps: [], run: null, result: null, error: prepErrorText(error), model: '', createdAt: Date.now() };
			return 'failed';
		} finally {
			prepStarting = false;
		}
		rememberJob(job.id, original, fingerprint);
		return followPrep(job, original, fingerprint);
	};

	/** ✨ 增强: the enhanced request into the box, to read and change before 开始制作. */
	const enhance = async () => {
		if (preparing || starting || !idea.trim()) return;
		if (styleProblem) { toast.error(styleProblem); return; }
		if ((await runPrep()) === 'failed' && prepJob?.error) toast.error(prepJob.error);
	};

	const cancelPrep = () => {
		const job = prepJob;
		prepJob = null;
		rememberJob(null);
		if (job?.id) void cancelStudioPrep(localStorage.token, job.id).catch(() => {});
	};

	const undoPrep = () => {
		if (!prepared) return;
		idea = prepared.original;
		prepared = null;
		ideaBox?.focus();
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

	/** Whether the browser can play *src*, and its length when it says. */
	const readAudio = (src: string, ms = 15_000): Promise<{ playable: boolean; seconds: number | null }> =>
		new Promise((resolve) => {
			if (typeof Audio === 'undefined') return resolve({ playable: true, seconds: null });
			const audio = new Audio();
			const done = (playable: boolean) => {
				clearTimeout(timer);
				const seconds = playable && Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : null;
				audio.removeAttribute('src');
				resolve({ playable, seconds });
			};
			const timer = setTimeout(() => done(false), ms);
			audio.preload = 'metadata';
			audio.onloadedmetadata = () => done(true);
			audio.onerror = () => done(false);
			audio.src = src;
		});

	const dropMusic = () => {
		musicPick += 1;
		if (music?.url.startsWith('blob:')) URL.revokeObjectURL(music.url);
		music = null;
	};

	/** A new MP3 from the computer: checked (MP3 by name, type and first bytes, ≤ 50 MB, plays in
	 * the browser), then uploaded as is for Hermes to read on the host. */
	const uploadMusic = async (file: File | null | undefined) => {
		if (!file) return;
		const head = new Uint8Array(await file.slice(0, 4).arrayBuffer().catch(() => new ArrayBuffer(0)));
		const problem = musicFileProblem(file, head);
		if (problem) {
			toast.error(problem);
			return;
		}
		const local = URL.createObjectURL(file);
		const { playable, seconds } = await readAudio(local);
		if (!playable) {
			URL.revokeObjectURL(local);
			toast.error(`「${file.name}」放不出来，换一个 MP3 试试`);
			return;
		}
		dropMusic();
		const pick = musicPick;
		const item: Music = { id: '', name: file.name, size: file.size, seconds, url: local, uploading: true, progress: 0 };
		music = item;
		try {
			const { file: stored } = await uploadFileReliably(localStorage.token, file, {
				process: false,
				onProgress: ({ percent }) => {
					if (pick !== musicPick || item.progress === percent) return;
					item.progress = percent;
					music = item;
				}
			});
			if (!stored?.id) throw new Error('upload failed');
			if (pick !== musicPick) return; // removed or replaced meanwhile
			item.id = stored.id;
			item.uploading = false;
			delete item.progress;
			music = item;
			recentMusic = [
				{ id: stored.id, name: file.name, size: file.size, createdAt: Date.now() },
				...recentMusic.filter((m) => m.id !== stored.id)
			];
		} catch (error) {
			console.warn('video studio music upload failed', error);
			if (pick !== musicPick) return;
			dropMusic();
			toast.error(`「${file.name}」上传失败`);
		}
	};

	/** An MP3 uploaded before. */
	const pickMusic = async (picked: MusicFile) => {
		dropMusic();
		const pick = musicPick;
		const item: Music = { id: picked.id, name: picked.name, size: picked.size, seconds: null, url: fileUrl(picked.id) };
		music = item;
		const { playable, seconds } = await readAudio(item.url);
		if (pick !== musicPick) return;
		if (!playable) {
			music = null;
			toast.error(`「${picked.name}」读不出来，换一首或重新上传`);
			return;
		}
		item.seconds = seconds;
		music = item;
	};

	const setLength = (seconds: number) => {
		// with music, a length means: cut the music to it
		settings = { ...settings, seconds, ...(music ? { musicFit: 'trim' as const } : {}) };
	};

	const removeAttachment = (item: Attachment) => {
		if (item.preview) URL.revokeObjectURL(item.preview);
		// The file stays on the server: it may have come from a chat (a handoff), and an upload
		// left behind costs little.
		attachments = attachments.filter((a) => a !== item);
	};

	let starting = false;
	const start = async () => {
		if (blocked || !hermes || starting) return;
		saveSettings();
		// Capture one request: edits while the start call is in flight belong to the next video.
		const snapshot = { ...briefOptions, idea };
		const snapshotFiles = sentFiles;
		const needsPrep = prepOptions.enhance && (!prepared || prepStale);
		const requestIdea = videoPrepIdea(idea, snapshot.prep);
		if (needsPrep && requestIdea.length > 6000) { toast.error('需求较长，请精简后再增强'); return; }
		if (fitVideoBrief({ ...snapshot, prepJob: needsPrep ? 'a'.repeat(32) : null }, HANDOFF_TEXT_MAX).length > HANDOFF_TEXT_MAX) {
			toast.error('需求较长，请精简后再制作'); return;
		}
		starting = true;
		try {
			// the enhancement starts on the server and the brief goes out at once: the chat's turn
			// waits for it (nobody has to stay here); the video is made from the words as written
			// when it fails
			let prepJobId: string | null = null;
			if (needsPrep) {
				try {
					prepJobId = (
						await startStudioPrep(localStorage.token, {
							kind: 'video',
							idea: requestIdea,
							settings: videoSettingsText(snapshot),
							research: prepOptions.research,
							deeper: prepOptions.deeper
						})
					).id;
				} catch (error) {
					toast.warning(`${prepErrorText(error)}，按原文制作`);
				}
			}
			// the chat is written and its Hermes turn started on the server: the video is followed
			// here (制作任务) and in the chat alike
			const task = await startVideoTask(localStorage.token, {
				brief: fitVideoBrief({ ...snapshot, prepJob: prepJobId }, HANDOFF_TEXT_MAX),
				idea: (snapshot.prep?.original || snapshot.idea).trim(),
				files: snapshotFiles,
				maker: snapshot.maker
			});
			if (destroyed) return;
			tasks = [task, ...tasks.filter((t) => t.chatId !== task.chatId)];
			watchTasks();
			// what was started is in the list now: the box is free for the next video (the
			// settings and the music stay)
			if (idea === snapshot.idea) {
				idea = '';
				prepared = null;
			}
			const sentIds = new Set(snapshotFiles.map((f) => f.id));
			attachments.forEach((a) => sentIds.has(a.id) && a.preview?.startsWith('blob:') && URL.revokeObjectURL(a.preview));
			attachments = attachments.filter((a) => !sentIds.has(a.id));
			toast.success('已开始制作：进度在「制作任务」里，也可以打开对话看');
			await tick();
			document
				.querySelector(`[data-video-task="${task.chatId}"]`)
				?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
		} catch (error) {
			toast.error(`没能开始制作：${(error as any)?.detail ?? (error as Error)?.message ?? error}`);
		} finally {
			starting = false;
		}
	};

	// ---- 制作任务: the videos started here, followed to the end -----------------------------------
	const TASKS_SHOWN = 6;
	let tasks: VideoTask[] = [];
	let tasksTimer: ReturnType<typeof setTimeout> | null = null;
	let stoppingTask = '';
	// ?task=<chat id>: the chat's card led here; that task is shown with a ring
	let focusTask = '';
	let showTaskHistory = false;
	// Keep work that needs attention visible; finished tasks remain available on demand.
	$: historyTasks = tasks.filter(
		(t) => (t.state === 'done' || t.state === 'stopped') && t.chatId !== focusTask
	);
	$: visibleTasks = tasks.filter((t) => !historyTasks.includes(t));

	const watchTasks = () => {
		if (tasksTimer) clearTimeout(tasksTimer);
		tasksTimer = null;
		if (destroyed || !tasks.some(videoTaskLive)) return;
		const hidden = typeof document !== 'undefined' && document.visibilityState === 'hidden';
		const quiet = !tasks.some((t) => t.state === 'running'); // only runners at work: slower
		tasksTimer = setTimeout(loadTasks, hidden ? 30000 : quiet ? 10000 : 3000);
	};

	const loadTasks = async () => {
		try {
			const list = await getVideoTasks(localStorage.token, TASKS_SHOWN);
			// the task the chat led to stays in view even when it is older than the list
			const focused =
				focusTask && !list.some((t) => t.chatId === focusTask)
					? await getVideoTask(localStorage.token, focusTask).catch(() => null)
					: null;
			if (destroyed) return;
			const finished = list.filter((t) => t.state === 'done' && tasks.some((o) => o.chatId === t.chatId && o.state !== 'done'));
			tasks = focused ? [...list, focused] : list;
			// a video that just came in belongs in the library too
			if (finished.length && libraryLoaded) void loadFirst();
		} catch (error) {
			console.warn('video tasks unavailable', error);
		}
		watchTasks();
	};

	const stopTask = async (task: VideoTask) => {
		if (stoppingTask) return;
		stoppingTask = task.chatId;
		try {
			const stopped = await stopVideoTask(localStorage.token, task.chatId);
			tasks = tasks.map((t) => (t.chatId === stopped.chatId ? stopped : t));
		} catch (error) {
			toast.error(`${(error as any)?.detail ?? (error as Error)?.message ?? error}`);
		} finally {
			stoppingTask = '';
		}
		watchTasks();
	};

	// back on this tab: read again while anything is still being made
	const onVisibility = () => {
		if (document.visibilityState === 'visible' && tasks.some(videoTaskLive)) void loadTasks();
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

	const videoTitle = (video: LibraryVideo) => video.chatTitle || video.runTitle || video.title || video.name;
	// Who made it: the runner's name for a run (codex, officlaude …), Hermes for its own reply.
	const makerLabel = (video: LibraryVideo) =>
		video.origin === 'runner' ? video.runner || 'runner' : 'Hermes';
	const PLATFORM_LABEL: Record<string, string> = { telegram: 'Telegram', api_server: 'HaloWebUI' };
	// A run started elsewhere (Telegram) has no chat here: where it was asked for, and which run.
	const runSource = (video: LibraryVideo) =>
		video.chatId || !video.runId ? '' : PLATFORM_LABEL[video.platform ?? ''] ?? video.platform ?? '';
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
		try {
			prepOptions = normalizePrepOptions(JSON.parse(localStorage.getItem(PREP_KEY) ?? 'null'));
		} catch {
			prepOptions = normalizePrepOptions(null);
		}
		const landing = new URL(window.location.href).searchParams;
		if (landing.get('tab') === 'library') tab = 'library';
		const asked = landing.get('task') ?? '';
		focusTask = /^[\w-]{1,128}$/.test(asked) ? asked : '';
		document.addEventListener('visibilitychange', onVisibility);
		void loadTasks().then(async () => {
			if (!focusTask || destroyed) return;
			await tick();
			document.querySelector(`[data-video-task="${focusTask}"]`)?.scrollIntoView?.({ block: 'center' });
		});

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
		} else {
			// an enhancement started here before a visit elsewhere: its result comes into the box
			// (the video is not started by itself: the attachments did not stay)
			void resumePrep();
		}

		void loadFirst();
		getMusicFiles(localStorage.token)
			.then((list) => (recentMusic = list))
			.catch((error) => console.warn('earlier music unavailable', error));
		if (($models ?? []).length === 0) await ensureModels(localStorage.token, { reason: 'video-studio' }).catch(() => {});
		modelsChecked = true;
		if (tab === 'workbench') ideaBox?.focus();
	});

	const resumePrep = async () => {
		let saved: { id?: string; original?: string; fingerprint?: string } | null = null;
		try {
			saved = JSON.parse(sessionStorage.getItem(PREP_JOB_KEY) ?? 'null');
		} catch {
			saved = null;
		}
		if (!saved?.id) return;
		try {
			const job = await getStudioPrep(localStorage.token, saved.id);
			if (!idea.trim()) idea = saved.original || job.idea;
			// a job saved without its settings snapshot is taken as made for the settings on screen
			await followPrep(job, saved.original || job.idea, saved.fingerprint || prepFingerprint);
		} catch {
			rememberJob(null);
		}
	};

	afterUpdate(() =>
		setModeDraft('video', idea, { from: origin, files: sentFiles })
	);
	onDestroy(() => {
		destroyed = true;
		if (tasksTimer) clearTimeout(tasksTimer);
		if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibility);
		clearModeDraft('video');
		if (searchTimer) clearTimeout(searchTimer);
		attachments.forEach((a) => a.preview?.startsWith('blob:') && URL.revokeObjectURL(a.preview));
		if (music?.url.startsWith('blob:')) URL.revokeObjectURL(music.url);
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
						<span class="flex shrink-0 items-center gap-1">
							<button
								type="button"
								class="inline-flex h-8 items-center gap-1 rounded-full px-2.5 text-xs text-gray-600 transition hover:bg-gray-100 hover:text-gray-900 disabled:opacity-50 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-white"
								disabled={preparing}
								title="用 gpt-chat 把需求写完整（需要时先联网查资料、先交给精答或讨论），改写后的需求放回这里"
								on:click={enhance}
								data-video-enhance
							>
								<Sparkles className="size-3.5" strokeWidth="2" />
								<span>{prepared ? '再增强' : '增强'}</span>
							</button>
							<button
								type="button"
								class="h-8 rounded-full px-2.5 text-xs text-gray-500 transition hover:bg-gray-100 hover:text-gray-800 disabled:opacity-50 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
								disabled={preparing}
								on:click={() => {
									idea = '';
									prepared = null;
									ideaBox?.focus();
								}}>清空</button
							>
						</span>
					{/if}
				</div>
				<textarea
					bind:this={ideaBox}
					bind:value={idea}
					readonly={preparing}
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

				{#if prepStale}
					<p class="text-xs text-amber-700 dark:text-amber-300" role="status" data-video-prep-stale>制作设置已变更，文字修改已保留。{prepOptions.enhance ? '开始制作时会按新设置重新增强。' : '自动增强已关闭，制作者将按新设置调整旧草稿；也可点“再增强”预览。'}</p>
				{/if}

				<StudioPrepPanel
					job={prepJob}
					result={prepared?.result ?? null}
					model={prepared?.model ?? ''}
					onCancel={cancelPrep}
					onUndo={undoPrep}
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
						{uploading ? '上传中…' : attachments.length ? '执行者会先看这些再动手' : '可选 · 图片、视频素材、脚本文档，可粘贴或拖进来（背景音乐在下面单独选）'}
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

			</div>

			<!-- svelte-ignore a11y-no-static-element-interactions -->
			<div
				class="glass-item p-4 space-y-3"
				data-video-music
				on:dragover={(event) => {
					if (event.dataTransfer?.types?.includes('Files')) event.preventDefault();
				}}
				on:drop={(event) => {
					if (!event.dataTransfer?.files?.length) return;
					event.preventDefault();
					void uploadMusic(event.dataTransfer.files[0]);
				}}
			>
				<div class="flex items-start justify-between gap-2">
					<div class="min-w-0">
						<div class="text-sm font-semibold text-gray-900 dark:text-gray-100">背景音乐</div>
						<div class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">可选 · 你先定音乐，视频跟着它的长度和节拍做</div>
					</div>
					{#if music}
						<span class="flex shrink-0 items-center gap-1">
							<button type="button" class="h-8 rounded-full px-2.5 text-xs text-gray-500 transition hover:bg-gray-100 hover:text-gray-800 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200" on:click={() => musicInput?.click()} data-video-music-replace>更换</button>
							<button type="button" class="h-8 rounded-full px-2.5 text-xs text-gray-500 transition hover:bg-gray-100 hover:text-red-600 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-red-400" on:click={dropMusic} data-video-music-remove>移除</button>
						</span>
					{/if}
				</div>

				{#if music}
					<div class="flex items-center gap-3 rounded-xl bg-gray-50 p-2.5 ring-1 ring-gray-200/70 dark:bg-gray-900/60 dark:ring-white/10" data-video-music-picked={music.id || 'uploading'}>
						<span class="relative grid size-10 shrink-0 place-items-center rounded-lg bg-gray-900 text-white dark:bg-white dark:text-gray-900" aria-hidden="true">
							<svg class="size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="18" cy="16" r="3" /></svg>
							{#if music.uploading}
								<UploadProgress progress={music.progress} className="absolute inset-0 rounded-lg bg-black/55 text-white pointer-events-none" ringClassName="size-8" />
							{/if}
						</span>
						<div class="min-w-0 flex-1">
							<div class="truncate text-sm font-medium text-gray-800 dark:text-gray-100" title={music.name}>{music.name}</div>
							<div class="text-xs text-gray-500 dark:text-gray-400">
								{music.seconds ? clockLabel(music.seconds) : '读取时长…'}{music.size ? ` · ${formatFileSize(music.size)}` : ''}{music.uploading ? ' · 上传中' : ''}
							</div>
						</div>
					</div>
					<!-- svelte-ignore a11y-media-has-caption -->
					<audio src={music.url} controls preload="metadata" class="h-9 w-full" data-video-music-player />
					<div class="flex flex-wrap gap-1.5">
						<button type="button" class={followsMusic ? chipOn : chip} disabled={musicTooLong} on:click={() => (settings = { ...settings, musicFit: 'full' })} data-video-music-fit="full">
							跟音乐一样长{music.seconds ? `（${clockLabel(music.seconds)}）` : ''}
						</button>
						<button type="button" class={!followsMusic ? chipOn : chip} on:click={() => (settings = { ...settings, musicFit: 'trim' })} data-video-music-fit="trim">
							截取到 {settings.seconds >= 60 ? `${settings.seconds / 60} 分钟` : `${settings.seconds} 秒`}
						</button>
					</div>
					<p class="text-xs leading-relaxed text-gray-500 dark:text-gray-400" data-video-music-hint>
						{musicTooLong
							? `音乐超过 ${MUSIC_MAX_SECONDS / 60} 分钟，按右边选的时长从开头截取`
							: followsMusic
								? '成片和这首音乐一样长，转场卡在节拍上；交付前核验成片里确实是这首音乐'
								: `成片约 ${settings.seconds} 秒，音乐从开头截取、结尾淡出${music.seconds && music.seconds < settings.seconds ? '；音乐比视频短，会循环' : ''}`}
					</p>
				{:else}
					<div class="flex flex-wrap items-center gap-2">
						<button
							type="button"
							class="inline-flex items-center gap-1.5 rounded-full border border-dashed border-gray-300 px-3 py-1.5 text-xs text-gray-600 transition hover:border-gray-400 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
							on:click={() => musicInput?.click()}
							data-video-music-upload
						>
							<span aria-hidden="true">＋</span> 上传 MP3
						</button>
						<span class="text-xs text-gray-500 dark:text-gray-400">MP3，最大 50 MB，可拖进来</span>
					</div>
					{#if recentMusic.length}
						<div class="space-y-1.5" data-video-music-recent>
							<div class="text-xs font-medium text-gray-500 dark:text-gray-400">用以前上传的</div>
							<div class="flex flex-wrap gap-1.5">
								{#each recentMusic.slice(0, 6) as m (m.id)}
									<button type="button" class="{chip} max-w-[14rem] truncate" title={m.name} on:click={() => pickMusic(m)} data-video-music-pick={m.id}>♪ {m.name}</button>
								{/each}
							</div>
						</div>
					{/if}
				{/if}
				<input
					bind:this={musicInput}
					type="file"
					accept=".mp3,audio/mpeg"
					hidden
					on:change={(event) => {
						const input = event.currentTarget;
						void uploadMusic(input.files?.[0]);
						input.value = '';
					}}
					data-video-music-input
				/>
			</div>

			<!-- after the music: the music is decided before the video is started -->
			<div class="flex flex-col-reverse gap-2 px-1 sm:flex-row sm:items-center sm:justify-between">
				<span class="text-xs text-gray-500 dark:text-gray-400" data-video-status data-video-blocked={blocked || undefined}>
					{blocked ||
						`交给 ${maker.label} · ${recipe.label} · ${lengthSummary}${musicReady ? ' · 配乐已定' : ''}，在这里${prepOptions.enhance && (!prepared || prepStale) ? '先增强需求再' : ''}制作，同时记成一个对话`}
				</span>
				<button type="submit" class="workspace-primary-button w-full sm:w-auto sm:min-w-32" disabled={!!blocked || starting} title={blocked} data-video-start>
					<SidebarModeIcon mode="video" className="size-4" />
					<span>{preparing ? '增强中…' : starting ? '发出中…' : '开始制作'}</span>
				</button>
			</div>

			{#if tasks.length}
				<div class="glass-item p-4 space-y-3" data-video-tasks>
					<div class="flex items-center justify-between gap-2">
						<div class="text-sm font-semibold text-gray-900 dark:text-gray-100">制作任务</div>
						<span class="text-xs text-gray-500 dark:text-gray-400">可以离开这页，做好后自动进视频库</span>
					</div>
					{#each visibleTasks as task (task.chatId)}
						<VideoTaskCard
							{task}
							where="studio"
							stopping={stoppingTask === task.chatId}
							highlight={task.chatId === focusTask}
							on:stop={(event) => stopTask(event.detail)}
						/>
					{/each}
					{#if historyTasks.length}
						<div class="flex flex-wrap items-center justify-between gap-2">
							<button
								type="button"
								class="rounded-lg py-1 text-xs text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
								aria-expanded={showTaskHistory}
								aria-controls="video-task-history"
								on:click={() => (showTaskHistory = !showTaskHistory)}
								data-video-task-history-toggle
							>
								{showTaskHistory ? '收起' : '展开'}已完成 / 已停止任务（{historyTasks.length}）
								<span aria-hidden="true">{showTaskHistory ? '▴' : '▾'}</span>
							</button>
							<button type="button" class="text-xs text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200" on:click={() => setTab('library')}>去视频库 →</button>
						</div>
						<div id="video-task-history" class="space-y-3" hidden={!showTaskHistory}>
							{#if showTaskHistory}
								{#each historyTasks as task (task.chatId)}
									<VideoTaskCard {task} where="studio" />
								{/each}
							{/if}
						</div>
					{/if}
				</div>
			{/if}

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

				<VideoStylePicker
					value={settings.style}
					custom={settings.customStyle}
					appearance={settings.appearance}
					recipe={settings.recipe}
					onAppearance={(appearance) => (settings = { ...settings, appearance })}
					disabled={preparing || starting}
					{hasReference}
					onChange={(style, customStyle) => (settings = { ...settings, style, customStyle })}
				/>

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
						<div class="text-xs font-medium text-gray-500 dark:text-gray-400">
							时长{followsMusic ? ` · 跟背景音乐${music?.seconds ? `（${clockLabel(music.seconds)}）` : ''}` : ''}
						</div>
						<div class="flex flex-wrap gap-1.5">
							{#each VIDEO_LENGTHS as s}
								<button type="button" class={settings.seconds === s && !followsMusic ? chipOn : chip} on:click={() => setLength(s)} data-video-length={s}>
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

				<div class="space-y-2" data-video-prep-options>
					<div class="text-xs font-medium text-gray-500 dark:text-gray-400">提示词增强</div>
					<div class="flex flex-wrap gap-1.5">
						<button type="button" class={prepOptions.enhance ? chipOn : chip} aria-pressed={prepOptions.enhance} on:click={() => setPrepOption({ enhance: !prepOptions.enhance })} data-video-prep="enhance">
							开始前自动增强
						</button>
						<button type="button" class={prepOptions.research ? chipOn : chip} aria-pressed={prepOptions.research} on:click={() => setPrepOption({ research: !prepOptions.research })} data-video-prep="research">
							联网搜索
						</button>
						<button type="button" class={prepOptions.deeper ? chipOn : chip} aria-pressed={prepOptions.deeper} on:click={() => setPrepOption({ deeper: !prepOptions.deeper })} data-video-prep="deeper">
							需要时先精答 / 讨论
						</button>
					</div>
					<p class="text-xs leading-relaxed text-gray-500 dark:text-gray-400">
						gpt-chat 先判断：需要事实就联网查，内容要先想清楚就交给精答（有争议交给讨论），等结论出来再把需求改写完整、按时长拆好分镜，然后交给制作者。这些都在新对话里自动进行，点完开始制作就可以离开。{prepOptions.enhance
							? ''
							: '已关自动增强：点需求框右上的「增强」可以先看改写结果。'}
					</p>
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
								{makerLabel(video)}
							</span>
						</button>
						<div class="space-y-1 p-2">
							<div class="line-clamp-2 text-sm font-medium text-gray-800 dark:text-gray-100" title={video.name}>{videoTitle(video)}</div>
							<div class="flex items-center justify-between gap-2 text-xs text-gray-500">
								<span class="truncate">{dateLabel(video.createdAt)}{video.size ? ` · ${formatFileSize(video.size)}` : ''}</span>
								<span class="flex shrink-0 items-center gap-0.5">
									{#if video.chatId}
										<a href="/c/{encodeURIComponent(video.chatId)}" class="rounded-full px-2 py-0.5 hover:bg-gray-100 hover:text-gray-800 dark:hover:bg-gray-800 dark:hover:text-gray-200" title="打开做这个视频的对话" data-video-chat>对话</a>
									{:else if runSource(video)}
										<span class="rounded-full px-2 py-0.5" title="在 {runSource(video)} 发起的 {video.runner ?? ''} 运行 {video.runId}" data-video-run={video.runId}>{runSource(video)}</span>
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
				<span>{playing.name}{playing.size ? ` · ${formatFileSize(playing.size)}` : ''} · {dateLabel(playing.createdAt)}{playing.runId ? ` · ${makerLabel(playing)} 运行 ${playing.runId}` : ''}{runSource(playing) ? `（${runSource(playing)} 发起）` : ''}</span>
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
