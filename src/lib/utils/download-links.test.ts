import { describe, expect, it } from 'vitest';

import { getDataUrlDownloadName, rewriteDataUrlDownloadLinks } from './download-links';

describe('download-links', () => {
	it('turns data URLs into named downloads using the link label', () => {
		expect(
			getDataUrlDownloadName(
				'data:text/plain;charset=utf-8,%E4%BC%9A%E8%AE%AE',
				'下载会议纪要模板.txt'
			)
		).toBe('下载会议纪要模板.txt');

		expect(getDataUrlDownloadName('data:text/csv,a,b', 'sales')).toBe('sales.csv');
		expect(getDataUrlDownloadName('data:application/pdf;base64,AAAA', '')).toBe('download.pdf');
	});

	it('does not treat normal links as inline downloads', () => {
		expect(
			getDataUrlDownloadName('/api/v1/files/file-id/content?attachment=true', 'report.txt')
		).toBeNull();
		expect(getDataUrlDownloadName('https://example.com/report.txt', 'report.txt')).toBeNull();
	});

	it('sanitizes unsafe filename characters', () => {
		expect(getDataUrlDownloadName('data:text/plain,hello', '../bad:name.txt')).toBe(
			'.._bad_name.txt'
		);
	});

	it('rewrites data URL HTML anchors to downloads instead of new tabs', () => {
		const rewritten = rewriteDataUrlDownloadLinks(
			'<a href="data:text/plain;charset=utf-8,hello" target="_blank">会议纪要</a>'
		);

		expect(rewritten).toContain('download="download.txt"');
		expect(rewritten).not.toContain('target="_blank"');
	});
});
