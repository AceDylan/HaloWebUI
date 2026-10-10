// New-chat landing page: the models dealt out as cards; a tap picks the model, the chosen one
// is marked, hidden models stay out and pinned ones lead.
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { installDominoDom } from '$lib/test-support/domino-dom';

installDominoDom('http://localhost/');

let Deck: any;
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
	model('gpt-chat'),
	model('deepseek-chat'),
	model('gpt-image'),
	model('hermes-agent', { original_id: 'hermes-agent' }),
	model('gemini-chat'),
	model('claude-chat'),
	model('answer-1', { info: { meta: { hidden: true } } })
];

beforeAll(async () => {
	stores = await import('$lib/stores');
	Deck = (await import('./ModelDeck.svelte')).default;
}, 60000);

afterEach(() => {
	apps.splice(0).forEach((app) => app.$destroy());
	document.body.innerHTML = '';
});

const mount = (props: Record<string, unknown>) => {
	const target = document.createElement('div');
	document.body.appendChild(target);
	const app = new Deck({ target, props });
	apps.push(app);
	return { target, app };
};

describe('ModelDeck', () => {
	it('deals every visible model, pinned first, and picks one on tap', async () => {
		stores.models.set(MODELS);
		stores.config.set({ hermes_agent_model_ids: ['hermes-agent'] });
		stores.settings.set({ pinnedModels: [MODELS[3].selection_id] });
		const onSelect = vi.fn();
		const { target, app } = mount({ selected: MODELS[3], onSelect });
		await Promise.resolve();

		const cards = [...target.querySelectorAll('[data-halo-model-card]')] as any[];
		expect(cards.map((c) => c.querySelector('.halo-deck__name').textContent)).toEqual([
			'hermes-agent',
			'gpt-chat',
			'deepseek-chat',
			'gpt-image',
			'gemini-chat',
			'claude-chat'
		]);
		expect(cards.map((c) => c.querySelector('.halo-deck__kind').textContent)).toEqual([
			'智能体',
			'对话',
			'对话',
			'生图',
			'对话',
			'对话'
		]);
		expect(cards.map((c) => c.getAttribute('aria-pressed'))).toEqual([
			'true',
			'false',
			'false',
			'false',
			'false',
			'false'
		]);
		// the out-prop the page binds (its own name line steps aside)
		expect(app.$$.ctx[app.$$.props.shows]).toBe(true);

		cards[5].click();
		expect(onSelect).toHaveBeenCalledWith(MODELS[5].selection_id);
		// the chosen card does not pick itself again
		cards[0].click();
		expect(onSelect).toHaveBeenCalledTimes(1);
	});

	it('shows nothing for a single model and says the choice is not on a card', async () => {
		stores.models.set([MODELS[0], MODELS[6]]);
		stores.settings.set({});
		const { target, app } = mount({ selected: MODELS[6], onSelect: () => {} });
		await Promise.resolve();
		expect(target.querySelector('[data-halo-model-deck]')).toBeFalsy();
		expect(app.$$.ctx[app.$$.props.shows]).toBe(false);
	});
});
