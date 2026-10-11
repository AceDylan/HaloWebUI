// New-chat landing page: the agent is the core, the other models ride the orbit as nodes; a tap
// picks the model, the chosen one is marked, hidden models stay out and pinned ones lead.
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

let Orbit: any;
let stores: any;
const apps: any[] = [];

const model = (name: string, extra: Record<string, any> = {}) => ({
	id: `c1.${name}`,
	name,
	model_id: name,
	owned_by: 'openai',
	connection_name: name === 'hermes-agent' ? 'hermes' : 'cch',
	selection_id: `modelref::openai::personal::id:c1::${name}`,
	info: { meta: { profile_image_url: '/static/favicon.png' } },
	...extra
});
const MODELS = [
	model('gpt-chat', { info: { meta: { profile_image_url: '/static/model-icons/openai.svg' } } }),
	model('deepseek-chat'),
	model('gpt-image'),
	model('hermes-agent', { original_id: 'hermes-agent' }),
	model('gemini-chat'),
	model('claude-chat'),
	model('answer-1', { info: { meta: { hidden: true } } })
];

beforeAll(async () => {
	stores = await import('$lib/stores');
	Orbit = (await import('./ModelOrbit.svelte')).default;
}, 60000);

afterEach(() => {
	apps.splice(0).forEach((app) => app.$destroy());
	document.body.innerHTML = '';
});

const mount = (props: Record<string, unknown>) => {
	const target = document.createElement('div');
	document.body.appendChild(target);
	const app = new Orbit({ target, props });
	apps.push(app);
	return { target, app };
};

const text = (root: any, selector: string) =>
	[...root.querySelectorAll(selector)].map((el: any) => el.textContent);

describe('ModelOrbit', () => {
	it('puts the agent in the core, the rest on the orbit, and picks one on tap', async () => {
		stores.models.set(MODELS);
		stores.config.set({ hermes_agent_model_ids: ['hermes-agent'] });
		stores.settings.set({ pinnedModels: [MODELS[3].selection_id] });
		const onSelect = vi.fn();
		const { target, app } = mount({ selected: MODELS[3], onSelect });
		await Promise.resolve();

		expect(target.querySelector('.halo-orbit__core-tag .halo-orbit__name')?.textContent).toBe(
			'hermes-agent'
		);
		const nodes = [...target.querySelectorAll('.halo-orbit__node')] as any[];
		expect(text(target, '.halo-orbit__node .halo-orbit__name')).toEqual([
			'gpt-chat',
			'deepseek-chat',
			'gpt-image',
			'gemini-chat',
			'claude-chat'
		]);
		expect(text(target, '.halo-orbit__node .halo-orbit__kind')).toEqual([
			'对话',
			'对话',
			'生图',
			'对话',
			'对话'
		]);
		expect(nodes.map((n) => n.getAttribute('data-accent'))).toEqual([
			'gpt',
			'deepseek',
			'image',
			'gemini',
			'claude'
		]);
		// the one-colour OpenAI knot becomes a glyph in the node's colours; the image model wears a mark
		expect(nodes[0].querySelector('.halo-orbit__glyph')).toBeTruthy();
		expect(nodes.map((n) => !!n.querySelector('.halo-orbit__badge'))).toEqual([
			false,
			false,
			true,
			false,
			false
		]);
		// one link per node, none lit while the core is the chosen one
		expect(target.querySelectorAll('.halo-orbit__link')).toHaveLength(5);
		expect(target.querySelectorAll('.halo-orbit__link.is-on')).toHaveLength(0);
		const core = target.querySelector('.halo-orbit__core') as any;
		expect(core.getAttribute('aria-pressed')).toBe('true');
		expect(nodes.map((n) => n.getAttribute('aria-pressed'))).toEqual([
			'false',
			'false',
			'false',
			'false',
			'false'
		]);
		expect(app.$$.ctx[app.$$.props.shows]).toBe(true);

		nodes[4].click();
		expect(onSelect).toHaveBeenCalledWith(MODELS[5].selection_id);
		// the chosen one does not pick itself again
		core.click();
		expect(onSelect).toHaveBeenCalledTimes(1);

		app.$set({ selected: MODELS[5] });
		await Promise.resolve();
		expect(nodes[4].getAttribute('aria-pressed')).toBe('true');
		expect(nodes[4].classList.contains('is-on')).toBe(true);
		expect(
			[...target.querySelectorAll('.halo-orbit__link.is-on')].map((l: any) => l.getAttribute('data-accent'))
		).toEqual(['claude']);
		expect(core.getAttribute('aria-pressed')).toBe('false');
	});

	it('shows nothing for a single model and says the choice is not on the orbit', async () => {
		stores.models.set([MODELS[0], MODELS[6]]);
		stores.settings.set({});
		const { target, app } = mount({ selected: MODELS[6], onSelect: () => {} });
		await Promise.resolve();
		expect(target.querySelector('[data-halo-model-orbit]')).toBeFalsy();
		expect(app.$$.ctx[app.$$.props.shows]).toBe(false);
	});
});
