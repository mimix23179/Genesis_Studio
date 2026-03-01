export type TerminalBridgeMessage =
	| { type: "input"; data: string }
	| { type: "output"; data: string }
	| { type: "control"; action: "open" | "close" }
	| { type: "editor.changed"; path: string; text: string }
	| { type: "editor.requestOpen"; path: string };

declare global {
	interface Window {
		flutter_inappwebview?: {
			callHandler?: (name: string, payload: unknown) => void;
		};
	}
}

export function sendToHost(message: TerminalBridgeMessage): void {
	try {
		window.flutter_inappwebview?.callHandler?.("message", { payload: message });
	} catch {
		// no-op for host without this bridge
	}

	try {
		window.parent.postMessage({ payload: message }, "*");
	} catch {
		// no-op for host without postMessage
	}
}
