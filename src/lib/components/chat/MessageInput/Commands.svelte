<script>
	import { createEventDispatcher } from 'svelte';
	
	const dispatch = createEventDispatcher();

	
	import Models from './Commands/Models.svelte';

	import { removeLastWordFromString } from '$lib/utils';
	

	export let prompt = '';
	
	let commandElement = null;

	export const selectUp = () => {
		commandElement?.selectUp();
	};

	export const selectDown = () => {
		commandElement?.selectDown();
	};

	let command = '';
	$: command = (prompt?.trim() ?? '').split(' ')?.at(-1) ?? '';

	

	
</script>

{#if command?.charAt(0) === '@'}
	<Models
		bind:this={commandElement}
		{command}
		on:select={(e) => {
			prompt = removeLastWordFromString(prompt, command);

			dispatch('select', {
				type: 'model',
				data: e.detail
			});
		}}
	/>
{/if}