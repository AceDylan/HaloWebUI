<script lang="ts">
	import { fade } from 'svelte/transition';
	import { toast } from 'svelte-sonner';

	import { getStalePins, refreshPin, type StalePin } from '$lib/apis/assistant-library';

	/** A chat keeps the version of an assistant it started with; when the assistant has moved on
	 * (upgraded by a workbench or by hand), say so and offer to switch this chat to the new one. */
	export let chatId = '';

	let stale: StalePin[] = [];
	let checked = '';
	let busy = false;

	const check = async (id: string) => {
		checked = id;
		stale = [];
		if (!id || id.startsWith('local:') || typeof localStorage === 'undefined' || !localStorage.token) return;
		try {
			const found = await getStalePins(localStorage.token, id);
			if (checked === id) stale = found;
		} catch {
			// a hint only
		}
	};
	$: if (chatId !== checked) check(chatId);

	const switchTo = async (pin: StalePin) => {
		if (busy) return;
		busy = true;
		try {
			await refreshPin(localStorage.token, chatId, pin.id);
			stale = stale.filter((p) => p.id !== pin.id);
			toast.success(`这个对话之后用「${pin.name}」的第 ${pin.current} 版`);
		} catch (e: any) {
			toast.error(e?.message || '切换失败');
		} finally {
			busy = false;
		}
	};
</script>

{#each stale as pin (pin.id)}
	<div
		class="mx-auto mb-2 flex w-full max-w-3xl flex-wrap items-center gap-x-2 gap-y-1 rounded-xl bg-gray-500/5 px-3 py-1.5 text-xs text-gray-600 dark:text-gray-300"
		transition:fade={{ duration: 120 }}
		data-assistant-version-notice={pin.id}
	>
		<span>
			助手「{pin.name}」已更新到第 {pin.current} 版，这个对话仍按开始时的{pin.pinned ? `第 ${pin.pinned} 版` : '设定'}回答。
		</span>
		<button
			type="button"
			class="font-medium text-gray-900 hover:underline disabled:opacity-40 dark:text-white"
			disabled={busy}
			on:click={() => switchTo(pin)}
			data-assistant-version-switch>改用新版</button
		>
		<button
			type="button"
			class="ml-auto text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
			aria-label="知道了"
			on:click={() => (stale = stale.filter((p) => p.id !== pin.id))}>×</button
		>
	</div>
{/each}
