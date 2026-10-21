import { describe, expect, it, vi } from 'vitest';
import { normalizePrepOptions, prepErrorText, prepSummary, waitForPrep } from './studio-prep';

const job = (status: string, extra: Record<string, unknown> = {}) =>
	({ id: 'j1', kind: 'video', status, idea: 'x', steps: [], run: null, result: null, error: '', model: 'gpt-chat', createdAt: 1, ...extra }) as any;

describe('normalizePrepOptions', () => {
	it('is all on by default and keeps what was chosen', () => {
		expect(normalizePrepOptions(null)).toEqual({ enhance: true, research: true, deeper: true });
		expect(normalizePrepOptions({ research: false, deeper: 'no', enhance: false })).toEqual({ enhance: false, research: false, deeper: true });
	});
});

describe('waitForPrep', () => {
	it('reads the job until it ends, telling each reading', async () => {
		const get = vi.fn().mockResolvedValueOnce(job('running')).mockResolvedValueOnce(job('done', { result: { idea: 'y' } }));
		const seen: string[] = [];
		const ended = await waitForPrep('t', job('running'), { get, interval: 1, onUpdate: (j) => seen.push(j.status) });
		expect(ended.status).toBe('done');
		expect(seen).toEqual(['running', 'done']);
	});

	it('does not read a job that already ended', async () => {
		const get = vi.fn();
		expect((await waitForPrep('t', job('done'), { get, interval: 1 })).status).toBe('done');
		expect(get).not.toHaveBeenCalled();
	});

	it('stops when told, and ends as an error when the job is gone or keeps failing to read', async () => {
		const get = vi.fn().mockResolvedValue(job('running'));
		let n = 0;
		expect((await waitForPrep('t', job('running'), { get, interval: 1, stopped: () => ++n > 2 })).status).toBe('running');
		const gone = vi.fn().mockRejectedValue({ status: 404 });
		expect(await waitForPrep('t', job('running'), { get: gone, interval: 1 })).toMatchObject({ status: 'error' });
		const flaky = vi.fn().mockRejectedValue(new Error('offline'));
		const ended = await waitForPrep('t', job('running'), { get: flaky, interval: 1 });
		expect(ended).toMatchObject({ status: 'error', error: '读不到增强进度' });
		expect(flaky).toHaveBeenCalledTimes(5);
	});
});

describe('prepErrorText / prepSummary', () => {
	it('words an API error and what an enhancement brought', () => {
		expect(prepErrorText({ detail: '没有模型' })).toBe('没有模型');
		expect(prepErrorText(new Error('x'))).toBe('增强没成功');
		expect(prepSummary({ idea: 'a', notes: '', sources: [{ n: 1, title: 't', url: 'u' }], run: { kind: 'discuss', chatId: 'c', href: '/discuss/c', label: '讨论' } }, 'gpt-chat')).toBe(
			'已用 gpt-chat 增强 · 参考了讨论结论 · 1 个网上来源'
		);
		expect(prepSummary(null)).toBe('');
	});
});
