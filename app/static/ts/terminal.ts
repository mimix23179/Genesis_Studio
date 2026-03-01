export type TerminalInputMessage = { type: "input"; data: string };
export type TerminalOutputMessage = { type: "output"; data: string };
export type TerminalControlMessage = { type: "control"; action: "open" | "close" };

export type TerminalBridgeMessage =
	| TerminalInputMessage
	| TerminalOutputMessage
	| TerminalControlMessage;

declare global {
	interface Window {
		flutter_inappwebview?: {
			callHandler?: (name: string, payload: unknown) => void;
		};
		__TERMINAL_PAYLOAD__?: {
			welcome?: string;
			motd?: string[];
		};
	}
}

export function sendToHost(message: TerminalBridgeMessage): void {
	try {
		window.flutter_inappwebview?.callHandler?.("message", { payload: message });
	} catch {
		// ignore bridge errors
	}

	try {
		window.parent.postMessage({ payload: message }, "*");
	} catch {
		// ignore postMessage errors
	}
}

export function createOutput(text: string): TerminalOutputMessage {
	return { type: "output", data: text };
}

export function createControl(action: "open" | "close"): TerminalControlMessage {
	return { type: "control", action };
}
