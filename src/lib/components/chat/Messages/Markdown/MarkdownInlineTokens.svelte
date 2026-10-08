<script lang="ts">
	import DOMPurify from 'dompurify';
	import { toast } from 'svelte-sonner';

	import type { Token } from 'marked';
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';

	const i18n: Writable<any> = getContext('i18n');

	import { WEBUI_BASE_URL } from '$lib/constants';
	import { config } from '$lib/stores';
	import { copyToClipboard, unescapeHtml } from '$lib/utils';
	import { splitVaultNotePaths, vaultNotePath } from '$lib/utils/hub-embed';
	import { inAppPath } from '$lib/utils/app-links';
	import { getDataUrlDownloadName, rewriteDataUrlDownloadLinks } from '$lib/utils/download-links';
	import KatexHtml from './KatexHtml.svelte';

	import Image from '$lib/components/common/Image.svelte';
	import {
		resolveGeneratedFileContentUrl,
		resolveGeneratedFileDownloadUrl,
		rewriteGeneratedFileHtmlLinks,
		type GeneratedMessageFile
	} from '$lib/utils/generated-file-links';
	import {
		buildLocalFileIframeSrc,
		resolveLocalFileIframeSrcFromHtml,
		resolveSafeMarkdownUrl,
		SAFE_HTML_URI_REGEXP
	} from '$lib/utils/html-safety';
	import { HTML_PREVIEW_REFERRER_POLICY, HTML_PREVIEW_SANDBOX } from '$lib/utils/html-preview';
	import KatexRenderer from './KatexRenderer.svelte';
	import Source from './Source.svelte';
	import SourceToken from './SourceToken.svelte';
	import StreamText from './StreamText.svelte';
	import VaultNoteLink from './VaultNoteLink.svelte';
	import { isSvgMarkup, mergeSvgMarkupTokens, type RenderableHtmlToken } from './svgMarkupTokens';

	export let id: string;
	export let tokens: Token[] = [];
	export let onSourceClick: Function = () => {};
	export let charAnimation = false;
	export let generatedFiles: GeneratedMessageFile[] = [];
	/** Inside a link: note paths in the text stay text (no link in a link). */
	export let inLink = false;

	let renderTokens: RenderableHtmlToken[] = [];
	$: renderTokens = mergeSvgMarkupTokens(tokens);

	const resolveLinkHref = (href: string) => {
		const resolved = resolveGeneratedFileDownloadUrl(href, generatedFiles) ?? href;
		return resolveSafeMarkdownUrl(resolved, {
			allowHash: true,
			allowRelative: true,
			allowDataDownload: true
		});
	};

	const resolveContentSrc = (href: string) =>
		resolveGeneratedFileContentUrl(href, generatedFiles) ?? href;

	const resolveImageSrc = (href: string) =>
		resolveSafeMarkdownUrl(resolveContentSrc(href), {
			allowHash: false,
			allowRelative: true,
			allowDataImage: true
		});

	const resolveDownloadName = (href: string, label: string = '') =>
		getDataUrlDownloadName(href, label);

	// A page of this app (a team's result page, a discussion, a chat) opens in place.
	const resolveAppPath = (href: string | null, download: string | null) =>
		href && !download
			? inAppPath(href, typeof location === 'undefined' ? null : location.origin)
			: null;

	// Absolute paths of the Hub's vault notes become links (see VaultNoteLink).
	$: vaultRoot = $config?.hub_origin ? $config?.hub_vault_root : undefined;

	const toText = (value: unknown) => String(value ?? '');
	const decodeHtmlText = (value: unknown) => unescapeHtml(toText(value)) ?? '';
</script>

{#each renderTokens as token}
	{#if token.type === 'escape'}
		{#if charAnimation}
			<StreamText text={decodeHtmlText(token.text)} />
		{:else}
			{decodeHtmlText(token.text)}
		{/if}
	{:else if token.type === 'html'}
		{@const tokenText = toText(token.text)}
		{@const isSvgMarkupToken = isSvgMarkup(tokenText)}
		{@const iframeSrc = resolveLocalFileIframeSrcFromHtml(tokenText, WEBUI_BASE_URL)}
		{@const html = rewriteDataUrlDownloadLinks(
			rewriteGeneratedFileHtmlLinks(
				DOMPurify.sanitize(tokenText, {
					ADD_ATTR: ['style', 'download', 'target', 'rel'],
					ALLOWED_URI_REGEXP: SAFE_HTML_URI_REGEXP
				}),
				generatedFiles
			)
		)}
		{#if isSvgMarkupToken}
			<span class="font-mono whitespace-pre-wrap break-all">{tokenText}</span>
		{:else if html && html.includes('<video')}
			{@html html}
		{:else if iframeSrc}
			<iframe
				src={iframeSrc}
				title="Generated file preview"
				width="100%"
				frameborder="0"
				sandbox={HTML_PREVIEW_SANDBOX}
				referrerpolicy={HTML_PREVIEW_REFERRER_POLICY}
				class="min-h-80 rounded-lg border border-gray-100 dark:border-gray-800"
			></iframe>
		{:else if tokenText.includes(`<source_id`)}
			<Source {id} {token} onClick={onSourceClick} />
		{:else}
			<KatexHtml {html} />
		{/if}
	{:else if token.type === 'link'}
		{@const notePath = inLink ? null : vaultNotePath(token.href ?? '', vaultRoot)}
		{@const href = notePath ? null : resolveLinkHref(token.href ?? '')}
		{@const download = href ? resolveDownloadName(href, token.text ?? '') : null}
		{@const appPath = resolveAppPath(href, download)}
		{#if notePath}
			<VaultNoteLink path={notePath}
				>{#if token.tokens}<svelte:self
						id={`${id}-a`}
						tokens={token.tokens}
						{charAnimation}
						{onSourceClick}
						{generatedFiles}
						inLink
					/>{:else}{toText(token.text)}{/if}</VaultNoteLink
			>
		{:else if href && token.tokens}
			<a
				href={appPath ?? href}
				target={download || appPath ? undefined : '_blank'}
				download={download ?? undefined}
				rel={appPath ? undefined : 'noopener noreferrer nofollow'}
				title={token.title}
				data-halo-app-link={appPath ? '' : undefined}
			>
				<svelte:self
					id={`${id}-a`}
					tokens={token.tokens}
					{charAnimation}
					{onSourceClick}
					{generatedFiles}
					inLink
				/>
			</a>
		{:else if token.tokens}
			<svelte:self
				id={`${id}-a`}
				tokens={token.tokens}
				{charAnimation}
				{onSourceClick}
				{generatedFiles}
				{inLink}
			/>
		{:else if href}
			<a
				href={appPath ?? href}
				target={download || appPath ? undefined : '_blank'}
				download={download ?? undefined}
				rel={appPath ? undefined : 'noopener noreferrer nofollow'}
				title={token.title}
				data-halo-app-link={appPath ? '' : undefined}>{toText(token.text)}</a
			>
		{:else}
			{toText(token.text)}
		{/if}
	{:else if token.type === 'image'}
		{@const src = resolveImageSrc(token.href ?? '')}
		{#if src}
			<Image {src} alt={toText(token.text)} />
		{:else}
			{toText(token.text)}
		{/if}
	{:else if token.type === 'strong'}
		<strong>
			<svelte:self
				id={`${id}-strong`}
				tokens={token.tokens}
				{charAnimation}
				{onSourceClick}
				{generatedFiles}
				{inLink}
			/>
		</strong>
	{:else if token.type === 'em'}
		<em>
			<svelte:self
				id={`${id}-em`}
				tokens={token.tokens}
				{charAnimation}
				{onSourceClick}
				{generatedFiles}
				{inLink}
			/>
		</em>
	{:else if token.type === 'codespan'}
		<!-- svelte-ignore a11y-click-events-have-key-events -->
		<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
		<code
			class="codespan cursor-pointer"
			on:click={() => {
				copyToClipboard(decodeHtmlText(token.text));
				toast.success($i18n.t('Copied to clipboard'));
			}}>{decodeHtmlText(token.text)}</code
		>{#if vaultRoot && !inLink}{@const notePath = vaultNotePath(
				decodeHtmlText(token.text),
				vaultRoot
			)}{#if notePath}<VaultNoteLink path={notePath} compact />{/if}{/if}
	{:else if token.type === 'br'}
		<br />
	{:else if token.type === 'del'}
		<del>
			<svelte:self
				id={`${id}-del`}
				tokens={token.tokens}
				{charAnimation}
				{onSourceClick}
				{generatedFiles}
				{inLink}
			/>
		</del>
	{:else if token.type === 'inlineKatex'}
		{#if token.text}
			<KatexRenderer content={token.text} source={token.raw} displayMode={false} />
		{/if}
	{:else if token.type === 'iframe'}
		{@const iframeSrc = buildLocalFileIframeSrc(token.fileId, WEBUI_BASE_URL)}
		{#if iframeSrc}
			<iframe
				src={iframeSrc}
				title={toText(token.fileId)}
				width="100%"
				frameborder="0"
				sandbox={HTML_PREVIEW_SANDBOX}
				referrerpolicy={HTML_PREVIEW_REFERRER_POLICY}
				class="min-h-80 rounded-lg border border-gray-100 dark:border-gray-800"
			></iframe>
		{/if}
	{:else if token.type === 'citation'}
		<SourceToken {id} {token} onClick={onSourceClick} />
	{:else if token.type === 'text'}
		{#if charAnimation}
			<StreamText text={toText(token.raw ?? token.text)} />
		{:else if vaultRoot && !inLink && toText(token.raw ?? token.text).includes(vaultRoot)}
			{#each splitVaultNotePaths(toText(token.raw ?? token.text), vaultRoot) as piece}{#if piece.path}<VaultNoteLink
						path={piece.path}>{piece.text}</VaultNoteLink
					>{:else}{piece.text}{/if}{/each}
		{:else}
			{toText(token.raw ?? token.text)}
		{/if}
	{/if}
{/each}
