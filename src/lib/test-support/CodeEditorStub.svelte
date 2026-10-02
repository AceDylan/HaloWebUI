<script lang="ts">
	// Stand-in for common/CodeEditor.svelte in DOM mount tests: CodeMirror needs browser APIs
	// (getSelection, input handling) the test DOM does not have. Renders the code as text.
	export let value = '';
	export let id = '';
	export let lang = '';
</script>

<pre data-code-stub={lang} {id}>{value}</pre>
