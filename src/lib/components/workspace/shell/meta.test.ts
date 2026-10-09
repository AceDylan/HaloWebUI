import { describe, expect, it } from 'vitest';

import { WORKSPACE_TABS, getActiveWorkspaceTab } from './meta';

describe('getActiveWorkspaceTab', () => {
	it('names the page open, sub-pages included', () => {
		expect(getActiveWorkspaceTab('/workspace/models')?.key).toBe('models');
		expect(getActiveWorkspaceTab('/workspace/prompts/edit')?.key).toBe('prompts');
		expect(getActiveWorkspaceTab('/workspace/assistants')?.key).toBe('assistants');
		expect(getActiveWorkspaceTab('/workspace/tools/edit')?.key).toBe('tools');
		expect(getActiveWorkspaceTab('/workspace/schedules')?.key).toBe('schedules');
	});

	it('leaves the image studio to its own header', () => {
		expect(WORKSPACE_TABS.map((tab) => tab.key)).not.toContain('images');
		expect(getActiveWorkspaceTab('/workspace/images')).toBeNull();
	});
});
