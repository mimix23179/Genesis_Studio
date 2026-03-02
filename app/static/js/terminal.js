(function () {
	"use strict";

	var term = null;
	var fitAddon = null;
	var ready = false;
	var lineBuffer = "";

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
		if (payload.type === "meta") {
			if (payload.workspace) setText("workspace_badge", payload.workspace);
			if (payload.shell) setText("shell_badge", payload.shell);
		}
		if (payload.type === "control" && payload.action === "close") {
			sendToHost({ type: "control", action: "close" });
		}
	};

	function setText(id, value) {
		var el = document.getElementById(id);
		if (!el) return;
		el.textContent = String(value || "");
	}

	function writeOutput(text) {
		if (term) term.write(String(text));
	}

	/* ── Bootstrap xterm ── */
	function bootstrap() {
		if (ready) return;
		var mount = document.getElementById("terminal");
		if (!mount) { setTimeout(bootstrap, 60); return; }

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
			if (payload.workspace) setText("workspace_badge", payload.workspace);
			if (payload.shell) setText("shell_badge", payload.shell);
			if (payload.welcome) term.writeln("\x1b[1;36m" + payload.welcome + "\x1b[0m");
			if (Array.isArray(payload.motd)) payload.motd.forEach(function (l) { term.writeln(String(l)); });
		}
		term.writeln("\x1b[2m" + "Interactive shell attached. Run commands directly in this terminal." + "\x1b[0m");
		term.writeln("");
		sendToHost({ type: "terminal.ready" });

		/* Click to focus terminal */
		mount.addEventListener("click", function () { if (term) term.focus(); });

		/* Keyboard -> shell input */
		term.onData(function (data) {
			if (data === "\r") {
				var cmd = lineBuffer;
				lineBuffer = "";
				term.write("\r\n");
				sendToHost({ type: "input", data: cmd });
				return;
			}

			if (data === "\u007f") {
				if (lineBuffer.length > 0) {
					lineBuffer = lineBuffer.slice(0, -1);
					term.write("\b \b");
				}
				return;
			}

			if (data && data.charCodeAt(0) === 3) {
				lineBuffer = "";
				term.write("^C\r\n");
				sendToHost({ type: "input", data: "" });
				return;
			}

			if (data >= " " && data !== "\u007f" && !data.startsWith("\u001b")) {
				lineBuffer += data;
				term.write(data);
			}
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
		term.focus();
	}

	ensureXterm(bootstrap);
})();
