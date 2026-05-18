const DATA_URL_RE = /^data:([^;,]+)?[;,]/i;

const EXTENSION_BY_MIME_TYPE: Record<string, string> = {
	'text/plain': 'txt',
	'text/csv': 'csv',
	'text/markdown': 'md',
	'application/json': 'json',
	'application/pdf': 'pdf',
	'application/zip': 'zip',
	'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
	'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
	'image/png': 'png',
	'image/jpeg': 'jpg',
	'image/gif': 'gif',
	'image/webp': 'webp'
};

const sanitizeDownloadName = (value: string): string => {
	const sanitized = value
		.replace(/[\u0000-\u001f\u007f]/g, '')
		.replace(/[\\/:*?"<>|]/g, '_')
		.trim();

	return sanitized.slice(0, 160);
};

const inferDataUrlExtension = (href: string): string => {
	const mimeType = DATA_URL_RE.exec(href.trim())?.[1]?.toLowerCase() ?? '';
	return EXTENSION_BY_MIME_TYPE[mimeType] ?? 'download';
};

export const getDataUrlDownloadName = (href: string, label: string = ''): string | null => {
	if (!DATA_URL_RE.test(href.trim())) {
		return null;
	}

	const extension = inferDataUrlExtension(href);
	const name = sanitizeDownloadName(label);
	if (!name) {
		return `download.${extension}`;
	}

	return /\.[a-z0-9]{1,12}$/i.test(name) ? name : `${name}.${extension}`;
};

const escapeHtmlAttribute = (value: string): string =>
	value
		.replaceAll('&', '&amp;')
		.replaceAll('"', '&quot;')
		.replaceAll('<', '&lt;')
		.replaceAll('>', '&gt;');

const rewriteDataUrlDownloadLinksFallback = (html: string): string =>
	html.replace(/<a(\s[^<>]*)?>/gi, (tag) => {
		const hrefMatch = tag.match(/\shref\s*=\s*("([^"]*)"|'([^']*)'|([^\s"'=<>]+))/i);
		const href = hrefMatch?.[2] ?? hrefMatch?.[3] ?? hrefMatch?.[4] ?? '';
		const downloadName = getDataUrlDownloadName(href);
		if (!downloadName) {
			return tag;
		}

		let rewritten = tag.replace(/\starget\s*=\s*("([^"]*)"|'([^']*)'|([^\s"'=<>]+))/gi, '');
		if (/\sdownload(\s*=|\s|>)/i.test(rewritten)) {
			rewritten = rewritten.replace(
				/\sdownload(\s*=\s*("([^"]*)"|'([^']*)'|([^\s"'=<>]+)))?/i,
				` download="${escapeHtmlAttribute(downloadName)}"`
			);
		} else {
			rewritten = rewritten.replace(/>$/, ` download="${escapeHtmlAttribute(downloadName)}">`);
		}
		return rewritten;
	});

export const rewriteDataUrlDownloadLinks = (html: string): string => {
	if (!html || !html.toLowerCase().includes('data:')) {
		return html;
	}

	if (typeof document === 'undefined') {
		return rewriteDataUrlDownloadLinksFallback(html);
	}

	const template = document.createElement('template');
	template.innerHTML = html;

	template.content.querySelectorAll('a[href]').forEach((node) => {
		const href = node.getAttribute('href') ?? '';
		const downloadName = getDataUrlDownloadName(href, node.textContent ?? '');
		if (!downloadName) {
			return;
		}

		node.setAttribute('download', downloadName);
		node.removeAttribute('target');
	});

	return template.innerHTML;
};
