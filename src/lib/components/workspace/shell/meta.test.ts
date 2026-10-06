import { describe, expect, it } from 'vitest';

import { HIDDEN_WORKSPACE_TABS, getVisibleWorkspaceTabs } from './meta';

const admin = { user: { role: 'admin' }, config: {} };

describe('getVisibleWorkspaceTabs', () => {
	it('leaves the unused tabs out of the strip', () => {
		const keys = getVisibleWorkspaceTabs(admin, '/workspace/models').map((tab) => tab.key);
		expect(keys).toEqual(['models', 'prompts', 'images']);
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

	it('keeps the templates tab only for users without the assistants page', () => {
		const member = { user: { role: 'user', permissions: { workspace: { models: true } } }, config: {} };
		expect(getVisibleWorkspaceTabs(member, '/workspace/models').map((t) => t.key)).not.toContain('assistants');
		const reader = { user: { role: 'user', permissions: { workspace: { prompts: true } } }, config: {} };
		const keys = getVisibleWorkspaceTabs(reader, '/workspace/assistants').map((t) => t.key);
		expect(keys).toContain('assistants');
		expect(keys).not.toContain('models');
	});
});
