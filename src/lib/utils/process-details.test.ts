import { describe, expect, it } from 'vitest';

import { getToolCallHistoryInput, processDetails } from './index';

describe('processDetails', () => {
	it('keeps the command of a hermes tool call for the next turn', () => {
		const content =
			'前言\n<details type="tool_calls" done="true" id="h-1" name="terminal" arguments="{&quot;input&quot;: &quot;git status &amp;&amp; echo \\&quot;ok\\&quot;&quot;}" result="{&quot;status&quot;: &quot;success&quot;, &quot;duration&quot;: 2}">\n<summary>Tool Executed</summary>\n</details>\n结论';
		const processed = processDetails(content);
		expect(processed).toContain(
			'<tool_calls name="terminal" input="git status &amp;&amp; echo &quot;ok&quot;" result="{&quot;status&quot;: &quot;success&quot;, &quot;duration&quot;: 2}"/>'
		);
		expect(processed).toContain('前言');
		expect(processed).toContain('结论');
	});

	it('leaves native tool calls as they were', () => {
		const processed = processDetails(
			'<details type="tool_calls" done="true" name="get_weather" arguments="{&quot;city&quot;: &quot;Paris&quot;, &quot;unit&quot;: &quot;c&quot;}" result="&quot;sunny&quot;"><summary>Tool Executed</summary></details>'
		);
		expect(processed).toBe('<tool_calls name="get_weather" result="&quot;sunny&quot;"/>');
	});

	it('caps a long command', () => {
		const input = getToolCallHistoryInput(
			`{&quot;input&quot;: &quot;${'x'.repeat(400)}&quot;}`
		);
		expect(input.length).toBe(160);
		expect(input.endsWith('…')).toBe(true);
	});
});
