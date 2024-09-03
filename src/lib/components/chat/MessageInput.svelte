<script lang="ts">	
	import { onMount, tick, getContext } from 'svelte';

	import {
		type Model,
		mobile,
		settings,		
		models,		
		user as _user
	} from '$lib/stores';
	import {  findWordIndices } from '$lib/utils';	

	import {		
		WEBUI_BASE_URL,		
	} from '$lib/constants';
	
	import Commands from './MessageInput/Commands.svelte';
	import XMark from '../icons/XMark.svelte';

	const i18n = getContext('i18n');

	export let transparentBackground = false;

	export let submitPrompt: Function;
	
	export let autoScroll = false;

	export let atSelectedModel: Model | undefined;
	export let selectedModels: [''];
	

	let chatTextAreaElement: HTMLTextAreaElement;
	

	let commandsElement;

	
	let dragged = false;

	let user = null;
	let chatInputPlaceholder = '';	

	export let prompt = '';
	export let messages = [];

	
	$: if (prompt) {
		if (chatTextAreaElement) {
			chatTextAreaElement.style.height = '';
			chatTextAreaElement.style.height = Math.min(chatTextAreaElement.scrollHeight, 200) + 'px';
		}
	}

	const scrollToBottom = () => {
		const element = document.getElementById('messages-container');
		element.scrollTo({
			top: element.scrollHeight,
			behavior: 'smooth'
		});
	};

	

	onMount(() => {
		window.setTimeout(() => chatTextAreaElement?.focus(), 0);

		const dropZone = document.querySelector('body');

		const handleKeyDown = (event: KeyboardEvent) => {
			if (event.key === 'Escape') {
				console.log('Escape');
				dragged = false;
			}
		};

		const onDragOver = (e) => {
			e.preventDefault();
			dragged = true;
		};

		const onDragLeave = () => {
			dragged = false;
		};		

		window.addEventListener('keydown', handleKeyDown);

		dropZone?.addEventListener('dragover', onDragOver);		
		dropZone?.addEventListener('dragleave', onDragLeave);

		return () => {
			window.removeEventListener('keydown', handleKeyDown);

			dropZone?.removeEventListener('dragover', onDragOver);			
			dropZone?.removeEventListener('dragleave', onDragLeave);
		};
	});
</script>

<div class="w-full font-primary">
	<div class=" -mb-0.5 mx-auto inset-x-0 bg-transparent flex justify-center">
		<div class="flex flex-col max-w-6xl px-2.5 md:px-6 w-full">
			<div class="relative">
				{#if autoScroll === false && messages.length > 0}
					<div
						class=" absolute -top-12 left-0 right-0 flex justify-center z-30 pointer-events-none"
					>
						<button
							class=" bg-white border border-gray-100 dark:border-none dark:bg-white/20 p-1.5 rounded-full pointer-events-auto"
							on:click={() => {
								autoScroll = true;
								scrollToBottom();
							}}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 20 20"
								fill="currentColor"
								class="w-5 h-5"
							>
								<path
									fill-rule="evenodd"
									d="M10 3a.75.75 0 01.75.75v10.638l3.96-4.158a.75.75 0 111.08 1.04l-5.25 5.5a.75.75 0 01-1.08 0l-5.25-5.5a.75.75 0 111.08-1.04l3.96 4.158V3.75A.75.75 0 0110 3z"
									clip-rule="evenodd"
								/>
							</svg>
						</button>
					</div>
				{/if}
			</div>

			<div class="w-full relative">
				{#if atSelectedModel !== undefined}
					<div
						class="px-3 py-2.5 text-left w-full flex justify-between items-center absolute bottom-0.5 left-0 right-0 bg-gradient-to-t from-50% from-white dark:from-gray-900 z-10"
					>
						<div class="flex items-center gap-2 text-sm dark:text-gray-500">
							<img
								crossorigin="anonymous"
								alt="model profile"
								class="size-5 max-w-[28px] object-cover rounded-full"
								src={$models.find((model) => model.id === atSelectedModel.id)?.info?.meta
									?.profile_image_url ??
									($i18n.language === 'dg-DG'
										? `/doge.png`
										: `${WEBUI_BASE_URL}/static/favicon.png`)}
							/>
							<div>
								Talking to <span class=" font-medium">{atSelectedModel.name}</span>
							</div>
						</div>
						<div>
							<button
								class="flex items-center"
								on:click={() => {
									atSelectedModel = undefined;
								}}
							>
								<XMark />
							</button>
						</div>
					</div>
				{/if}

				<Commands
					bind:this={commandsElement}
					bind:prompt					
					on:select={(e) => {
						const data = e.detail;

						if (data?.type === 'model') {
							atSelectedModel = data.data;
						}

						chatTextAreaElement?.focus();
					}}
				/>
			</div>
		</div>
	</div>

	<div class="{transparentBackground ? 'bg-transparent' : 'bg-white dark:bg-gray-900'} ">
		<div class="max-w-6xl px-2.5 md:px-6 mx-auto inset-x-0">
			<div class=" pb-2">				
			
				<form
					class="w-full flex gap-1.5"
					on:submit|preventDefault={() => {
						// check if selectedModels support image input
						submitPrompt(prompt);
					}}
				>
					<div
						class="flex-1 flex flex-col relative w-full rounded-3xl px-1.5 bg-gray-50 dark:bg-gray-850 dark:text-gray-100"
						dir={$settings?.chatDirection ?? 'LTR'}
					>
						
						<div class=" flex">								

							<textarea
								id="chat-textarea"
								bind:this={chatTextAreaElement}
								class="scrollbar-hidden bg-gray-50 dark:bg-gray-850 dark:text-gray-100 outline-none w-full py-3 px-1 rounded-xl resize-none h-[48px]"
								placeholder={chatInputPlaceholder !== ''
									? chatInputPlaceholder
									: $i18n.t('Send a Message')}
								bind:value={prompt}
								on:keypress={(e) => {
									if (
										!$mobile ||
										!(
											'ontouchstart' in window ||
											navigator.maxTouchPoints > 0 ||
											navigator.msMaxTouchPoints > 0
										)
									) {
										// Prevent Enter key from creating a new line
										if (e.key === 'Enter' && !e.shiftKey) {
											e.preventDefault();
										}

										// Submit the prompt when Enter key is pressed
										if (prompt !== '' && e.key === 'Enter' && !e.shiftKey) {
											submitPrompt(prompt);
										}
									}
								}}
								on:keydown={async (e) => {
									const isCtrlPressed = e.ctrlKey || e.metaKey; // metaKey is for Cmd key on Mac
									const commandsContainerElement = document.getElementById('commands-container');

									// Check if Ctrl + R is pressed
									if (prompt === '' && isCtrlPressed && e.key.toLowerCase() === 'r') {
										e.preventDefault();
										console.log('regenerate');

										const regenerateButton = [
											...document.getElementsByClassName('regenerate-response-button')
										]?.at(-1);

										regenerateButton?.click();
									}

									if (prompt === '' && e.key == 'ArrowUp') {
										e.preventDefault();

										const userMessageElement = [
											...document.getElementsByClassName('user-message')
										]?.at(-1);

										const editButton = [
											...document.getElementsByClassName('edit-user-message-button')
										]?.at(-1);

										console.log(userMessageElement);

										userMessageElement.scrollIntoView({ block: 'center' });
										editButton?.click();
									}

									if (commandsContainerElement && e.key === 'ArrowUp') {
										e.preventDefault();
										commandsElement.selectUp();

										const commandOptionButton = [
											...document.getElementsByClassName('selected-command-option-button')
										]?.at(-1);
										commandOptionButton.scrollIntoView({ block: 'center' });
									}

									if (commandsContainerElement && e.key === 'ArrowDown') {
										e.preventDefault();
										commandsElement.selectDown();

										const commandOptionButton = [
											...document.getElementsByClassName('selected-command-option-button')
										]?.at(-1);
										commandOptionButton.scrollIntoView({ block: 'center' });
									}

									if (commandsContainerElement && e.key === 'Enter') {
										e.preventDefault();

										const commandOptionButton = [
											...document.getElementsByClassName('selected-command-option-button')
										]?.at(-1);

										if (e.shiftKey) {
											prompt = `${prompt}\n`;
										} else if (commandOptionButton) {
											commandOptionButton?.click();
										} else {
											document.getElementById('send-message-button')?.click();
										}
									}

									if (commandsContainerElement && e.key === 'Tab') {
										e.preventDefault();

										const commandOptionButton = [
											...document.getElementsByClassName('selected-command-option-button')
										]?.at(-1);

										commandOptionButton?.click();
									} else if (e.key === 'Tab') {
										const words = findWordIndices(prompt);

										if (words.length > 0) {
											const word = words.at(0);
											const fullPrompt = prompt;

											prompt = prompt.substring(0, word?.endIndex + 1);
											await tick();

											e.target.scrollTop = e.target.scrollHeight;
											prompt = fullPrompt;
											await tick();

											e.preventDefault();
											e.target.setSelectionRange(word?.startIndex, word.endIndex + 1);
										}

										e.target.style.height = '';
										e.target.style.height = Math.min(e.target.scrollHeight, 200) + 'px';
									}

									if (e.key === 'Escape') {
										console.log('Escape');
										atSelectedModel = undefined;
									}
								}}
								rows="1"
								on:input={async (e) => {
									e.target.style.height = '';
									e.target.style.height = Math.min(e.target.scrollHeight, 200) + 'px';
									user = null;
								}}
								on:focus={async (e) => {
									e.target.style.height = '';
									e.target.style.height = Math.min(e.target.scrollHeight, 200) + 'px';
								}}
								
							/>
							
						</div>
					</div>
					
				</form>
				

				<div class="mt-1.5 text-xs text-gray-500 text-center line-clamp-1">
					{$i18n.t('LLMs can make mistakes. Verify important information.')}
				</div>
			</div>
		</div>
	</div>
</div>

<style>
	.scrollbar-hidden:active::-webkit-scrollbar-thumb,
	.scrollbar-hidden:focus::-webkit-scrollbar-thumb,
	.scrollbar-hidden:hover::-webkit-scrollbar-thumb {
		visibility: visible;
	}
	.scrollbar-hidden::-webkit-scrollbar-thumb {
		visibility: hidden;
	}
</style>
