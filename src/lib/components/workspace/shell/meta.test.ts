import { describe, expect, it } from 'vitest';

import { HIDDEN_WORKSPACE_TABS, getVisibleWorkspaceTabs } from './meta';

const admin = { user: { role: 'admin' }, config: {} };

describe('getVisibleWorkspaceTabs', () => {
	it('leaves the unused tabs out of the strip', () => {
		const keys = getVisibleWorkspaceTabs(admin, '/workspace/models').map((tab) => tab.key);
		expect(keys).toEqual(['models', 'assistants', 'prompts', 'images']);
		for (const hidden of HIDDEN_WORKSPACE_TABS) {
			expect(keys).not.toContain(hidden);
		}
	});

	it('still shows a hidden tab while its page is open', () => {
		const keys = getVisibleWorkspaceTabs(admin, '/workspace/tools/edit?id=x').map(
			(tab) => tab.key
		);
		expect(keys).toContain('tools');
		expect(keys).not.toContain('knowledge');
	});
});
