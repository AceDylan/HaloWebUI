import { describe, expect, it } from 'vitest';

import {
	assistantArchived,
	assistantSource,
	assistantSourceKind,
	assistantVersion,
	changeSourceLabel,
	rowMeta,
	runHref,
	versionTimeline,
	workbenchHref
} from './assistant-library';

describe('library record of a workspace row', () => {
	it('reads meta at the top level or under info', () => {
		expect(rowMeta({ meta: { hidden: true } }).hidden).toBe(true);
		expect(rowMeta({ info: { meta: { hidden: true } } }).hidden).toBe(true);
	});

	it('takes the source from meta.assistant, an old 精答 record, or manual', () => {
		expect(assistantSource({ assistant: { source: 'team' } })).toBe('team');
		expect(assistantSourceKind({ assistant: { source: 'builtin:15' } })).toBe('builtin');
		expect(assistantSource({ answer_desk: { revisions: [{}, {}] } })).toBe('answer');
		expect(assistantVersion({ answer_desk: { revisions: [{}, {}] } })).toBe(3);
		expect(assistantSourceKind({})).toBe('manual');
		expect(assistantSourceKind({ assistant: { source: 'odd' } })).toBe('manual');
		expect(assistantVersion({ assistant: { version: 4 } })).toBe(4);
		expect(assistantArchived({ assistant: { archived: true } })).toBe(true);
	});
});

describe('links', () => {
	it('opens a workbench with the assistant and finds a run', () => {
		expect(workbenchHref('answer', 'model:a b')).toBe('/answer?assistant=model%3Aa%20b');
		expect(runHref('answer:c1')).toBe('/answer/c1');
		expect(runHref('discuss:c2:ask9')).toBe('/discuss/c2');
		expect(runHref('team:t1')).toBeNull();
		expect(runHref(null)).toBeNull();
		expect(changeSourceLabel('undo')).toBe('撤销');
		expect(changeSourceLabel('answer')).toBe('精答');
	});
});

describe('versionTimeline', () => {
	it('describes each version by the change that made it, newest first', () => {
		const entries = versionTimeline({
			id: 'm',
			name: 'Coder',
			editable: true,
			source: 'answer',
			domain: '',
			createdFor: { runRef: 'answer:c0', at: 100 },
			current: { version: 3, name: 'Coder', system: 'v3', description: '', at: 400 },
			revisions: [
				{ version: 2, at: 300, source: 'undo', runRef: 'answer:c2', change: '撤销这次升级', system: 'v2' },
				{ version: 1, at: 200, source: 'answer', runRef: 'answer:c1', change: '加了测试', system: 'v1' }
			]
		});
		expect(entries.map((e) => [e.version, e.current, e.source, e.change, e.runRef, e.at, e.system])).toEqual([
			[3, true, 'undo', '撤销这次升级', 'answer:c2', 300, 'v3'],
			[2, false, 'answer', '加了测试', 'answer:c1', 200, 'v2'],
			[1, false, 'answer', '创建', 'answer:c0', 100, 'v1']
		]);
	});

	it('leaves a version without a record of its making blank', () => {
		const entries = versionTimeline({
			id: 'm',
			name: 'X',
			editable: false,
			source: 'manual',
			domain: '',
			current: { version: 5, name: 'X', system: 's', description: '', at: 9 },
			revisions: [{ version: 4, at: 8, source: 'manual', change: '手动编辑', system: 'old' }]
		});
		expect(entries[1]).toMatchObject({ version: 4, source: '', change: '', at: null });
		expect(entries[0]).toMatchObject({ version: 5, source: 'manual', at: 8 });
	});
});
