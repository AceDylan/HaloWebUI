<script lang="ts">
	import type { LEGACY_VIDEO_STYLES } from '$lib/utils/video-styles';
	export let preset: (typeof LEGACY_VIDEO_STYLES)[number];
	$: [bg, ink, accent] = preset.colors;
</script>

<!-- Small vector mood boards, not promises of a rendered frame. No assets or render jobs. -->
<svg viewBox="0 0 160 80" class="block w-full rounded-lg" aria-hidden="true">
	<rect width="160" height="80" rx="8" fill={bg} />
	{#if preset.key === 'product'}
		<rect x="22" y="13" width="116" height="55" rx="5" fill="white" stroke={ink} />
		<path d="M23 25h114M47 25v42" stroke={ink} opacity=".3" />
		<rect x="57" y="34" width="28" height="23" rx="3" fill={ink} opacity=".2" />
		<path d="M94 37h30M94 45h23M94 53h15" stroke={ink} stroke-width="3" />
		<path d="m106 48 3 17 4-6 7-2Z" fill={accent} />
	{:else if preset.key === 'line'}
		<path
			d="M18 57c25 0 12-36 31-36s-5 43 21 36 0-44 25-36 10 37 47 30"
			fill="none"
			stroke={ink}
			stroke-width="2.5"
			stroke-linecap="round"
		/>
		<path d="M25 65h47" stroke={accent} stroke-width="4" />
	{:else if preset.key === 'ascii'}
		<text x="18" y="37" font-family="monospace" font-size="16" font-weight="800" fill={ink}
			>{'{ . : # : . }'}</text
		>
		<text x="48" y="63" font-family="monospace" font-size="20" font-weight="700" fill={accent}
			>01 / 10</text
		>
	{:else if preset.key === 'ink' || preset.key === 'paper'}
		<circle cx="121" cy="22" r="9" fill={accent} />
		<path d="m0 66 38-43 24 29 31-37 67 59H0Z" fill={ink} opacity=".25" />
		<path d="m0 76 47-37 36 23 29-20 48 38H0Z" fill={ink} opacity=".6" />
		{#if preset.key === 'paper'}<path d="m0 79 58-17 41 13 61-13v18H0Z" fill={accent} />{/if}
	{:else if preset.key === 'film'}
		<rect x="20" y="9" width="120" height="62" fill={ink} />
		{#each [0, 1, 2, 3, 4, 5, 6, 7] as i}<rect
				x={26 + 14 * i}
				y="12"
				width="7"
				height="5"
				fill={bg}
			/><rect x={26 + 14 * i} y="63" width="7" height="5" fill={bg} />{/each}
		<rect x="34" y="24" width="92" height="32" fill="none" stroke={accent} /><text
			x="80"
			y="45"
			text-anchor="middle"
			font-family="serif"
			font-size="15"
			fill={bg}>CHAPTER I</text
		>
	{:else if preset.key === 'hud' || preset.key === 'blueprint'}
		{#each [20, 40, 60] as y}<path d={`M12 ${y}h136`} stroke={ink} opacity=".15" />{/each}
		{#each [20, 40, 60, 80, 100, 120, 140] as x}<path
				d={`M${x} 10v60`}
				stroke={ink}
				opacity=".15"
			/>{/each}
		{#if preset.key === 'hud'}<circle cx="61" cy="40" r="25" stroke={ink} fill="none" /><circle
				cx="61"
				cy="40"
				r="17"
				stroke={accent}
				stroke-width="3"
				stroke-dasharray="60 20"
				fill="none"
			/><path d="M100 23h30M100 34h20M100 45h25M100 56h16" stroke={ink} stroke-width="2" />
		{:else}<path
				d="m44 31 27-14 40 19v24L84 72 44 53Zm0 0 40 20 27-15M84 51v21M29 21v40m-5-40h10m-10 40h10"
				stroke={ink}
				fill="none"
			/><path d="M119 32h18M119 60h18" stroke={accent} />{/if}
	{:else if preset.key === 'synthwave'}
		<circle cx="80" cy="32" r="21" fill={ink} />
		{#each [43, 49, 60, 76] as y}<path d={`M0 ${y}h160`} stroke={accent} />{/each}
		{#each [-50, 15, 80, 145, 210] as x}<path d={`M80 40 ${x} 80`} stroke={accent} />{/each}
	{:else}
		<circle cx="49" cy="36" r="22" fill={ink} /><rect
			x="85"
			y="19"
			width="38"
			height="38"
			fill={accent}
			transform={preset.key === 'bauhaus' ? 'rotate(15 104 38)' : ''}
		/><path d="M26 68h105" stroke={ink} stroke-width="4" opacity=".4" />
	{/if}
</svg>
