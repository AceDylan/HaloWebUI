<script lang="ts">
	import { katexAutoRender } from '$lib/utils/katex-auto-render';

	// Already-sanitized markup for a raw HTML token. The action injects it and renders any
	// LaTeX delimiters it contains; `{@html ...}` must not be used here because KaTeX rewrites
	// the nodes Svelte tracks, which leaks a duplicated copy on every update.
	export let html: string = '';
</script>

<span class="contents" use:katexAutoRender={html}></span>
