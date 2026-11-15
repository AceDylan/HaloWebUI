/**
 * 「生成 HTML 卡片」 on request: nothing designs a reply's card on its own any more
 * (backend utils/message_card.py). These helpers say where a reply's card stands and why one
 * did not come out.
 */

export type HtmlCardEntry = {
	status?: 'designing' | 'ready' | 'failed' | 'skipped' | string;
	reason?: string;
	startedAt?: number;
	endedAt?: number;
};

/** A card still "designing" after this was lost (a restart): it may be asked for again. */
export const HTML_CARD_STALE_MS = 6 * 60 * 1000;

const FENCED_HTML_RE = /^\s{0,3}(`{3,}|~{3,})\s*html\b/im;

/** Whether the content already carries an HTML card (a fenced html block). */
export const hasHtmlCard = (content: unknown): boolean =>
	typeof content === 'string' && FENCED_HTML_RE.test(content);

/** The card state of a reply: its own (`htmlCard`), else the one its 精答 / 讨论台 run keeps. */
export const messageCardEntry = (message: any): HtmlCardEntry | null =>
	message?.htmlCard ?? message?.answer_desk?.card ?? message?.discussion_room?.card ?? null;

/** Whether the card is being designed right now. */
export const cardBusy = (entry: HtmlCardEntry | null | undefined, nowMs = Date.now()): boolean =>
	entry?.status === 'designing' && nowMs - (entry.startedAt ?? 0) < HTML_CARD_STALE_MS;

const REASONS: Record<string, string> = {
	timeout: 'AGY 超时了',
	busy: 'AGY 正忙，稍后再试',
	unavailable: 'AGY 正忙，稍后再试',
	missing: '服务器上没有 AGY',
	not_found: '服务器上没有 AGY',
	authentication_required: 'AGY 需要重新登录',
	changed: '回复在生成时被改过了',
	empty: 'AGY 没有返回内容',
	empty_output: 'AGY 没有返回内容',
	invalid: 'AGY 返回的卡片不合规',
	skipped: '内容太少，不需要卡片'
};

/** Why a card did not come out, in words (the reason codes of utils/html_visual_prompt.py). */
export const cardFailureText = (entry: HtmlCardEntry | null | undefined): string => {
	const reason = `${entry?.reason ?? ''}`.trim();
	if (REASONS[reason]) return REASONS[reason];
	const http = /^http_(\d{3})$/.exec(reason);
	if (http) return http[1] === '429' ? 'AGY 额度用完或太忙（429）' : `AGY 出错（HTTP ${http[1]}）`;
	if (entry?.status === 'skipped') return REASONS.skipped;
	return reason ? `没生成（${reason}）` : '没生成';
};
