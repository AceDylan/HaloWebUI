import { describe, expect, it } from 'vitest';

import { cardBusy, cardFailureText, hasHtmlCard, HTML_CARD_STALE_MS, messageCardEntry } from './html-card';

describe('html-card', () => {
	it('knows a reply that already carries a card', () => {
		expect(hasHtmlCard('正文\n\n````html\n<div class="hv"></div>\n````')).toBe(true);
		expect(hasHtmlCard('正文\n\n```HTML\n<div></div>\n```')).toBe(true);
		expect(hasHtmlCard('正文 ```html 行内不算')).toBe(false);
		expect(hasHtmlCard('```python\nprint(1)\n```')).toBe(false);
		expect(hasHtmlCard(undefined)).toBe(false);
	});

	it("reads the reply's own card state, else its mode run's", () => {
		expect(messageCardEntry({ htmlCard: { status: 'failed' } })?.status).toBe('failed');
		expect(messageCardEntry({ answer_desk: { card: { status: 'designing' } } })?.status).toBe('designing');
		expect(messageCardEntry({ discussion_room: { card: { status: 'ready' } } })?.status).toBe('ready');
		expect(messageCardEntry({ content: 'x' })).toBeNull();
	});

	it('a card lost to a restart is not busy', () => {
		const now = 1_000_000_000;
		expect(cardBusy({ status: 'designing', startedAt: now - 1000 }, now)).toBe(true);
		expect(cardBusy({ status: 'designing', startedAt: now - HTML_CARD_STALE_MS - 1 }, now)).toBe(false);
		expect(cardBusy({ status: 'ready', startedAt: now }, now)).toBe(false);
		expect(cardBusy(null, now)).toBe(false);
	});

	it('says why a card did not come out', () => {
		expect(cardFailureText({ status: 'failed', reason: 'timeout' })).toBe('AGY 超时了');
		expect(cardFailureText({ status: 'failed', reason: 'http_429' })).toContain('429');
		expect(cardFailureText({ status: 'failed', reason: 'http_502' })).toBe('AGY 出错（HTTP 502）');
		expect(cardFailureText({ status: 'failed', reason: 'changed' })).toBe('回复在生成时被改过了');
		expect(cardFailureText({ status: 'failed', reason: 'weird' })).toBe('没生成（weird）');
		expect(cardFailureText({ status: 'failed' })).toBe('没生成');
	});
});
