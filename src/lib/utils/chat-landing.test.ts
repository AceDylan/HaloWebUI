import { describe, expect, it } from 'vitest';

import { takeLandingPrompt } from './chat-landing';

// The Bookmark Hub lands a question here as /?q=<prompt>&models=<model>; the
// question is taken once and removed from the address (see chat-landing.ts).
describe('takeLandingPrompt', () => {
	it('takes the question and leaves the address without it', () => {
		const taken = takeLandingPrompt(
			'https://halo.example/?q=%E4%BD%A0%E8%83%BD%E5%81%9A%E4%BB%80%E4%B9%88&models=modelref%3A%3Aopenai%3A%3Apersonal%3A%3Aid%3A13c104eb%3A%3Agpt-chat'
		);

		expect(taken?.prompt).toBe('你能做什么');
		// The model the Hub pinned survives, percent-encoding intact.
		expect(taken?.path).toBe(
			'/?models=modelref%3A%3Aopenai%3A%3Apersonal%3A%3Aid%3A13c104eb%3A%3Agpt-chat'
		);
		expect(new URL(taken!.path, 'https://halo.example').searchParams.get('models')).toBe(
			'modelref::openai::personal::id:13c104eb::gpt-chat'
		);
	});

	it('is one-shot: the address it hands back has nothing left to take', () => {
		const first = takeLandingPrompt('https://halo.example/?q=hello&models=gpt-chat');
		expect(first?.prompt).toBe('hello');

		const second = takeLandingPrompt(new URL(first!.path, 'https://halo.example').href);
		expect(second).toBeNull();
	});

	it('gives a bare / when the question was the only parameter', () => {
		expect(takeLandingPrompt('https://halo.example/?q=hi')).toEqual({ prompt: 'hi', path: '/' });
	});

	it('keeps the hash and the other parameters in place', () => {
		expect(takeLandingPrompt('https://halo.example/?temporary-chat=true&q=hi#x=1')).toEqual({
			prompt: 'hi',
			path: '/?temporary-chat=true#x=1'
		});
	});

	it('does nothing without a question', () => {
		expect(takeLandingPrompt('https://halo.example/')).toBeNull();
		expect(takeLandingPrompt('https://halo.example/?models=gpt-chat')).toBeNull();
		expect(takeLandingPrompt('https://halo.example/?q=')).toBeNull();
		expect(takeLandingPrompt('https://halo.example/c/abc')).toBeNull();
		expect(takeLandingPrompt('not a url')).toBeNull();
	});
});
