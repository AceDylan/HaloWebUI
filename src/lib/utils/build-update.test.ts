import { beforeEach, describe, expect, it, vi } from 'vitest';

import { checkForNewBuild, isNewerBuild, resetBuildUpdateForTest } from './build-update';

const serving = (build: unknown, status = 200) =>
	vi.fn().mockResolvedValue(new Response(JSON.stringify({ version: '0.6', build }), { status }));

beforeEach(() => resetBuildUpdateForTest());

describe('build update', () => {
	it('only compares real builds', () => {
		expect(isNewerBuild('aaa', 'bbb')).toBe(true);
		expect(isNewerBuild('aaa', 'aaa')).toBe(false);
		expect(isNewerBuild('dev-build', 'bbb')).toBe(false);
		expect(isNewerBuild('aaa', 'dev-build')).toBe(false);
		expect(isNewerBuild('aaa', undefined)).toBe(false);
	});

	it('announces a redeploy once per build', async () => {
		const onNewBuild = vi.fn();
		await checkForNewBuild(onNewBuild, { running: 'aaa', fetchImpl: serving('bbb') });
		await checkForNewBuild(onNewBuild, { running: 'aaa', fetchImpl: serving('bbb') });
		expect(onNewBuild).toHaveBeenCalledTimes(1);
		await checkForNewBuild(onNewBuild, { running: 'aaa', fetchImpl: serving('ccc') });
		expect(onNewBuild).toHaveBeenLastCalledWith('ccc');
	});

	it('stays quiet on the same build or a server still restarting', async () => {
		const onNewBuild = vi.fn();
		await checkForNewBuild(onNewBuild, { running: 'aaa', fetchImpl: serving('aaa') });
		await checkForNewBuild(onNewBuild, { running: 'aaa', fetchImpl: serving('bbb', 502) });
		await checkForNewBuild(onNewBuild, {
			running: 'aaa',
			fetchImpl: vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
		});
		expect(onNewBuild).not.toHaveBeenCalled();
	});
});
