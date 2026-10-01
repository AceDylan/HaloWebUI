// Mounts the admin analytics page. Stats are keyed by the selection id the
// chat stored ("modelref::…"), while $models ids are "<conn>.<model>"; the
// models tab must still name each model and not flag live ones as deleted.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

const SELECTION_ID = 'modelref::openai::personal::id:ee5e02db::hermes-agent';
const GONE_ID = 'modelref::openai::personal::id:2649a5c5::gpt-5.6-sol';

const stat = (model: string, message_count: number) => ({
	model,
	message_count,
	total_prompt_tokens: 10,
	total_completion_tokens: 1,
	total_tokens: 11
});

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/services/models', () => ({ ensureModels: vi.fn(async () => []) }));
vi.mock('$lib/apis/users', () => ({ getUsers: vi.fn(async () => []) }));
vi.mock('$lib/apis/analytics', () => ({
	getModelUsageStats: vi.fn(async () => [stat(SELECTION_ID, 5), stat(GONE_ID, 1)]),
	getUserActivityStats: vi.fn(async () => []),
	getDailyStats: vi.fn(async () =>
		['2026-09-29', '2026-09-30', '2026-10-01'].map((date, i) => ({
			date,
			message_count: i === 1 ? 0 : 3,
			total_prompt_tokens: 0,
			total_completion_tokens: 0,
			total_tokens: 0
		}))
	),
	cleanupAnalytics: vi.fn()
}));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const waitFor = async <T>(probe: () => T | null | undefined | false): Promise<T> => {
	const started = Date.now();
	for (;;) {
		const value = probe();
		if (value) return value;
		if (Date.now() - started > 8000) throw new Error('timed out');
		await sleep(15);
	}
};

let app: any;
let target: any;

afterEach(() => {
	app?.$destroy();
	target?.remove();
	app = null;
});

describe('Analytics', () => {
	it('names models by their selection id and keeps idle days as bars', async () => {
		(globalThis as any).localStorage.token = 'tok';
		const { writable } = await import('svelte/store');
		const stores = await import('$lib/stores');
		stores.user.set({ id: 'u', role: 'admin', name: 'Admin' } as any);
		stores.models.set([
			{
				id: 'ee5e02db.hermes-agent',
				selection_id: SELECTION_ID,
				model_id: 'hermes-agent',
				original_id: 'hermes-agent',
				name: 'Hermes',
				owned_by: 'openai',
				model_ref: { provider: 'openai', source: 'personal', connection_id: 'ee5e02db' }
			}
		] as any);

		const i18n = writable({ language: 'zh-CN', t: (key: string) => key });
		const { default: Analytics } = await import('./Analytics.svelte');
		target = document.createElement('div');
		document.body.appendChild(target);
		app = new Analytics({ target, context: new Map<string, any>([['i18n', i18n]]) });

		const bars = await waitFor(() => {
			const found = target.querySelectorAll('[role="img"]');
			return found.length ? found : null;
		});
		expect(bars.length).toBe(3);

		const modelsTab = Array.from(target.querySelectorAll('button')).find((b: any) =>
			b.textContent.includes('模型')
		) as any;
		modelsTab.click();

		const rows = await waitFor(() => {
			const found = Array.from(target.querySelectorAll('tbody tr')) as any[];
			return found.length >= 2 ? found : null;
		});
		const text = rows.map((r) => r.textContent.replace(/\s+/g, ' ').trim());
		const live = text.find((t) => t.includes('Hermes'));
		const gone = text.find((t) => t.includes('gpt-5.6-sol'));
		expect(live).toBeTruthy();
		expect(live).not.toContain('Deleted');
		expect(gone).toContain('Deleted');
		expect(text.join(' ')).not.toContain('modelref::');
	});
});
