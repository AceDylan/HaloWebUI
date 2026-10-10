<script lang="ts">
	/**
	 * The landing page's models dealt out as cards under the greeting: one tap picks the model
	 * for the new chat (the menu top left stays the full list). The chosen card wears the halo.
	 * Styles: halo.css (.halo-deck), scifi.css for the sci-fi layer.
	 */
	import { config, models as _models, settings } from '$lib/stores';
	import ModelIcon from '$lib/components/common/ModelIcon.svelte';
	import { getModelBaseName, getModelConnectionName } from '$lib/utils/model-display';
	import { getModelSelectionId } from '$lib/utils/model-identity';
	import { modelDeck, modelDeckKind, type DeckKind } from '$lib/utils/model-deck';

	/** The model the new chat will use (resolved), or null. */
	export let selected: any = null;
	export let onSelect: (selectionId: string) => void;
	/** Out: the chosen model has a card here (the page then drops its own name line). */
	export let shows = false;

	const KIND_LABEL: Record<DeckKind, string> = { agent: '智能体', image: '生图', chat: '对话' };

	$: cards = modelDeck($_models, $settings?.pinnedModels).map((model) => ({
		id: getModelSelectionId(model),
		model,
		name: getModelBaseName(model),
		connection: getModelConnectionName(model),
		kind: modelDeckKind(model, $config?.hermes_agent_model_ids)
	}));
	$: selectedId = selected ? getModelSelectionId(selected) : '';
	$: shows = cards.some((card) => card.id === selectedId);
	// One row up to six; more wrap into rows of four. Phones always use three columns.
	$: cols = cards.length <= 6 ? cards.length : 4;
	const COLS_CLASS: Record<number, string> = {
		2: '@xl:grid-cols-2',
		3: '@xl:grid-cols-3',
		4: '@xl:grid-cols-4',
		5: '@xl:grid-cols-5',
		6: '@xl:grid-cols-6'
	};
</script>

{#if cards.length > 0}
	<!-- the composer's own insets (MessageInput), so the row lines up with the prompt box -->
	<div class="mx-auto mt-5 w-full max-w-4xl px-2.5 sm:pl-[calc(2rem+54px)] sm:pr-9">
		<div
			class="halo-deck mx-auto grid w-full gap-2 @xl:gap-2.5 {cards.length < 3
				? 'grid-cols-2'
				: 'grid-cols-3'} {COLS_CLASS[cols] ?? ''}"
			style="max-width: {cols * 9.5}rem"
			role="group"
			aria-label="选择模型"
			data-halo-model-deck
		>
			{#each cards as card, index (card.id)}
				{@const isSelected = card.id === selectedId}
				<button
					type="button"
					class="halo-deck__card"
					class:is-selected={isSelected}
					style="--d: {index}; --fan: {(index - (cards.length - 1) / 2) * 2.4}deg"
					aria-pressed={isSelected}
					title={card.connection ? `${card.name} · ${card.connection}` : card.name}
					data-halo-model-card={card.id}
					on:click={() => {
						if (!isSelected) onSelect(card.id);
					}}
				>
					<span class="halo-deck__glint" aria-hidden="true"></span>
					{#if isSelected}
						<span class="halo-presence halo-deck__presence" aria-hidden="true"></span>
					{/if}
					<ModelIcon
						src={card.model?.info?.meta?.profile_image_url ??
							card.model?.meta?.profile_image_url ??
							'/static/favicon.png'}
						alt=""
						className="halo-deck__icon size-8 @xl:size-10 rounded-full"
					/>
					<span class="halo-deck__name">{card.name}</span>
					<span class="halo-deck__meta hidden @md:flex">
						<span class="halo-deck__kind">{KIND_LABEL[card.kind]}</span>
						{#if card.connection}
							<span class="halo-chip halo-deck__conn">{card.connection}</span>
						{/if}
					</span>
				</button>
			{/each}
		</div>
	</div>
{/if}
