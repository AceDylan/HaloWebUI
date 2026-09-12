<script lang="ts">
	import { getContext, createEventDispatcher, onMount, tick } from 'svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;
	export let variables = [];

	let values = {};
	let inputRefs = {};

	const BUILTIN_VARS = [
		'CLIPBOARD',
		'USER_LOCATION',
		'USER_NAME',
		'USER_LANGUAGE',
		'CURRENT_DATE',
		'CURRENT_TIME',
		'CURRENT_DATETIME',
		'CURRENT_TIMEZONE',
		'CURRENT_WEEKDAY'
	];

	$: customVars = variables.filter((v) => !BUILTIN_VARS.includes(v.word));

	$: if (show && customVars.length > 0) {
		values = {};
		customVars.forEach((v) => {
			values[v.word] = values[v.word] ?? '';
		});
		tick().then(() => {
			const firstKey = customVars[0]?.word;
			if (firstKey && inputRefs[firstKey]) {
				inputRefs[firstKey].focus();
			}
		});
	}

	$: if (show && customVars.length === 0) {
		dispatch('confirm', {});
		show = false;
	}

	const handleConfirm = () => {
		// Normalize CRLF to LF for all values
		const normalized = {};
		for (const [k, v] of Object.entries(values)) {
			normalized[k] = typeof v === 'string' ? v.replace(/\r\n/g, '\n') : v;
		}
		dispatch('confirm', normalized);
		show = false;
	};

	const handleCancel = () => {
		dispatch('cancel');
		show = false;
	};

	const handleKeydown = (e, idx) => {
		if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
			e.preventDefault();
			if (idx < customVars.length - 1) {
				const nextKey = customVars[idx + 1]?.word;
				if (nextKey && inputRefs[nextKey]) {
					inputRefs[nextKey].focus();
				}
			} else {
				handleConfirm();
			}
		} else if (e.key === 'Escape') {
			handleCancel();
		}
	};
</script>

{#if show && customVars.length > 0}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		class="fixed inset-0 z-[999] flex items-center justify-center bg-black/50"
		on:click|self={handleCancel}
	>
		<div class="bg-white dark:bg-gray-900 rounded-2xl shadow-xl w-full max-w-md mx-4">
			<div class="px-5 py-4 border-b dark:border-gray-800">
				<h3 class="text-base font-semibold">{$i18n.t('Fill in Variables')}</h3>
				<p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
					{$i18n.t('Enter values for the template variables below.')}
				</p>
			</div>

			<div class="px-5 py-4 space-y-3 max-h-[50vh] overflow-y-auto">
				{#each customVars as variable, idx (variable.word)}
					<div>
						<label class="block text-sm font-medium mb-1" for="var-{variable.word}">
							{variable.word}
						</label>
						<textarea
							id="var-{variable.word}"
							bind:this={inputRefs[variable.word]}
							class="w-full px-3 py-2 rounded-lg border dark:border-gray-700 bg-transparent text-sm outline-none focus:ring-1 focus:ring-primary-500 resize-y min-h-[38px] max-h-[120px]"
							bind:value={values[variable.word]}
							on:keydown={(e) => handleKeydown(e, idx)}
							placeholder={variable.word}
							rows="1"
						/>
					</div>
				{/each}
			</div>

			<div class="flex justify-end gap-2 px-5 py-3 border-t dark:border-gray-800">
				<button
					class="px-4 py-1.5 text-sm rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition"
					on:click={handleCancel}
				>
					{$i18n.t('Cancel')}
				</button>
				<button
					class="px-4 py-1.5 text-sm rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition"
					on:click={handleConfirm}
				>
					{$i18n.t('Apply')}
				</button>
			</div>
		</div>
	</div>
{/if}
