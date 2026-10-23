<script lang="ts">
	import type { VIDEO_STYLES } from '$lib/utils/video-styles';
	export let preset: (typeof VIDEO_STYLES)[number];
	$: [bg, ink, accent] = preset.colors;
</script>

<!-- Small vector mood boards, not promises of a rendered frame. No assets or render jobs. -->
<svg viewBox="0 0 160 80" class="block w-full rounded-lg" aria-hidden="true">
	<rect width="160" height="80" rx="8" fill={bg} />
	{#if preset.key === 'news'}
		<path d="M25 18v44h112" fill="none" stroke={ink} opacity=".4" />
		{#each [22, 34, 45, 30] as h, i}<rect
				x={38 + i * 23}
				y={61 - h}
				width="14"
				height={h}
				rx="2"
				fill={i === 2 ? accent : ink}
			/>{/each}
	{:else if preset.key === 'product'}
		<rect x="22" y="13" width="116" height="55" rx="5" fill="white" stroke={ink} />
		<path d="M23 25h114M47 25v42" stroke={ink} opacity=".3" />
		<rect x="57" y="34" width="28" height="23" rx="3" fill={ink} opacity=".2" />
		<path d="M94 37h30M94 45h23M94 53h15" stroke={ink} stroke-width="3" />
		<path d="m106 48 3 17 4-6 7-2Z" fill={accent} />
	{:else if preset.key === 'isometric'}
		{#each [0, 1, 2] as i}<g transform={`translate(${38 + i * 30} ${29 + (i % 2) * 12})`}>
				<path d="m0 0 22-12L44 0 22 12Z" fill={accent} /><path
					d="M0 0v19l22 12V12Z"
					fill={ink}
				/><path d="m22 12 22-12v19L22 31Z" fill={ink} opacity=".6" />
			</g>{/each}
	{:else if preset.key === 'whiteboard' || preset.key === 'line'}
		<path
			d={preset.key === 'line'
				? 'M18 57c25 0 12-36 31-36s-5 43 21 36 0-44 25-36 10 37 47 30'
				: 'M22 24h37v30H22Zm48 15h25m-7-7 8 7-8 7m16-19h32v27h-32Z'}
			fill="none"
			stroke={ink}
			stroke-width="2.5"
			stroke-linecap="round"
		/>
		<path d="M25 65h47" stroke={accent} stroke-width="4" />
	{:else if preset.key === 'type' || preset.key === 'ascii'}
		<text
			x="18"
			y="37"
			font-family={preset.key === 'ascii' ? 'monospace' : 'sans-serif'}
			font-size={preset.key === 'ascii' ? 16 : 28}
			font-weight="800"
			fill={ink}>{preset.key === 'ascii' ? '{ . : # : . }' : 'MAKE'}</text
		>
		<text x="48" y="63" font-family="monospace" font-size="20" font-weight="700" fill={accent}
			>{preset.key === 'ascii' ? '01 / 10' : 'IT MOVE'}</text
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
	{:else if preset.key === 'pixel'}
		<path d="M12 65h136M26 54h24v10H26Zm65-15h24v10H91Zm-28 6V30h9V20h13v10h9v15H63Z" fill={ink} />
		<rect x="111" y="20" width="9" height="9" fill={accent} /><rect
			x="70"
			y="31"
			width="5"
			height="5"
			fill={bg}
		/>
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
