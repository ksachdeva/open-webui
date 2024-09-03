<script lang="ts">
	import hljs from 'highlight.js';	
	import mermaid from 'mermaid';

	import { v4 as uuidv4 } from 'uuid';

	import { getContext, onMount } from 'svelte';
	import { copyToClipboard } from '$lib/utils';

	import 'highlight.js/styles/github-dark.min.css';	

	const i18n = getContext('i18n');

	export let id = '';

	export let token;
	export let lang = '';
	export let code = '';

	let mermaidHtml = null;

	let highlightedCode = null;
	let executing = false;

	let stdout = null;
	let stderr = null;
	let result = null;

	let copied = false;

	const copyCode = async () => {
		copied = true;
		await copyToClipboard(code);

		setTimeout(() => {
			copied = false;
		}, 1000);
	};	

	let debounceTimeout;

	const drawMermaidDiagram = async () => {
		try {
			const { svg } = await mermaid.render(`mermaid-${uuidv4()}`, code);
			mermaidHtml = svg;
		} catch (error) {
			console.log('Error:', error);
		}
	};

	$: if (token.raw) {
		if (lang === 'mermaid' && (token?.raw ?? '').slice(-4).includes('```')) {
			(async () => {
				await drawMermaidDiagram();
			})();
		} else {
			// Function to perform the code highlighting
			const highlightCode = () => {
				highlightedCode = hljs.highlightAuto(code, hljs.getLanguage(lang)?.aliases).value || code;
			};

			// Clear the previous timeout if it exists
			clearTimeout(debounceTimeout);
			// Set a new timeout to debounce the code highlighting
			debounceTimeout = setTimeout(highlightCode, 10);
		}
	}

	onMount(async () => {
		if (document.documentElement.classList.contains('dark')) {
			mermaid.initialize({
				startOnLoad: true,
				theme: 'dark',
				securityLevel: 'loose'
			});
		} else {
			mermaid.initialize({
				startOnLoad: true,
				theme: 'default',
				securityLevel: 'loose'
			});
		}
	});
</script>

<div class="my-2" dir="ltr">
	{#if lang === 'mermaid'}
		{#if mermaidHtml}
			{@html `${mermaidHtml}`}
		{:else}
			<pre class="mermaid">{code}</pre>
		{/if}
	{:else}
		<div
			class="flex justify-between bg-[#202123] text-white text-xs px-4 pt-1 pb-0.5 rounded-t-lg overflow-x-auto"
		>
			<div class="p-1">{lang}</div>

			<div class="flex items-center">				
				<button class="copy-code-button bg-none border-none p-1" on:click={copyCode}
					>{copied ? $i18n.t('Copied') : $i18n.t('Copy Code')}</button
				>
			</div>
		</div>

		<pre
			class=" hljs p-4 px-5 overflow-x-auto"
			style="border-top-left-radius: 0px; border-top-right-radius: 0px; {(executing ||
				stdout ||
				stderr ||
				result) &&
				'border-bottom-left-radius: 0px; border-bottom-right-radius: 0px;'}"><code
				class="language-{lang} rounded-t-none whitespace-pre"
				>{#if highlightedCode}{@html highlightedCode}{:else}{code}{/if}</code
			></pre>

		<div
			id="plt-canvas-{id}"
			class="bg-[#202123] text-white max-w-full overflow-x-auto scrollbar-hidden"
		/>

		{#if executing}
			<div class="bg-[#202123] text-white px-4 py-4 rounded-b-lg">
				<div class=" text-gray-500 text-xs mb-1">STDOUT/STDERR</div>
				<div class="text-sm">Running...</div>
			</div>
		{:else if stdout || stderr || result}
			<div class="bg-[#202123] text-white px-4 py-4 rounded-b-lg">
				<div class=" text-gray-500 text-xs mb-1">STDOUT/STDERR</div>
				<div class="text-sm">{stdout || stderr || result}</div>
			</div>
		{/if}
	{/if}
</div>
