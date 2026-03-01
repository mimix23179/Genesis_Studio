// Enhanced terminal loader using xterm.js from CDN
(function () {
	let scriptLoaded = false;

	function sendToHost(payload) {
		try {
			if (window.flutter_inappwebview && typeof window.flutter_inappwebview.callHandler === 'function') {
				window.flutter_inappwebview.callHandler('message', { payload });
			}
		} catch (e) { }
		try { window.parent.postMessage({ payload }, '*') } catch (e) { }
	}

	function loadScript(src, cb) {
		var s = document.createElement('script'); s.src = src; s.onload = cb; s.onerror = cb;
		document.head.appendChild(s);
	}

	function init() {
		if (typeof window.Terminal === 'undefined' || typeof window.FitAddon === 'undefined') {
			return setTimeout(init, 50);
		}

		const term = new window.Terminal({
			cursorBlink: true,
			fontSize: 14,
			fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
			theme: {
				background: 'transparent', // CSS handles the background glass effect
				foreground: '#e1e4ec',
				cursor: '#5c7cff',
				selection: 'rgba(92, 124, 255, 0.3)',
				black: '#1b1d23',
				red: '#ff4757',
				green: '#2ed573',
				yellow: '#ffa502',
				blue: '#5c7cff',
				magenta: '#a29bfe',
				cyan: '#7bed9f',
				white: '#e1e4ec'
			},
			allowTransparency: true
		});

		const fit = new window.FitAddon.FitAddon();
		term.loadAddon(fit);
		const termEl = document.getElementById('terminal');
		term.open(termEl);

		// Use a small delay for fit to ensure container dimensions are stable
		setTimeout(() => fit.fit(), 100);

		// handle resize
		window.addEventListener('resize', () => { try { fit.fit() } catch (e) { } });

		const input = document.getElementById('command_input');

		// Focus input on click anywhere in terminal
		termEl.addEventListener('click', () => input.focus());
		document.getElementById('terminal_wrap').addEventListener('click', () => input.focus());

		input.addEventListener('keydown', function (ev) {
			if (ev.key === 'Enter') {
				const v = input.value || '';
				input.value = '';
				if (v.trim()) {
					term.writeln('\x1b[1;34m❯\x1b[0m ' + v);
					sendToHost({ type: 'input', data: v });
				}
			}
		});

		// control buttons
		document.getElementById('clear_btn').addEventListener('click', () => term.clear());
		document.getElementById('copy_btn').addEventListener('click', () => {
			try { navigator.clipboard.writeText(term.buffer.active.translateToString()) } catch (e) { }
		});
		document.getElementById('close_btn').addEventListener('click', () => {
			sendToHost({ type: 'control', action: 'close' });
		});

		// handle messages from host
		window.addEventListener('message', (ev) => {
			const data = ev.data && (ev.data.payload || ev.data);
			if (!data) return;
			try {
				if (data.type === 'control') {
					const wrap = document.getElementById('terminal_wrap');
					if (data.action === 'open') {
						wrap.classList.add('open');
						setTimeout(() => { fit.fit(); input.focus(); }, 100);
					}
					if (data.action === 'close') {
						wrap.classList.remove('open');
					}
				} else if (data.type === 'output') {
					term.write(data.data || '');
				}
			} catch (e) { console.warn(e) }
		});

		// Handle initial payload if present
		if (window.__TERMINAL_PAYLOAD__ && window.__TERMINAL_PAYLOAD__.welcome) {
			term.writeln('\x1b[1;34m' + window.__TERMINAL_PAYLOAD__.welcome + '\x1b[0m');
		}

		// expose for debugging
		window.__genesis_terminal = { term, fit };
	}

	if (!scriptLoaded) {
		scriptLoaded = true;
		loadScript('https://cdn.jsdelivr.net/npm/xterm/lib/xterm.js', () => {
			loadScript('https://cdn.jsdelivr.net/npm/xterm-addon-fit/lib/xterm-addon-fit.js', init);
		});
	}
})();
