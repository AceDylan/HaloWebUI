export type SidebarLayoutMode = 'drawer' | 'foldable-rail' | 'desktop';
export type SidebarRailDensity = 'comfortable' | 'compact' | 'tight';

export type SidebarViewportInput = {
	width: number;
	height: number;
};

export type SidebarLayoutState = {
	mode: SidebarLayoutMode;
	railDensity: SidebarRailDensity;
	compactExpanded: boolean;
	overlayOnExpand: boolean;
	persistDesktopPreference: boolean;
};

export type RectLike = {
	top: number;
	left: number;
	right: number;
	bottom: number;
	width: number;
	height: number;
};

export const MOBILE_BREAKPOINT = 768;
export const FOLDABLE_MAX_WIDTH = 900;
export const COMPACT_HEIGHT_MAX = 860;
export const TIGHT_HEIGHT_MAX = 620;
export const COMPACT_EXPANDED_HEIGHT_MAX = 760;

const sanitizeDimension = (value: number): number =>
	Number.isFinite(value) ? Math.max(0, value) : 0;

export function resolveSidebarLayout(input: SidebarViewportInput): SidebarLayoutState {
	const width = sanitizeDimension(input.width);
	const height = sanitizeDimension(input.height);

	const mode: SidebarLayoutMode =
		width < MOBILE_BREAKPOINT
			? 'drawer'
			: width < FOLDABLE_MAX_WIDTH
				? 'foldable-rail'
				: 'desktop';

	const railDensity: SidebarRailDensity =
		height <= TIGHT_HEIGHT_MAX
			? 'tight'
			: height <= COMPACT_HEIGHT_MAX || width < FOLDABLE_MAX_WIDTH
				? 'compact'
				: 'comfortable';

	const compactExpanded =
		width < FOLDABLE_MAX_WIDTH || height <= COMPACT_EXPANDED_HEIGHT_MAX;
	const overlayOnExpand = width < FOLDABLE_MAX_WIDTH;
	const persistDesktopPreference = width >= FOLDABLE_MAX_WIDTH;

	return {
		mode,
		railDensity,
		compactExpanded,
		overlayOnExpand,
		persistDesktopPreference
	};
}

export function resolveInitialSidebarOpen(
	layout: SidebarLayoutState,
	storedDesktopSidebar: string | null | undefined
): boolean {
	if (!layout.persistDesktopPreference) {
		return false;
	}
	return storedDesktopSidebar !== 'false';
}

export function resolveInitialAssistantSectionOpen(
	storedValue: string | null | undefined,
	compactExpanded: boolean
): boolean {
	if (storedValue === 'true') {
		return true;
	}
	if (storedValue === 'false') {
		return false;
	}
	return !compactExpanded;
}

export function computeSidePopoverPosition(
	triggerRect: RectLike,
	panelSize: { width: number; height: number },
	viewport: { width: number; height: number },
	gap = 8,
	margin = 8
): { left: number; top: number } {
	const vw = sanitizeDimension(viewport.width);
	const vh = sanitizeDimension(viewport.height);
	const pw = sanitizeDimension(panelSize.width);
	const ph = sanitizeDimension(panelSize.height);

	const maxLeft = Math.max(margin, vw - pw - margin);
	const rawLeft = triggerRect.right + gap;
	const left = Math.round(Math.max(margin, Math.min(rawLeft, maxLeft)));

	const maxTop = Math.max(margin, vh - ph - margin);
	const rawTop = triggerRect.top;
	const top = Math.round(Math.max(margin, Math.min(rawTop, maxTop)));

	return { left, top };
}
