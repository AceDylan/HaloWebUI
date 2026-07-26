export const HTML_VISUAL_MODES = ['off', 'auto', 'force'] as const;

export type HtmlVisualMode = (typeof HTML_VISUAL_MODES)[number];

export const normalizeHtmlVisualMode = (value: unknown): HtmlVisualMode => {
	// Missing legacy settings adopt the new web default; malformed persisted values fail closed.
	if (value === undefined || value === null) return 'force';
	if (value === true) return 'force';
	if (value === false) return 'off';
	if (typeof value === 'string') {
		const normalized = value.trim().toLowerCase();
		if (normalized === 'off' || normalized === 'auto' || normalized === 'force') {
			return normalized;
		}
	}
	return 'off';
};

export const serializeHtmlVisualMode = (value: unknown): HtmlVisualMode =>
	normalizeHtmlVisualMode(value);
