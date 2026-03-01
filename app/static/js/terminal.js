(function () {
	"use strict";

	var term = null;
	var fitAddon = null;
	var ready = false;

	/* ── Host bridge ── */
	function sendToHost(payload) {
		try {
			if (window.flutter_inappwebview && typeof window.flutter_inappwebview.callHandler === "function") {
				window.flutter_inappwebview.callHandler("message", JSON.stringify(payload));
			}
		} catch (_) {}
		try { window.parent.postMessage({ payload: payload }, "*"); } catch (_) {}
	}

	/* ── Dynamic script loader with fallback CDNs ── */
	function loadScript(urls, idx, done) {
		if (idx >= urls.length) { done(false); return; }
		var s = document.createElement("script");
		s.src = urls[idx];
		s.async = true;
		s.onload = function () { done(true); };
		s.onerror = function () { loadScript(urls, idx + 1, done); };
		document.head.appendChild(s);
	}

	function ensureXterm(callback) {
		if (window.Terminal && (window.FitAddon || (window.FitAddon = {}))) { callback(); return; }
		var xtermUrls = [
			"https://cdn.jsdelivr.net/npm/@xterm/xterm@5/lib/xterm.js",
			"https://cdn.jsdelivr.net/npm/xterm@5/lib/xterm.js",
			"https://unpkg.com/@xterm/xterm@5/lib/xterm.js"
		];
		var fitUrls = [
			"https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0/lib/addon-fit.js",
			"https://cdn.jsdelivr.net/npm/xterm-addon-fit@0/lib/xterm-addon-fit.js",
			"https://unpkg.com/@xterm/addon-fit@0/lib/addon-fit.js"
		];
		loadScript(xtermUrls, 0, function (ok) {
			if (!ok) { callback(); return; }
			loadScript(fitUrls, 0, function () { callback(); });
		});
	}

	/* ── Global receive function — called from Python via run_javascript ── */
	window.__genesis_receive = function (payload) {
		if (!payload || typeof payload !== "object") return;
		if (payload.type === "output") { writeOutput(payload.data || ""); }
		if (payload.type === "control" && payload.action === "close") {
			sendToHost({ type: "control", action: "close" });
		}
	};

	function writeOutput(text) {
		if (term) term.write(String(text));
	}

	/* ── Bootstrap xterm ── */
	function bootstrap() {
		if (ready) return;
		var mount = document.getElementById("terminal");
		var input = document.getElementById("command_input");
		if (!mount || !input) { setTimeout(bootstrap, 60); return; }

		if (!window.Terminal) {
			mount.innerHTML = '<p style="color:#8892a4;padding:12px;font-size:12px;">xterm.js failed to load — check network.</p>';
			return;
		}

		ready = true;

		term = new window.Terminal({
			cursorBlink: true,
			fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', Consolas, monospace",
			fontSize: 13,
			lineHeight: 1.35,
			allowTransparency: true,
			theme: {
				background: "#0e1118",
				foreground: "#e7ebf3",
				cursor: "#818cf8",
				cursorAccent: "#0e1118",
				selectionBackground: "rgba(129, 140, 248, 0.28)",
				black: "#1a1d2e",
				red: "#f87171",
				green: "#34d399",
				yellow: "#fbbf24",
				blue: "#818cf8",
				magenta: "#c084fc",
				cyan: "#22d3ee",
				white: "#e7ebf3",
				brightBlack: "#4b5563",
				brightRed: "#fca5a5",
				brightGreen: "#6ee7b7",
				brightYellow: "#fde68a",
				brightBlue: "#a5b4fc",
				brightMagenta: "#d8b4fe",
				brightCyan: "#67e8f9",
				brightWhite: "#f9fafb"
			}
		});

		/* Fit addon */
		try {
			var FA = window.FitAddon || {};
			var AddonClass = FA.FitAddon || FA.default || FA;
			if (typeof AddonClass === "function") {
				fitAddon = new AddonClass();
				term.loadAddon(fitAddon);
			}
		} catch (_) {}

		term.open(mount);

		function doFit() { try { if (fitAddon) fitAddon.fit(); } catch (_) {} }
		setTimeout(doFit, 80);
		window.addEventListener("resize", doFit);
		new ResizeObserver(doFit).observe(mount);

		/* Welcome */
		var payload = window.__TERMINAL_PAYLOAD__;
		if (payload) {
			if (payload.welcome) term.writeln("\x1b[1;36m" + payload.welcome + "\x1b[0m");
			if (Array.isArray(payload.motd)) payload.motd.forEach(function (l) { term.writeln(String(l)); });
		}
		term.writeln("\x1b[2m" + "Type a command below or use the AI chat to interact with Genesis." + "\x1b[0m");

		/* Click to focus input */
		mount.addEventListener("click", function () { input.focus(); });

		/* Command input handling */
		input.addEventListener("keydown", function (e) {
			if (e.key !== "Enter") return;
			var cmd = (input.value || "").trim();
			input.value = "";
			if (!cmd) return;
			term.writeln("\x1b[1;35m❯\x1b[0m " + cmd);
			sendToHost({ type: "input", data: cmd });
		});

		/* Header buttons */
		var clearBtn = document.getElementById("clear_btn");
		var copyBtn = document.getElementById("copy_btn");
		var closeBtn = document.getElementById("close_btn");
		if (clearBtn) clearBtn.addEventListener("click", function () { if (term) term.clear(); });
		if (copyBtn) copyBtn.addEventListener("click", function () {
			try { navigator.clipboard.writeText(term ? (term.getSelection() || "") : ""); } catch (_) {}
		});
		if (closeBtn) closeBtn.addEventListener("click", function () {
			sendToHost({ type: "control", action: "close" });
		});

		/* Incoming messages from parent / postMessage bridge */
		window.addEventListener("message", function (ev) {
			var p = ev.data && (ev.data.payload || ev.data);
			if (!p || typeof p !== "object") return;
			window.__genesis_receive(p);
		});

		/* Expose for Python */
		window.__genesis_terminal = { term: term, fitAddon: fitAddon, writeOutput: writeOutput };
		input.focus();
	}

	ensureXterm(bootstrap);
})();
