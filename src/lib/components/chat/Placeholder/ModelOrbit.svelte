<script lang="ts">
	/**
	 * The landing page's models as an orbit: the agent (Hermes) is the core in the middle and the
	 * other models ride an ellipse around it as holographic nodes, each tied to the core by a link.
	 * One tap picks the model for the new chat (the menu top left stays the full list). The chosen
	 * node lights up and its link carries a current; on a change a light runs along the orbit from
	 * the old node to the new one and the core sends out a ring. The greeting goes in the slot.
	 * Geometry: utils/model-orbit.ts. Styles: halo-orbit.css (the core reuses halo.css's .halo-orb).
	 */
	import { config, models as _models, settings } from '$lib/stores';
	import ModelIcon from '$lib/components/common/ModelIcon.svelte';
	import HudReactor from '$lib/components/scifi/HudReactor.svelte';
	import Photo from '$lib/components/icons/Photo.svelte';
	import { getModelBaseName, getModelConnectionName } from '$lib/utils/model-display';
	import { getModelSelectionId } from '$lib/utils/model-identity';
	import { modelDeck, modelDeckKind, type DeckKind } from '$lib/utils/model-deck';
	import {
		isMonoIcon,
		orbitAccent,
		orbitArc,
		orbitFrame,
		orbitGreetingWidth,
		orbitLabelSide,
		orbitLink,
		orbitPoint,
		orbitSlots
	} from '$lib/utils/model-orbit';

	/** The model the new chat will use (resolved), or null. */
	export let selected: any = null;
	export let onSelect: (selectionId: string) => void;
	/** Out: the chosen model is on the orbit (the page then drops its own name line). */
	export let shows = false;

	const KIND_LABEL: Record<DeckKind, string> = { agent: '智能体', image: '生图', chat: '对话' };
	// a few motes drifting over the stage: [left %, top %, delay s]
	const MOTES = [
		[14, 22, 0],
		[27, 70, 1.6],
		[41, 12, 3.1],
		[63, 84, 0.8],
		[76, 18, 2.4],
		[88, 58, 4],
		[52, 46, 5.2]
	];

	$: cards = modelDeck($_models, $settings?.pinnedModels).map((model) => {
		const name = getModelBaseName(model);
		const kind = modelDeckKind(model, $config?.hermes_agent_model_ids);
		const icon =
			model?.info?.meta?.profile_image_url ?? (model as any)?.meta?.profile_image_url ?? '/static/favicon.png';
		return {
			id: getModelSelectionId(model),
			name,
			connection: getModelConnectionName(model),
			kind,
			accent: orbitAccent(`${name} ${model?.id ?? ''}`, kind),
			icon,
			mono: isMonoIcon(icon)
		};
	});
	// the agent is the core; without one, the first model is
	$: hubIndex = Math.max(0, cards.findIndex((card) => card.kind === 'agent'));
	$: hub = cards[hubIndex];
	$: satellites = cards.filter((_, index) => index !== hubIndex);

	$: selectedId = selected ? getModelSelectionId(selected) : '';
	$: shows = cards.some((card) => card.id === selectedId);

	// The stage's size drives the layout; until it is measured it lays out for a laptop, unseen.
	let w = 0;
	let h = 0;
	$: frame = orbitFrame(w || 860, h || 480, satellites.length);
	$: slots = orbitSlots(satellites.length);
	$: nodes = satellites.map((card, index) => {
		const angle = slots[index];
		const at = orbitPoint(frame, angle);
		return {
			...card,
			index,
			angle,
			x: at.x,
			y: at.y,
			side: orbitLabelSide(angle, frame.compact),
			link: orbitLink(frame, at)
		};
	});
	$: greetingWidth = orbitGreetingWidth(frame, slots);
	$: chosen = nodes.find((node) => node.id === selectedId) ?? null;

	// Pointer or keyboard on a node: its link brightens and the core answers.
	let hot = '';

	// A change of model: a light runs from the old node to the new one and the core rings once.
	let lastId = '';
	let surge = 0;
	let comet = '';
	$: if (w && selectedId !== lastId) {
		if (lastId) {
			const from = nodes.find((node) => node.id === lastId);
			comet = from && chosen ? orbitArc(frame, from.angle, chosen.angle) : '';
			surge += 1;
		}
		lastId = selectedId;
	}

	const pick = (id: string) => {
		if (id !== selectedId) onSelect(id);
	};
</script>

{#if cards.length > 0}
	<div
		class="halo-orbit"
		class:is-compact={frame.compact}
		class:is-measured={w > 0}
		class:is-hub-on={hub?.id === selectedId}
		data-hot={hot ? '' : undefined}
		style="--node: {frame.node}px"
		bind:clientWidth={w}
		bind:clientHeight={h}
		role="group"
		aria-label="选择模型"
		data-halo-model-orbit
	>
		<svg class="halo-orbit__map" viewBox="0 0 {frame.w} {frame.h}" aria-hidden="true">
			<defs>
				<linearGradient id="halo-orbit-ring" x1="0" y1="0" x2="1" y2="0">
					<stop offset="0" stop-color="var(--scifi-cyan)" />
					<stop offset="0.5" stop-color="var(--scifi-violet)" />
					<stop offset="1" stop-color="var(--scifi-cyan)" />
				</linearGradient>
			</defs>
			<ellipse
				class="halo-orbit__ring halo-orbit__ring--far"
				cx={frame.cx}
				cy={frame.cy}
				rx={frame.rx + 22}
				ry={frame.ry + 12}
			/>
			<ellipse class="halo-orbit__ring" cx={frame.cx} cy={frame.cy} rx={frame.rx} ry={frame.ry} />
			<ellipse
				class="halo-orbit__current"
				cx={frame.cx}
				cy={frame.cy}
				rx={frame.rx}
				ry={frame.ry}
				pathLength="100"
			/>
			{#each nodes as node (node.id)}
				<g
					class="halo-orbit__link"
					class:is-on={node.id === selectedId}
					class:is-hot={node.id === hot}
					data-accent={node.accent}
				>
					<path class="halo-orbit__wire" d={node.link} />
					<path class="halo-orbit__flow" d={node.link} pathLength="100" />
					<circle class="halo-orbit__dock" cx={node.x} cy={node.y} r={frame.node / 2 + 7} />
				</g>
			{/each}
			{#key surge}
				{#if surge}
					{#if comet}
						<path class="halo-orbit__comet" d={comet} pathLength="100" />
					{/if}
					{#if chosen}
						<path class="halo-orbit__surge" data-accent={chosen.accent} d={chosen.link} pathLength="100" />
					{/if}
				{/if}
			{/key}
		</svg>

		<div class="halo-orbit__motes" aria-hidden="true">
			{#each MOTES as [left, top, delay]}
				<span style="left: {left}%; top: {top}%; animation-delay: -{delay}s"></span>
			{/each}
		</div>

		{#if hub}
			<div class="halo-orbit__hub" style="top: {frame.coreY - frame.core / 2}px">
				<div class="halo-orb halo-rise" style="--i: 0; --orb-size: {frame.core}px" data-halo-orb>
					<span class="halo-orb__bloom" aria-hidden="true"></span>
					<span class="halo-orb__ring" aria-hidden="true"></span>
					<span class="halo-orb__arc" aria-hidden="true"></span>
					<HudReactor />
					<span class="halo-orbit__echo" aria-hidden="true"></span>
					{#key surge}
						{#if surge}
							<span class="halo-orbit__wave" aria-hidden="true"></span>
						{/if}
					{/key}
					<button
						type="button"
						class="halo-orbit__core"
						aria-pressed={hub.id === selectedId}
						aria-label="{hub.name} · {KIND_LABEL[hub.kind]}"
						title={hub.connection ? `${hub.name} · ${hub.connection}` : hub.name}
						data-halo-model-card={hub.id}
						on:click={() => pick(hub.id)}
					>
						<ModelIcon src={hub.icon} alt="" className="size-full rounded-full" />
					</button>
				</div>
				<div class="halo-orbit__core-tag halo-rise" style="--i: 1" aria-hidden="true">
					<span class="halo-orbit__name">{hub.name}</span>
					<span class="halo-orbit__meta">
						<span class="halo-orbit__kind">{KIND_LABEL[hub.kind]}</span>
						{#if hub.connection}
							<span class="halo-chip halo-orbit__conn">{hub.connection}</span>
						{/if}
					</span>
				</div>
				<div class="halo-orbit__greeting" style="max-width: {greetingWidth}px">
					<slot />
				</div>
			</div>
		{/if}

		{#each nodes as node (node.id)}
			{@const on = node.id === selectedId}
			<button
				type="button"
				class="halo-orbit__node"
				class:is-on={on}
				data-accent={node.accent}
				data-side={node.side}
				style="left: {node.x}px; top: {node.y}px; --d: {node.index}"
				aria-pressed={on}
				aria-label="{node.name} · {KIND_LABEL[node.kind]}"
				title={node.connection ? `${node.name} · ${node.connection}` : node.name}
				data-halo-model-card={node.id}
				on:click={() => pick(node.id)}
				on:pointerenter={() => (hot = node.id)}
				on:pointerleave={() => (hot = '')}
				on:focus={() => (hot = node.id)}
				on:blur={() => (hot = '')}
			>
				<span class="halo-orbit__body">
					<span class="halo-orbit__float">
						<span class="halo-orbit__pad" aria-hidden="true"></span>
						<span class="halo-orbit__glow" aria-hidden="true"></span>
						<span class="halo-orbit__spin" aria-hidden="true"></span>
						<span class="halo-orbit__sphere">
							{#if node.mono}
								<span class="halo-orbit__glyph" style:--glyph={`url("${node.icon}")`}></span>
							{:else}
								<ModelIcon src={node.icon} alt="" bare className="halo-orbit__icon rounded-full" />
							{/if}
						</span>
						{#if node.kind === 'image'}
							<span class="halo-orbit__badge" aria-hidden="true"><Photo className="size-full" /></span>
						{/if}
					</span>
				</span>
				<span class="halo-orbit__tag" aria-hidden="true">
					<span class="halo-orbit__name">{node.name}</span>
					<span class="halo-orbit__meta">
						<span class="halo-orbit__kind">{KIND_LABEL[node.kind]}</span>
						{#if node.connection}
							<span class="halo-chip halo-orbit__conn">{node.connection}</span>
						{/if}
					</span>
				</span>
			</button>
		{/each}
	</div>
{/if}
