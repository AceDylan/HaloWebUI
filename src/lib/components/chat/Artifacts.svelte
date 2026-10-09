<script lang="ts">
	import { onDestroy, onMount, getContext, createEventDispatcher, tick } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18n } from 'i18next';
	import { marked } from 'marked';
	const i18n = getContext<Writable<I18n>>('i18n');
	const dispatch = createEventDispatcher();

	import {
		artifactAutoOpenDismissedMessageId,
		artifactPreviewTarget,
		chatId,
		showArtifacts,
		showControls
	} from '$lib/stores';
	import XMark from '../icons/XMark.svelte';
	import ImagePreview from '../common/ImagePreview.svelte';
	import {
		hasSameOriginPreviewImages,
		inlineSameOriginPreviewImages
	} from '$lib/utils/html-preview-images';
	import { copyToClipboard, createMessagesList } from '$lib/utils';
	import ArrowsPointingOut from '../icons/ArrowsPointingOut.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import SvgPanZoom from '../common/SVGPanZoom.svelte';
	import ArrowLeft from '../icons/ArrowLeft.svelte';
	import { toast } from 'svelte-sonner';
	import { extractSvgMarkupBlocks, normalizeSvgMarkup } from './Messages/Markdown/svgMarkupTokens';
	import {
		buildHtmlArtifactPreview,
		HTML_PREVIEW_IMAGE_ALT_MAX_CHARS,
		isInlineHtmlPreviewCopyMessage,
		isInlineHtmlPreviewImageMessage,
		HTML_PREVIEW_REFERRER_POLICY,
		HTML_PREVIEW_SANDBOX,
		type HtmlPreviewColorScheme
	} from '$lib/utils/html-preview';
	import { isDarkMode } from '$lib/utils/dark-mode';
	import {
		captureHtmlPreviewPng,
		downloadBlob,
		htmlPreviewExportErrorMessage,
		HtmlPreviewExportTimeoutError
	} from '$lib/utils/html-preview-export';

	export let overlay = false;
	export let history;
	let messages: any[] = [];

	type PreviewContent = { type: 'iframe' | 'svg'; content: string; messageId: string };
	type CachedMessageContents = {
		source: string;
		colorScheme: HtmlPreviewColorScheme;
		previews: PreviewContent[];
	};

	const MAX_ARTIFACT_VERSIONS = 50;

	let contents: PreviewContent[] = [];
	let selectedContentIdx = 0;
	// HTML previews follow the app theme like the inline answer cards do.
	let previewColorScheme: HtmlPreviewColorScheme = 'light';
	let builtColorScheme: HtmlPreviewColorScheme | null = null;

	let copied = false;
	let exportingImage = false;
	let iframeElement: HTMLIFrameElement;
	let showPreviewImage = false;
	let previewImageSrc = '';
	let previewImageAlt = '';
	let alive = true;
	let refreshTimer: ReturnType<typeof setTimeout> | null = null;
	const messageContentsCache = new Map<string, CachedMessageContents>();

	/** Strip thinking/reasoning blocks from content before code extraction */
	const stripThinkingBlocks = (text: string): string => {
		return text.replace(/<(think|thinking|reasoning)\b[^>]*>[\s\S]*?<\/\1>/gi, '');
	};

	const extractSvgContents = (content: string, messageId: string): PreviewContent[] => {
		const previews: PreviewContent[] = [];
		const seen = new Set<string>();
		const appendSvg = (markup: string) => {
			const normalizedContent = normalizeSvgMarkup(markup);
			if (!normalizedContent || seen.has(normalizedContent)) return;
			seen.add(normalizedContent);
			previews.push({ type: 'svg', content: normalizedContent, messageId });
		};

		const tokens = marked.lexer(content);
		marked.walkTokens(tokens, (token: any) => {
			if (token?.type !== 'code') return;
			const language = String(token.lang ?? '')
				.trim()
				.toLowerCase()
				.split(/\s+/, 1)[0];
			const code = String(token.text ?? '');
			if (language === 'svg' || (language === 'xml' && code.includes('<svg'))) {
				appendSvg(code);
			}
		});

		for (const markup of extractSvgMarkupBlocks(content)) {
			appendSvg(markup);
		}

		return previews;
	};

	// Same-origin uploads cannot load inside the sandboxed frame; swap them for
	// data: URLs once fetched, both in the cache and in the visible list.
	const inlinePreviewImages = (messageId: string, source: string, htmlPreview: string) => {
		void inlineSameOriginPreviewImages(htmlPreview).then((inlined) => {
			if (!alive || inlined === htmlPreview) return;
			const cached = messageContentsCache.get(messageId);
			if (cached?.source !== source) return;
			const swap = (entry: PreviewContent) =>
				entry.type === 'iframe' && entry.messageId === messageId && entry.content === htmlPreview
					? { ...entry, content: inlined }
					: entry;
			cached.previews = cached.previews.map(swap);
			contents = contents.map(swap);
		});
	};

	const buildMessageContents = (message: any): PreviewContent[] => {
		const messageId = String(message.id ?? '');
		const source = String(message.content ?? '');
		const colorScheme = previewColorScheme;
		const cached = messageContentsCache.get(messageId);
		if (cached?.source === source && cached.colorScheme === colorScheme) {
			return cached.previews;
		}

		const previews: PreviewContent[] = [];
		const htmlPreview = buildHtmlArtifactPreview(source, { colorScheme });
		if (htmlPreview) {
			previews.push({ type: 'iframe', content: htmlPreview, messageId });
			if (hasSameOriginPreviewImages(htmlPreview)) {
				inlinePreviewImages(messageId, source, htmlPreview);
			}
		}
		previews.push(...extractSvgContents(stripThinkingBlocks(source), messageId));

		messageContentsCache.set(messageId, { source, colorScheme, previews });
		return previews;
	};

	const scheduleGetContents = () => {
		if (refreshTimer) {
			clearTimeout(refreshTimer);
			refreshTimer = null;
		}
		if (!messages.some((message) => message?.done === false)) {
			getContents();
			return;
		}

		refreshTimer = setTimeout(() => {
			refreshTimer = null;
			if (alive) getContents();
		}, 300);
	};

	$: previewColorScheme = $isDarkMode ? 'dark' : 'light';

	const refreshContents = (currentHistory: any, _colorScheme: HtmlPreviewColorScheme) => {
		messages = currentHistory ? createMessagesList(currentHistory, currentHistory.currentId) : [];
		scheduleGetContents();
	};

	$: refreshContents(history, previewColorScheme);

	const getContents = () => {
		// A theme switch only re-renders the same versions: keep the one on screen.
		const themeOnly = builtColorScheme !== null && builtColorScheme !== previewColorScheme;
		const previousLength = contents.length;
		builtColorScheme = previewColorScheme;
		const nextContents: PreviewContent[] = [];
		const activeMessageIds = new Set<string>();

		for (const message of messages) {
			if (message?.role === 'user' || !message?.content || !message?.id) continue;
			const messageId = String(message.id);
			activeMessageIds.add(messageId);
			nextContents.push(...buildMessageContents(message));
		}

		for (const messageId of messageContentsCache.keys()) {
			if (!activeMessageIds.has(messageId)) {
				messageContentsCache.delete(messageId);
			}
		}

		contents = nextContents.slice(-MAX_ARTIFACT_VERSIONS);

		if (themeOnly && contents.length === previousLength && contents.length > 0) {
			return;
		}

		if (contents.length === 0) {
			// Defer store mutations out of the reactive block to avoid re-trigger loops
			tick().then(() => {
				if (alive) {
					showControls.set(false);
					showArtifacts.set(false);
				}
			});
		}

		const target = $artifactPreviewTarget;
		if (target?.type === 'svg' && target.content) {
			const normalizedContent = normalizeSvgMarkup(target.content);
			const existingIdx = contents.findIndex(
				(content) => content.type === 'svg' && content.content === normalizedContent
			);

			if (existingIdx >= 0) {
				selectedContentIdx = existingIdx;
				return;
			}

			contents = [
				...contents,
				{
					type: 'svg',
					content: normalizedContent,
					messageId: target.messageId ?? '__svg-preview__'
				}
			];
			selectedContentIdx = contents.length - 1;
			return;
		}

		if (target?.messageId) {
			for (let idx = contents.length - 1; idx >= 0; idx -= 1) {
				const content = contents[idx];
				if (
					content.messageId === target.messageId &&
					(!target.type || content.type === target.type)
				) {
					selectedContentIdx = idx;
					return;
				}
			}
		}

		selectedContentIdx = contents.length > 0 ? contents.length - 1 : 0;
	};

	function navigateContent(direction: 'prev' | 'next') {
		selectedContentIdx =
			direction === 'prev'
				? Math.max(selectedContentIdx - 1, 0)
				: Math.min(selectedContentIdx + 1, contents.length - 1);
	}

	const showFullScreen = () => {
		iframeElement?.requestFullscreen();
	};

	const exportPreviewPng = async () => {
		if (exportingImage) return;
		if (!iframeElement?.contentWindow || contents[selectedContentIdx]?.type !== 'iframe') {
			toast.error($i18n.t('No HTML preview is available to export.'));
			return;
		}

		exportingImage = true;
		try {
			const pngBlob = await captureHtmlPreviewPng(iframeElement, { keepTheme: true });
			if (!alive) return;
			downloadBlob(pngBlob, `halo-html-artifact-${Date.now()}.png`);
			toast.success($i18n.t('Exported PNG'));
		} catch (error) {
			if (!alive) return;
			if (error instanceof HtmlPreviewExportTimeoutError) {
				toast.error($i18n.t('PNG export timed out'));
				return;
			}
			toast.error(htmlPreviewExportErrorMessage(error) || $i18n.t('Failed to export PNG'));
		} finally {
			exportingImage = false;
		}
	};

	const handleExportMessage = async (event: MessageEvent) => {
		if (!iframeElement?.contentWindow || event.source !== iframeElement.contentWindow) return;
		const data = event.data;
		if (isInlineHtmlPreviewCopyMessage(data)) {
			await copyToClipboard(data.text);
			toast.success($i18n.t('Copied'));
			return;
		}
		if (isInlineHtmlPreviewImageMessage(data)) {
			previewImageSrc = data.src;
			previewImageAlt = String(data.alt ?? '').slice(0, HTML_PREVIEW_IMAGE_ALT_MAX_CHARS);
			showPreviewImage = true;
		}
	};

	onMount(() => {
		window.addEventListener('message', handleExportMessage);
	});

	onDestroy(() => {
		alive = false;
		window.removeEventListener('message', handleExportMessage);
		if (refreshTimer) clearTimeout(refreshTimer);
	});

	const getActivePreviewMessageId = () =>
		$artifactPreviewTarget?.messageId ?? contents[selectedContentIdx]?.messageId ?? null;

	const dismissArtifacts = ({ closeControls = false } = {}) => {
		const messageId = getActivePreviewMessageId();

		if (messageId) {
			artifactAutoOpenDismissedMessageId.set(messageId);
		}

		artifactPreviewTarget.set(null);
		showArtifacts.set(false);

		if (closeControls) {
			dispatch('close');
			showControls.set(false);
		}
	};

	const closeArtifacts = () => {
		dismissArtifacts({ closeControls: true });
	};
</script>

<div class=" w-full h-full relative flex flex-col bg-gray-50 dark:bg-gray-850">
	<div class="w-full h-full flex flex-col flex-1 relative">
		{#if contents.length > 0}
			<div
				class="pointer-events-auto z-20 flex justify-between items-center p-2.5 font-primar text-gray-900 dark:text-white"
			>
				<button
					class="self-center pointer-events-auto p-1 rounded-full bg-white dark:bg-gray-850"
					on:click={() => dismissArtifacts()}
				>
					<ArrowLeft className="size-3.5  text-gray-900 dark:text-white" />
				</button>

				<div class="flex-1 flex items-center justify-between">
					<div class="flex items-center space-x-2">
						<div class="flex items-center gap-0.5 self-center min-w-fit" dir="ltr">
							<button
								class="self-center p-1 hover:bg-black/5 dark:hover:bg-white/5 dark:hover:text-white hover:text-black rounded-md transition disabled:cursor-not-allowed"
								on:click={() => navigateContent('prev')}
								disabled={contents.length <= 1}
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke="currentColor"
									stroke-width="2.5"
									class="size-3.5"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M15.75 19.5 8.25 12l7.5-7.5"
									/>
								</svg>
							</button>

							<div class="text-xs self-center dark:text-gray-100 min-w-fit">
								{$i18n.t('Version {{selectedVersion}} of {{totalVersions}}', {
									selectedVersion: selectedContentIdx + 1,
									totalVersions: contents.length
								})}
							</div>

							<button
								class="self-center p-1 hover:bg-black/5 dark:hover:bg-white/5 dark:hover:text-white hover:text-black rounded-md transition disabled:cursor-not-allowed"
								on:click={() => navigateContent('next')}
								disabled={contents.length <= 1}
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke="currentColor"
									stroke-width="2.5"
									class="size-3.5"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="m8.25 4.5 7.5 7.5-7.5 7.5"
									/>
								</svg>
							</button>
						</div>
					</div>

					<div class="flex items-center gap-1">
						<button
							class="copy-code-button bg-none border-none text-xs bg-gray-50 hover:bg-gray-100 dark:bg-gray-850 dark:hover:bg-gray-800 transition rounded-md px-1.5 py-0.5"
							on:click={() => {
								copyToClipboard(contents[selectedContentIdx].content);
								copied = true;

								setTimeout(() => {
									copied = false;
								}, 2000);
							}}>{copied ? $i18n.t('Copied') : $i18n.t('Copy')}</button
						>

						{#if contents[selectedContentIdx].type === 'iframe'}
							<button
								class="bg-none border-none text-xs bg-gray-50 hover:bg-gray-100 dark:bg-gray-850 dark:hover:bg-gray-800 transition rounded-md px-1.5 py-0.5 disabled:cursor-wait disabled:opacity-60"
								on:click={exportPreviewPng}
								disabled={exportingImage}
							>
								{exportingImage ? $i18n.t('Exporting...') : $i18n.t('Export PNG')}
							</button>

							<Tooltip content={$i18n.t('Open in full screen')}>
								<button
									class=" bg-none border-none text-xs bg-gray-50 hover:bg-gray-100 dark:bg-gray-850 dark:hover:bg-gray-800 transition rounded-md p-0.5"
									on:click={showFullScreen}
								>
									<ArrowsPointingOut className="size-3.5" />
								</button>
							</Tooltip>
						{/if}
					</div>
				</div>

				<button
					class="self-center pointer-events-auto p-1 rounded-full bg-white dark:bg-gray-850"
					on:click={closeArtifacts}
				>
					<XMark className="size-3.5 text-gray-900 dark:text-white" />
				</button>
			</div>
		{/if}

		{#if overlay}
			<div class=" absolute top-0 left-0 right-0 bottom-0 z-10"></div>
		{/if}

		<div class="flex-1 w-full h-full">
			<div class=" h-full flex flex-col">
				{#if contents.length > 0}
					<div class="max-w-full w-full h-full">
						{#if contents[selectedContentIdx].type === 'iframe'}
							<iframe
								bind:this={iframeElement}
								title="HTML artifact preview"
								srcdoc={contents[selectedContentIdx].content}
								class="w-full border-0 h-full rounded-none"
								sandbox={HTML_PREVIEW_SANDBOX}
								referrerpolicy={HTML_PREVIEW_REFERRER_POLICY}
							></iframe>
						{:else if contents[selectedContentIdx].type === 'svg'}
							<SvgPanZoom
								className=" w-full h-full max-h-full overflow-hidden"
								svg={contents[selectedContentIdx].content}
							/>
						{/if}
					</div>
				{:else}
					<div class="m-auto font-medium text-xs text-gray-900 dark:text-white">
						{$i18n.t('No previewable HTML or SVG content found.')}
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>

<ImagePreview bind:show={showPreviewImage} src={previewImageSrc} alt={previewImageAlt} />
