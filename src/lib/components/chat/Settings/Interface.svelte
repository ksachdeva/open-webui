<script lang="ts">	
	import { config, models, settings } from '$lib/stores';
	import { createEventDispatcher, onMount, getContext } from 'svelte';	
	const dispatch = createEventDispatcher();

	const i18n = getContext('i18n');

	export let saveSettings: Function;	

	// Addons	
	let widescreenMode = false;
	let splitLargeChunks = false;
	

	// Interface
	let defaultModelId = '';
	let showUsername = false;

	let chatBubble = true;
	let chatDirection: 'LTR' | 'RTL' = 'LTR';	

	const togglewidescreenMode = async () => {
		widescreenMode = !widescreenMode;
		saveSettings({ widescreenMode: widescreenMode });
	};

	const toggleChatBubble = async () => {
		chatBubble = !chatBubble;
		saveSettings({ chatBubble: chatBubble });
	};

	const toggleShowUsername = async () => {
		showUsername = !showUsername;
		saveSettings({ showUsername: showUsername });
	};	

	const toggleChangeChatDirection = async () => {
		chatDirection = chatDirection === 'LTR' ? 'RTL' : 'LTR';
		saveSettings({ chatDirection });
	};

	const updateInterfaceHandler = async () => {
		saveSettings({
			models: [defaultModelId]
		});
	};

	onMount(async () => {
		showUsername = $settings.showUsername ?? false;		
		chatBubble = $settings.chatBubble ?? true;
		widescreenMode = $settings.widescreenMode ?? false;
		splitLargeChunks = $settings.splitLargeChunks ?? false;		
		chatDirection = $settings.chatDirection ?? 'LTR';	

		defaultModelId = $settings?.models?.at(0) ?? '';
		if ($config?.default_models) {
			defaultModelId = $config.default_models.split(',')[0];
		}		
	});
</script>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={() => {
		updateInterfaceHandler();
		dispatch('save');
	}}
>

	<div class=" space-y-3 pr-1.5 overflow-y-scroll max-h-[25rem] scrollbar-hidden">

		<div>
			<div class=" py-0.5 flex w-full justify-between">
				<div class=" self-center text-xs">{$i18n.t('Chat Bubble UI')}</div>

				<button
					class="p-1 px-3 text-xs flex rounded transition"
					on:click={() => {
						toggleChatBubble();
					}}
					type="button"
				>
					{#if chatBubble === true}
						<span class="ml-2 self-center">{$i18n.t('On')}</span>
					{:else}
						<span class="ml-2 self-center">{$i18n.t('Off')}</span>
					{/if}
				</button>
			</div>
		</div>

		{#if !$settings.chatBubble}
			<div>
				<div class=" py-0.5 flex w-full justify-between">
					<div class=" self-center text-xs">
						{$i18n.t('Display the username instead of You in the Chat')}
					</div>

					<button
						class="p-1 px-3 text-xs flex rounded transition"
						on:click={() => {
							toggleShowUsername();
						}}
						type="button"
					>
						{#if showUsername === true}
							<span class="ml-2 self-center">{$i18n.t('On')}</span>
						{:else}
							<span class="ml-2 self-center">{$i18n.t('Off')}</span>
						{/if}
					</button>
				</div>
			</div>
		{/if}

		<div>
			<div class=" py-0.5 flex w-full justify-between">
				<div class=" self-center text-xs">{$i18n.t('Widescreen Mode')}</div>

				<button
					class="p-1 px-3 text-xs flex rounded transition"
					on:click={() => {
						togglewidescreenMode();
					}}
					type="button"
				>
					{#if widescreenMode === true}
						<span class="ml-2 self-center">{$i18n.t('On')}</span>
					{:else}
						<span class="ml-2 self-center">{$i18n.t('Off')}</span>
					{/if}
				</button>
			</div>
		</div>

		<div>
			<div class=" py-0.5 flex w-full justify-between">
				<div class=" self-center text-xs">{$i18n.t('Chat direction')}</div>

				<button
					class="p-1 px-3 text-xs flex rounded transition"
					on:click={toggleChangeChatDirection}
					type="button"
				>
					{#if chatDirection === 'LTR'}
						<span class="ml-2 self-center">{$i18n.t('LTR')}</span>
					{:else}
						<span class="ml-2 self-center">{$i18n.t('RTL')}</span>
					{/if}
				</button>
			</div>
		</div>							
		
	</div>
	
</form>
