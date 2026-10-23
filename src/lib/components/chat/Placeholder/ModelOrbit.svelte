<script lang="ts">
	/**
	 * The landing page's centred core and full ring of evenly spaced holographic models.
	 * Nodes, links and docks circle clockwise in 90 seconds, pausing on hover, focus or a swap;
	 * reduced motion keeps the initial angles. Labels stay below nodes, the greeting below
	 * the stage in normal flow. One tap picks the model for the new chat (the menu top left
	 * stays the full list) and the two trade places on screen: the picked node locks on, flies
	 * an arc into the core on a beam while the stars jump, the core flashes and rings out, and
	 * the old core flies back out to the empty seat. The core keeps its own name tag, with
	 * larger decorative reactor rings behind the seats and untruncated HUD read-outs.
	 * Geometry and seating: utils/model-orbit.ts. Styles: halo-orbit.css (the core's rings are
	 * halo.css's .halo-orb and scifi.css's reactor).
	 */
	import { onMount, tick } from 'svelte';
	import { config, models as _models, settings } from '$lib/stores';
	import ModelIcon from '$lib/components/common/ModelIcon.svelte';
	import HudReactor from '$lib/components/scifi/HudReactor.svelte';
	import Photo from '$lib/components/icons/Photo.svelte';
	import { hudClock } from '$lib/components/scifi/clock';
	import { warp } from '$lib/components/scifi/scifi';
	import { getModelBaseName, getModelConnectionName } from '$lib/utils/model-display';
	import { getModelSelectionId } from '$lib/utils/model-identity';
	import { modelDeck, modelDeckKind, modelDeckSize, type DeckKind } from '$lib/utils/model-deck';
	import {
		isMonoIcon,
		orbitAccent,
		orbitBend,
		orbitFrame,
		orbitLink,
		orbitOrder,
		orbitPoint,
		orbitSlots,
		seatModels,
		type OrbitFrame,
		type OrbitSeating
	} from '$lib/utils/model-orbit';

	/** The model the new chat will use (resolved), or null. */
	export let selected: any = null;
	export let onSelect: (selectionId: string) => void;
	/** Out: the chosen model is on the orbit (the page then drops its own name line). */
	export let shows = false;

	const KIND_LABEL: Record<DeckKind, string> = { agent: '智能体', image: '生图', chat: '对话' };
	const KIND_CODE: Record<DeckKind, string> = { agent: 'AGENT', image: 'IMAGE', chat: 'CHAT' };
	// a few motes drifting over the stage: [left %, top %, delay s]
	const MOTES = [
		[14, 22, 0],
		[27, 70, 1.6],
		[41, 12, 3.1],
		[63, 84, 0.8],
		[76, 18, 2.4],
		[88, 58, 4],
		[52, 46, 5.2],
		[8, 52, 2.9],
		[94, 30, 1.2]
	];
	// the swap: the picked node flies in, the old core flies out (ms)
	const FLIGHT_MS = 900;

	$: cards = modelDeck(
		$_models,
		$settings?.pinnedModels,
		modelDeckSize($settings?.modelOrbitCount)
	).map((model) => {
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
	$: byId = new Map(cards.map((card) => [card.id, card]));
	// the agent is the core when the chosen model is not on the orbit
	$: hubId = (cards.find((card) => card.kind === 'agent') ?? cards[0])?.id ?? '';

	$: selectedId = selected ? getModelSelectionId(selected) : '';
	$: shows = cards.some((card) => card.id === selectedId);
	$: target = shows ? selectedId : hubId;

	// The stage's size drives the layout; until it is measured it lays out for a laptop, unseen.
	let w = 0;
	let h = 0;
	$: frame = orbitFrame(w || 860, h || 480, Math.max(0, cards.length - 1));
	let spin = 0;
	$: slots = orbitSlots(Math.max(0, cards.length - 1)).map((angle) => angle + spin);

	let seating: OrbitSeating = { core: '', ring: [] };
	// reseat() changes `seating` inside a function, which Svelte does not see as a dependency:
	// it has to run before the statements below that read `seating` (source order decides)
	$: reseat(
		cards.map((card) => card.id),
		target
	);
	$: core = byId.get(seating.core) ?? null;
	$: links = seating.ring.map((id, k) => {
		const at = orbitPoint(frame, slots[k]);
		return { id, k, accent: byId.get(id)?.accent ?? 'plain', x: at.x, y: at.y, d: orbitLink(frame, at) };
	});

	/** Where a model sits now: centre and scale (the core is bigger); `depth` sizes the sphere
	 *  alone (the far side of the orbit a little smaller), so the labels keep their places. */
	// frame and angles are passed in (not closed over) so the template re-places on a resize
	const place = (id: string, seats: OrbitSeating, f: OrbitFrame, angles: number[]) => {
		if (id === seats.core) {
			return { x: f.cx, y: f.coreY, scale: f.core / f.node, depth: 1 };
		}
		const angle = angles[seats.ring.indexOf(id)] ?? 0;
		const at = orbitPoint(f, angle);
		const depth = Math.sin((angle * Math.PI) / 180);
		return { ...at, scale: 1, depth: 1 + depth * 0.06 };
	};
	const transformOf = (p: { x: number; y: number; scale: number }, f: OrbitFrame) =>
		`translate(${p.x - f.node / 2}px, ${p.y - f.node / 2}px) scale(${p.scale})`;

	let reduce =
		typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
	const reducedMotion = () => reduce;
	let flying = false;
	let swapVersion = 0;
	const flights = new Set<Animation>();

	onMount(() => {
		const media = window.matchMedia?.('(prefers-reduced-motion: reduce)');
		const motionChanged = () => {
			reduce = !!media?.matches;
			if (reduce) {
				spin = 0;
				flights.forEach((run) => run.cancel());
			}
		};
		motionChanged();
		media?.addEventListener('change', motionChanged);
		let raf = 0;
		let last: number | null = null;
		const advance = (now: number) => {
			if (reduce || hovered || hot || flying || !w || !h) {
				last = null;
			} else {
				// Discard hidden-tab time rather than catching up on a suspended orbit.
				if (last !== null) spin = (spin + Math.min(50, Math.max(0, now - last)) * 360 / 90000) % 360;
				last = now;
			}
			raf = requestAnimationFrame(advance);
		};
		raf = requestAnimationFrame(advance);
		return () => {
			cancelAnimationFrame(raf);
			media?.removeEventListener('change', motionChanged);
			swapVersion += 1;
			flights.forEach((run) => run.cancel());
		};
	});

	let seatEls: Record<string, HTMLElement> = {};
	// bumps once per swap: replays the beams, the flash and the rings, re-types the read-outs
	let surge = 0;
	let swapSlot = -1;

	const fly = (el: HTMLElement | undefined, from: any, to: any, bend: number, role: string) => {
		if (!el || typeof el.animate !== 'function') return;
		const mid = orbitBend(from, to, bend);
		const midScale = (from.scale + to.scale) / 2;
		const lift = role === 'is-arriving' ? 1.18 : 0.82;
		el.classList.add('is-flying', role);
		const run = el.animate(
			[
				{ transform: transformOf(from, frame), filter: 'brightness(1)' },
				{ transform: transformOf({ ...from, scale: from.scale * lift }, frame), filter: 'brightness(1.7)', offset: 0.2 },
				{ transform: transformOf({ ...mid, scale: midScale }, frame), filter: 'brightness(1.9) blur(1.2px)', offset: 0.62 },
				{ transform: transformOf(to, frame), filter: 'brightness(1)' }
			],
			{ duration: FLIGHT_MS, easing: 'cubic-bezier(0.65, 0, 0.25, 1)' }
		);
		flights.add(run);
		return new Promise<void>((resolve) => {
			const done = () => {
				flights.delete(run);
				el.classList.remove('is-flying', role);
				resolve();
			};
			run.onfinish = done;
			run.oncancel = done;
		});
	};

	const reseat = async (ids: string[], want: string) => {
		const next = seatModels(ids, want, seating, hubId);
		if (next === seating) return;
		const version = ++swapVersion;
		flights.forEach((run) => run.cancel());
		flying = false;
		const prev = seating;
		// a swap: only the old core and the new one changed seats
		const swapped =
			!!prev.core &&
			next.core !== prev.core &&
			next.ring.length === prev.ring.length &&
			next.ring.every((id, k) => id === prev.ring[k] || (id === prev.core && prev.ring[k] === next.core));
		const motion = swapped && w > 0 && h > 0 && !reducedMotion();
		flying = motion;
		const from = motion
			? { in: place(next.core, prev, frame, slots), out: place(prev.core, prev, frame, slots) }
			: null;
		seating = next;
		if (!swapped) return;
		swapSlot = next.ring.indexOf(prev.core);
		surge += 1;
		if (!from) return;
		warp(700);
		await tick();
		if (version !== swapVersion) return;
		if (!reduce) {
			await Promise.all([
				fly(seatEls[next.core], from.in, place(next.core, next, frame, slots), 0.22, 'is-arriving'),
				fly(seatEls[prev.core], from.out, place(prev.core, next, frame, slots), -0.22, 'is-leaving')
			]);
		}
		if (version === swapVersion) flying = false;
	};

	// Pointer or keyboard on a node: its link brightens and the core answers.
	// Any pointer over a node holds the orbit still; focus only on a ring node (a clicked button
	// keeps its focus as it becomes the core, which would otherwise hold the orbit for good).
	// Only ring nodes light up: the core has no link.
	let hovered = '';
	let focused = '';
	$: hot = [hovered, focused].find((id) => id && id !== seating.core) ?? '';

	const pick = (id: string) => {
		if (id !== selectedId) onSelect(id);
	};

	// Arrow keys walk round the orbit (core first, then clockwise from the top).
	const onKeydown = (event: KeyboardEvent) => {
		const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
		if (!step && event.key !== 'Home') return;
		const order = [seating.core, ...orbitOrder(slots).map((k) => seating.ring[k])];
		const at = order.findIndex((id) => seatEls[id]?.contains(document.activeElement));
		const next = event.key === 'Home' ? 0 : (Math.max(0, at) + (at < 0 ? 0 : (step ?? 0)) + order.length) % order.length;
		seatEls[order[next]]?.querySelector('button')?.focus();
		event.preventDefault();
	};

	// The core's name decodes itself when it changes (a few frames of glyph noise).
	const GLYPHS = '▚▞▙▟░▒▓<>/\\|=+*#01';
	const decode = (node: HTMLElement, text: string) => {
		let raf = 0;
		node.textContent = text;
		return {
			update(next: string) {
				if (next === text) return;
				text = next;
				if (typeof requestAnimationFrame !== 'function' || reducedMotion()) {
					node.textContent = next;
					return;
				}
				const start = performance.now();
				const frameStep = (now: number) => {
					const p = Math.min(1, (now - start) / 620);
					const shown = Math.floor(p * next.length);
					node.textContent =
						next.slice(0, shown) +
						[...next.slice(shown)].map(() => GLYPHS[(Math.random() * GLYPHS.length) | 0]).join('');
					if (p < 1) raf = requestAnimationFrame(frameStep);
				};
				cancelAnimationFrame(raf);
				raf = requestAnimationFrame(frameStep);
			},
			destroy() {
				if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(raf);
			}
		};
	};
</script>

{#if cards.length > 0}
	<div class="halo-orbit-layout" class:is-compact={frame.compact}>
		<div
			class="halo-orbit"
			class:is-compact={frame.compact}
			class:is-measured={w > 0 && h > 0}
			class:is-dense={frame.ringUnit < frame.unit}
			data-hot={hot ? '' : undefined}
			style="--node: {frame.node}px; --unit: {frame.unit}; --label-width: {frame.labelWidth}px; --label-height: {frame.labelHeight}px; --label-gap: {frame.labelGap}px; --core-halo: {frame.coreHalo}px; --core-tag-height: {frame.coreTagHeight}px; --core-tag-width: {frame.core + 2 * frame.coreHalo}px"
			bind:clientWidth={w}
			bind:clientHeight={h}
			role="toolbar"
			aria-label="选择模型"
			tabindex="-1"
			on:keydown={onKeydown}
			data-halo-model-orbit
		>
			<svg class="halo-orbit__map" viewBox="0 0 {frame.w} {frame.h}" aria-hidden="true">
				<defs>
					<!-- the far side of the ring is dimmer than the near side -->
					<linearGradient id="halo-orbit-ring" x1="0" y1="0" x2="0" y2="1">
						<stop offset="0" stop-color="var(--scifi-violet)" stop-opacity="0.35" />
						<stop offset="0.55" stop-color="var(--scifi-cyan)" stop-opacity="0.7" />
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
				{#each links as link (link.k)}
					<g class="halo-orbit__link" class:is-hot={link.id === hot} data-accent={link.accent}>
						<path class="halo-orbit__wire" d={link.d} />
						<path class="halo-orbit__flow" d={link.d} pathLength="100" style="animation-delay: -{link.k * 0.7}s" />
						<circle class="halo-orbit__dock" cx={link.x} cy={link.y} r={frame.node / 2 + 7} />
					</g>
				{/each}
				{#key surge}
					{#if surge && links[swapSlot]}
						<!-- the picked model rides in on a beam, the old core rides out on the same link -->
						<path class="halo-orbit__beam-in" data-accent={core?.accent} d={links[swapSlot].d} pathLength="100" />
						<path class="halo-orbit__surge" data-accent={links[swapSlot].accent} d={links[swapSlot].d} pathLength="100" />
						<ellipse
							class="halo-orbit__charge"
							cx={frame.cx}
							cy={frame.cy}
							rx={frame.rx}
							ry={frame.ry}
							pathLength="100"
						/>
					{/if}
				{/key}
			</svg>

			<div class="halo-orbit__motes" aria-hidden="true">
				{#each MOTES as [left, top, delay]}
					<span style="left: {left}%; top: {top}%; animation-delay: -{delay}s"></span>
				{/each}
			</div>

			<!-- HUD read-outs in the stage's corners -->
			<div class="halo-orbit__hud halo-orbit__hud--tl" aria-hidden="true">
				<b>SYS</b> ONLINE<br /><i>T+ {$hudClock}</i>
			</div>
			<div class="halo-orbit__hud halo-orbit__hud--tr" aria-hidden="true">
				<b>LINK</b> STABLE<br /><i>NODES {String(cards.length).padStart(2, '0')}<span class="halo-orbit__hud-detail"> · SYNC 100%</span></i>
			</div>
			{#key seating.core}
				{#if core}
					<div class="halo-orbit__hud halo-orbit__hud--bl" aria-hidden="true">
						<b>CORE</b> {KIND_CODE[core.kind]}<br /><i>{core.name}</i>
					</div>
					<div class="halo-orbit__hud halo-orbit__hud--br" aria-hidden="true">
						<b>ROUTE</b> {core.connection || 'LOCAL'}<br /><i>LOCKED · {surge ? 'RELAY' : 'IDLE'}</i>
					</div>
				{/if}
			{/key}

			<!-- the core's rings stay in the middle; the models fly in and out of them -->
			<div class="halo-orbit__reactor" style="top: {frame.coreY - frame.core / 2}px" aria-hidden="true">
				<div class="halo-orb halo-rise" style="--i: 0; --orb-size: {frame.core}px" data-halo-orb>
					{#key seating.core}
						<span class="halo-orbit__corelight" data-accent={core?.accent} aria-hidden="true"></span>
					{/key}
					<span class="halo-orb__bloom" aria-hidden="true"></span>
					<span class="halo-orb__ring" aria-hidden="true"></span>
					<span class="halo-orb__arc" aria-hidden="true"></span>
					<HudReactor />
					<span class="halo-orbit__echo" aria-hidden="true"></span>
					{#key surge}
						{#if surge}
							<span class="halo-orbit__wave" aria-hidden="true"></span>
							<span class="halo-orbit__flash" data-accent={core?.accent} aria-hidden="true"></span>
						{/if}
					{/key}
				</div>
			</div>
			{#key surge}
				{#if surge}
					<span class="halo-orbit__flare" style="top: {frame.coreY}px" aria-hidden="true"></span>
				{/if}
			{/key}

			{#if core}
				<div class="halo-orbit__caption" style="top: {frame.coreY + frame.core / 2}px">
					<div class="halo-orbit__core-tag halo-rise" style="--i: 1" aria-hidden="true">
						<span class="halo-orbit__name" data-name={core.name} use:decode={core.name}></span>
						<span class="halo-orbit__meta">
							<span class="halo-orbit__kind">{KIND_LABEL[core.kind]}</span>
							{#if core.connection}
								<span class="halo-chip halo-orbit__conn">{core.connection}</span>
							{/if}
						</span>
					</div>
				</div>
			{/if}

			{#each cards as card, index (card.id)}
				{@const seat = place(card.id, seating, frame, slots)}
				{@const isCore = card.id === seating.core}
				{@const on = card.id === selectedId}
				<div
					class="halo-orbit__seat"
					class:is-core={isCore}
					class:is-back={!isCore && seat.y < frame.cy}
					data-accent={card.accent}
					style="transform: {transformOf(seat, frame)}; --d: {index}; --depth: {seat.depth}; --unit: {frame.ringUnit}"
					bind:this={seatEls[card.id]}
				>
					<button
						type="button"
						class="halo-orbit__node"
						class:is-on={on}
						aria-pressed={on}
						aria-label="{card.name} · {KIND_LABEL[card.kind]}"
						title={card.connection ? `${card.name} · ${card.connection}` : card.name}
						data-halo-model-card={card.id}
						on:click={() => pick(card.id)}
						on:pointerenter={() => (hovered = card.id)}
						on:pointerleave={() => (hovered = '')}
						on:focus={() => (focused = card.id)}
						on:blur={() => (focused = '')}
					>
						<span class="halo-orbit__body">
							<span class="halo-orbit__float">
								<span class="halo-orbit__pad" aria-hidden="true"></span>
								<span class="halo-orbit__beam" aria-hidden="true"></span>
								<span class="halo-orbit__glow" aria-hidden="true"></span>
								<span class="halo-orbit__spin" aria-hidden="true"></span>
								<span class="halo-orbit__sphere">
									{#if card.mono}
										<span class="halo-orbit__glyph" style:--glyph={`url("${card.icon}")`}></span>
									{:else}
										<ModelIcon src={card.icon} alt="" bare className="halo-orbit__icon rounded-full" />
									{/if}
									<span class="halo-orbit__scan" aria-hidden="true"></span>
								</span>
								{#if card.kind === 'image'}
									<span class="halo-orbit__badge" aria-hidden="true"><Photo className="size-full" /></span>
								{/if}
							</span>
						</span>
						<span class="halo-orbit__tag" aria-hidden="true">
							<span class="halo-orbit__name">{card.name}</span>
							<span class="halo-orbit__meta">
								<span class="halo-orbit__kind">{KIND_LABEL[card.kind]}</span>
								{#if card.connection}
									<span class="halo-chip halo-orbit__conn">{card.connection}</span>
								{/if}
							</span>
						</span>
					</button>
				</div>
			{/each}
		</div>
		<div class="halo-orbit__greeting"><slot /></div>
	</div>
{/if}
