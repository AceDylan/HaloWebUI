export type ChatPdfExportMode = 'stylized' | 'compact';

type ExportChatPdfOptions = {
	sourceElement: HTMLElement;
	title?: string | null;
	mode?: ChatPdfExportMode;
	darkMode?: boolean;
};

type RgbaColor = {
	r: number;
	g: number;
	b: number;
	a: number;
};

type PageSlice = {
	offsetY: number;
	sliceHeight: number;
};

type BlockRange = {
	top: number;
	bottom: number;
};

const PDF_PAGE_WIDTH_MM = 210;
const PDF_PAGE_HEIGHT_MM = 297;
const PRIMARY_BREAK_SELECTOR = [
	'.pdf-export-header',
	'[id^="message-"]'
].join(', ');
const SECONDARY_BREAK_SELECTOR = [
	'[id^="message-"] p',
	'[id^="message-"] ul',
	'[id^="message-"] ol',
	'[id^="message-"] li',
	'[id^="message-"] h1',
	'[id^="message-"] h2',
	'[id^="message-"] h3',
	'[id^="message-"] h4',
	'[id^="message-"] h5',
	'[id^="message-"] h6'
].join(', ');
const ATOMIC_BLOCK_SELECTOR = [
	'[id^="message-"] pre',
	'[id^="message-"] blockquote',
	'[id^="message-"] table',
	'[id^="message-"] img:not([alt="model profile"]):not([alt="profile"])'
].join(', ');

const MODE_CONFIG: Record<
	ChatPdfExportMode,
	{
		width: number;
		scale: number;
		quality: number;
		backgroundColor: (darkMode: boolean) => string;
	}
> = {
	stylized: {
		width: 820,
		scale: 2,
		quality: 0.78,
		backgroundColor: (darkMode) => (darkMode ? '#020617' : '#ffffff')
	},
	compact: {
		width: 760,
		scale: 1.25,
		quality: 0.72,
		backgroundColor: () => '#ffffff'
	}
};

const waitForNextFrame = () =>
	new Promise<void>((resolve) => {
		requestAnimationFrame(() => resolve());
	});

const waitForStableLayout = async () => {
	await waitForNextFrame();
	await waitForNextFrame();

	if (document.fonts?.ready) {
		try {
			await document.fonts.ready;
		} catch {
			// ignore font loading errors and let html2canvas continue
		}
	}

	await new Promise((resolve) => setTimeout(resolve, 60));
};

const parseCssColor = (value: string): RgbaColor | null => {
	if (!value || value === 'transparent' || value === 'initial' || value === 'inherit') {
		return null;
	}

	const rgbMatch = value.match(
		/rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?\s*\)/i
	);

	if (rgbMatch) {
		return {
			r: Number(rgbMatch[1]),
			g: Number(rgbMatch[2]),
			b: Number(rgbMatch[3]),
			a: rgbMatch[4] === undefined ? 1 : Number(rgbMatch[4])
		};
	}

	const hexMatch = value.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i);
	if (!hexMatch) {
		return null;
	}

	let hex = hexMatch[1];
	if (hex.length === 3) {
		hex = hex
			.split('')
			.map((char) => `${char}${char}`)
			.join('');
	}

	if (hex.length === 6) {
		return {
			r: parseInt(hex.slice(0, 2), 16),
			g: parseInt(hex.slice(2, 4), 16),
			b: parseInt(hex.slice(4, 6), 16),
			a: 1
		};
	}

	return {
		r: parseInt(hex.slice(0, 2), 16),
		g: parseInt(hex.slice(2, 4), 16),
		b: parseInt(hex.slice(4, 6), 16),
		a: parseInt(hex.slice(6, 8), 16) / 255
	};
};

const getLuminance = (color: RgbaColor | null) => {
	if (!color) {
		return 1;
	}

	const normalize = (channel: number) => {
		const value = channel / 255;
		return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
	};

	return (
		0.2126 * normalize(color.r) + 0.7152 * normalize(color.g) + 0.0722 * normalize(color.b)
	);
};

const isDarkSurface = (color: RgbaColor | null) =>
	Boolean(color && color.a > 0.15 && getLuminance(color) < 0.38);

const isLightText = (color: RgbaColor | null) =>
	Boolean(color && color.a > 0.1 && getLuminance(color) > 0.82);

const sanitizeFileName = (title?: string | null) => {
	const baseName = (title ?? '').trim() || 'chat';
	return `chat-${baseName.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_')}.pdf`;
};

const stabilizeModelIconsForExport = (root: HTMLElement) => {
	const wrappers = Array.from(root.querySelectorAll<HTMLElement>('.model-icon'));

	for (const wrapper of wrappers) {
		const rect = wrapper.getBoundingClientRect();
		const width = Math.max(Math.round(rect.width), 1);
		const height = Math.max(Math.round(rect.height), 1);
		const wrapperStyle = window.getComputedStyle(wrapper);
		const img = wrapper.querySelector<HTMLImageElement>('img');

		wrapper.style.width = `${width}px`;
		wrapper.style.height = `${height}px`;
		wrapper.style.minWidth = `${width}px`;
		wrapper.style.minHeight = `${height}px`;
		wrapper.style.maxWidth = `${width}px`;
		wrapper.style.maxHeight = `${height}px`;
		wrapper.style.display = 'inline-flex';
		wrapper.style.alignItems = 'center';
		wrapper.style.justifyContent = 'center';
		wrapper.style.flex = 'none';
		wrapper.style.overflow = 'hidden';
		wrapper.style.borderRadius = wrapperStyle.borderRadius;
		wrapper.style.backgroundColor = wrapperStyle.backgroundColor;
		wrapper.style.boxShadow = wrapperStyle.boxShadow;

		if (!img) {
			continue;
		}

		const imgStyle = window.getComputedStyle(img);
		img.style.width = `${width}px`;
		img.style.height = `${height}px`;
		img.style.minWidth = `${width}px`;
		img.style.minHeight = `${height}px`;
		img.style.maxWidth = `${width}px`;
		img.style.maxHeight = `${height}px`;
		img.style.display = 'block';
		img.style.objectFit = imgStyle.objectFit;
		img.style.transform = imgStyle.transform === 'none' ? '' : imgStyle.transform;
		img.style.transformOrigin = imgStyle.transformOrigin;
		img.style.filter = imgStyle.filter === 'none' ? '' : imgStyle.filter;
		img.style.borderRadius = imgStyle.borderRadius;
		img.style.opacity = '1';
		img.style.transition = 'none';
	}
};

const applyCompactAppearance = (root: HTMLElement) => {
	root.style.background = '#ffffff';
	root.style.color = '#111827';

	const elements = [root, ...Array.from(root.querySelectorAll<HTMLElement>('*'))];
	for (const element of elements) {
		element.style.animation = 'none';
		element.style.transition = 'none';
		element.style.backdropFilter = 'none';
		element.style.filter = 'none';
		element.style.boxShadow = 'none';

		const computed = window.getComputedStyle(element);
		const backgroundColor = parseCssColor(computed.backgroundColor);
		const textColor = parseCssColor(computed.color);
		const borderColor = parseCssColor(computed.borderColor);
		const tagName = element.tagName.toLowerCase();
		const isCodeLike = ['pre', 'code', 'blockquote', 'table', 'thead', 'tbody', 'tr', 'td', 'th'].includes(
			tagName
		);

		if (isDarkSurface(backgroundColor)) {
			element.style.backgroundColor = isCodeLike ? '#f3f4f6' : '#ffffff';
		}

		if (isLightText(textColor)) {
			element.style.color = '#111827';
		}

		if (isDarkSurface(borderColor)) {
			element.style.borderColor = '#d1d5db';
		}
	}
};

const buildClone = (sourceElement: HTMLElement, mode: ChatPdfExportMode, width: number) => {
	const clone = sourceElement.cloneNode(true) as HTMLElement;
	clone.style.position = 'absolute';
	clone.style.left = '-20000px';
	clone.style.top = '0';
	clone.style.height = 'auto';
	clone.style.maxWidth = 'none';
	clone.style.width = `${width}px`;
	clone.style.pointerEvents = 'none';
	clone.style.opacity = '1';
	clone.style.zIndex = '-1';
	clone.setAttribute('data-pdf-capture-mode', mode);

	return clone;
};

const collectBreakOffsets = (root: HTMLElement, selector: string, canvasWidth: number) => {
	const rootRect = root.getBoundingClientRect();
	const pxPerCssPixel = canvasWidth / Math.max(rootRect.width, 1);
	const offsets = new Set<number>();

	for (const element of root.querySelectorAll<HTMLElement>(selector)) {
		const rect = element.getBoundingClientRect();
		const top = Math.round((rect.top - rootRect.top) * pxPerCssPixel);
		if (top > 0) {
			offsets.add(top);
		}
	}

	return Array.from(offsets).sort((left, right) => left - right);
};

const collectBlockRanges = (root: HTMLElement, selector: string, canvasWidth: number) => {
	const rootRect = root.getBoundingClientRect();
	const pxPerCssPixel = canvasWidth / Math.max(rootRect.width, 1);
	const blocks: BlockRange[] = [];

	for (const element of root.querySelectorAll<HTMLElement>(selector)) {
		const rect = element.getBoundingClientRect();
		const top = Math.round((rect.top - rootRect.top) * pxPerCssPixel);
		const bottom = Math.round((rect.bottom - rootRect.top) * pxPerCssPixel);

		if (bottom > top) {
			blocks.push({ top, bottom });
		}
	}

	return blocks.sort((left, right) => left.top - right.top);
};

const getBandInkScore = (
	imageData: Uint8ClampedArray,
	canvasWidth: number,
	canvasHeight: number,
	startRow: number,
	bandHeight: number,
	background: RgbaColor
) => {
	let inkPixels = 0;
	let sampledPixels = 0;

	for (let row = startRow; row < Math.min(startRow + bandHeight, canvasHeight); row += 1) {
		for (let col = 0; col < canvasWidth; col += 2) {
			const index = (row * canvasWidth + col) * 4;
			const r = imageData[index];
			const g = imageData[index + 1];
			const b = imageData[index + 2];
			const a = imageData[index + 3];

			if (a < 12) {
				sampledPixels += 1;
				continue;
			}

			const distance =
				Math.abs(r - background.r) +
				Math.abs(g - background.g) +
				Math.abs(b - background.b);

			if (distance > 48) {
				inkPixels += 1;
			}

			sampledPixels += 1;
		}
	}

	return sampledPixels === 0 ? 1 : inkPixels / sampledPixels;
};

const findWhitespaceBreak = (
	canvas: HTMLCanvasElement,
	currentTop: number,
	targetBottom: number,
	minPageFill: number,
	background: RgbaColor
) => {
	const ctx = canvas.getContext('2d');
	if (!ctx) {
		return null;
	}

	const searchHeight = Math.min(220, Math.max(Math.floor((targetBottom - currentTop) * 0.22), 80));
	const searchStart = Math.max(currentTop + minPageFill, targetBottom - searchHeight);
	const searchEnd = Math.max(searchStart, targetBottom - 12);
	const imageData = ctx.getImageData(0, searchStart, canvas.width, searchEnd - searchStart + 1).data;

	let bestRow = -1;
	let bestScore = Number.POSITIVE_INFINITY;

	for (let row = 0; row <= searchEnd - searchStart; row += 2) {
		const absoluteRow = searchStart + row;
		const score = getBandInkScore(imageData, canvas.width, searchEnd - searchStart + 1, row, 4, background);
		if (score < bestScore) {
			bestScore = score;
			bestRow = absoluteRow;
		}
	}

	return bestScore < 0.035 ? bestRow : null;
};

const buildPageSlices = (
	canvas: HTMLCanvasElement,
	root: HTMLElement,
	pagePixelHeight: number,
	background: RgbaColor
) => {
	const primaryBreakOffsets = collectBreakOffsets(root, PRIMARY_BREAK_SELECTOR, canvas.width);
	const secondaryBreakOffsets = collectBreakOffsets(root, SECONDARY_BREAK_SELECTOR, canvas.width);
	const messageRanges = collectBlockRanges(root, '[id^="message-"]', canvas.width);
	const atomicRanges = collectBlockRanges(root, ATOMIC_BLOCK_SELECTOR, canvas.width);
	const slices: PageSlice[] = [];
	const minPageFill = Math.floor(pagePixelHeight * 0.62);
	const minSliceHeight = Math.floor(pagePixelHeight * 0.35);
	const preferredMessageFill = Math.floor(pagePixelHeight * 0.52);
	let offsetY = 0;

	while (offsetY < canvas.height) {
		if (offsetY + pagePixelHeight >= canvas.height) {
			slices.push({
				offsetY,
				sliceHeight: canvas.height - offsetY
			});
			break;
		}

		const targetBottom = offsetY + pagePixelHeight;
		const crossingMessage = messageRanges.find(
			(range) =>
				range.top > offsetY + minSliceHeight &&
				range.top < targetBottom &&
				range.bottom > targetBottom &&
				targetBottom - range.top < Math.min(180, pagePixelHeight * 0.22)
		);
		const crossingAtomic = atomicRanges.find(
			(range) =>
				range.top > offsetY + minSliceHeight &&
				range.top < targetBottom &&
				range.bottom > targetBottom &&
				range.bottom - range.top < pagePixelHeight * 0.92
		);

		const primaryBreak = [...primaryBreakOffsets]
			.reverse()
			.find(
				(offset) => offset >= offsetY + preferredMessageFill && offset <= targetBottom - 12
			);
		const secondaryBreak = [...secondaryBreakOffsets]
			.reverse()
			.find((offset) => offset >= offsetY + minPageFill && offset <= targetBottom - 12);

		const whitespaceBreak =
			crossingMessage === undefined &&
			crossingAtomic === undefined &&
			primaryBreak === undefined &&
			secondaryBreak === undefined
				? findWhitespaceBreak(canvas, offsetY, targetBottom, minPageFill, background)
				: null;

		const nextBreak =
			crossingMessage?.top ??
			crossingAtomic?.top ??
			primaryBreak ??
			secondaryBreak ??
			whitespaceBreak ??
			targetBottom;
		const sliceHeight = Math.max(nextBreak - offsetY, minSliceHeight);

		slices.push({
			offsetY,
			sliceHeight
		});

		offsetY += sliceHeight;
	}

	return slices;
};

const saveCanvasAsPdf = async (
	canvas: HTMLCanvasElement,
	title: string | null | undefined,
	quality: number,
	darkMode: boolean,
	pageSlices: PageSlice[]
) => {
	const jspdfModule = await import('jspdf');
	const JsPdf = (jspdfModule as any).jsPDF ?? (jspdfModule as any).default;
	const pdf = new JsPdf('p', 'mm', 'a4');
	let page = 0;

	for (const { offsetY, sliceHeight } of pageSlices) {
		const pageCanvas = document.createElement('canvas');
		pageCanvas.width = canvas.width;
		pageCanvas.height = sliceHeight;

		const ctx = pageCanvas.getContext('2d');
		if (!ctx) {
			throw new Error('无法创建 PDF 画布。');
		}

		ctx.drawImage(canvas, 0, offsetY, canvas.width, sliceHeight, 0, 0, canvas.width, sliceHeight);

		const imageData = pageCanvas.toDataURL('image/jpeg', quality);
		const imageHeightMM = (sliceHeight * PDF_PAGE_WIDTH_MM) / canvas.width;

		if (page > 0) {
			pdf.addPage();
		}

		if (darkMode) {
			pdf.setFillColor(2, 6, 23);
			pdf.rect(0, 0, PDF_PAGE_WIDTH_MM, PDF_PAGE_HEIGHT_MM, 'F');
		}

		pdf.addImage(imageData, 'JPEG', 0, 0, PDF_PAGE_WIDTH_MM, imageHeightMM);
		page += 1;
	}

	pdf.save(sanitizeFileName(title));
};

export const exportChatPdfFromElement = async ({
	sourceElement,
	title,
	mode = 'stylized',
	darkMode = false
}: ExportChatPdfOptions) => {
	const { default: html2canvas } = await import('html2canvas-pro');
	const config = MODE_CONFIG[mode];
	const clone = buildClone(sourceElement, mode, config.width);

	document.body.appendChild(clone);

	try {
		await waitForStableLayout();
		stabilizeModelIconsForExport(clone);

		if (mode === 'compact') {
			applyCompactAppearance(clone);
			await waitForNextFrame();
		}

		const canvas = await html2canvas(clone, {
			backgroundColor: config.backgroundColor(darkMode),
			useCORS: true,
			scale: config.scale,
			width: config.width,
			windowWidth: config.width,
			logging: false
		});
		const pagePixelHeight = Math.floor((canvas.width / PDF_PAGE_WIDTH_MM) * PDF_PAGE_HEIGHT_MM);
		const background =
			parseCssColor(config.backgroundColor(darkMode)) ??
			({
				r: 255,
				g: 255,
				b: 255,
				a: 1
			} satisfies RgbaColor);
		const pageSlices = buildPageSlices(canvas, clone, pagePixelHeight, background);

		await saveCanvasAsPdf(
			canvas,
			title,
			config.quality,
			darkMode && mode === 'stylized',
			pageSlices
		);
	} finally {
		clone.remove();
	}
};
