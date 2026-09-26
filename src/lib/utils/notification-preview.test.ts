import { describe, expect, it } from 'vitest';

import { getNotificationPreview } from './notification-preview';

describe('getNotificationPreview', () => {
	it('shows the answer, not the tool transcript or the card source', () => {
		const content = [
			'我先看看。',
			'<details type="tool_calls" done="true" name="terminal" arguments="{}"><summary>Tool Executed</summary>\n</details>',
			'<details type="tool_calls" done="true" name="terminal" arguments="{}"><summary>Tool Executed</summary>\n</details>',
			'',
			'**结论**：部署完成，[详情](https://x.test)。',
			'',
			'````html\n<div>card</div>\n````'
		].join('\n');
		expect(getNotificationPreview(content)).toBe('结论：部署完成，详情。');
	});

	it('caps the length', () => {
		const preview = getNotificationPreview('a'.repeat(500), 200);
		expect(preview).toHaveLength(200);
		expect(preview.endsWith('…')).toBe(true);
	});

	it('skips injected guidance quotes', () => {
		expect(getNotificationPreview('答案在这里。\n\n> 🧭 换个思路')).toBe('答案在这里。');
	});

	it('is empty when there is nothing but tools', () => {
		expect(
			getNotificationPreview(
				'<details type="tool_calls" done="true"><summary>Tool Executed</summary></details>'
			)
		).toBe('');
	});
});
