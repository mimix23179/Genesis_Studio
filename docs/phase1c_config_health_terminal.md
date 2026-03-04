# Phase 1C Implementation (Config, Health, Terminal)

## Completed

### 1. Central Runtime Config
- Added runtime settings loader in:
  - `app/config.py`
- Runtime config now includes:
  - `host`
  - `preferred_port`
  - `max_port_scan`
  - `db_path`
  - `ollama_base_url`
  - `model`
  - `request_timeout`
  - `preferred_shell`
- `GenesisStudioShell` now initializes runtime settings from `data/settings.json`.

### 2. Runtime Health Wiring
- Settings UI expanded with runtime controls in:
  - `app/ui/settings_page/view.py`
- Added:
  - model field
  - Ollama base URL field
  - timeout field
  - preferred shell selector
  - "Save Runtime" button
  - "Check Health" button
  - runtime status + health labels
- Shell now requests:
  - `runtime.info`
  - `runtime.health`
  during post-connect and on-demand from settings.

### 3. New Native ButterflyUI Terminal
- Replaced WebView terminal path with native controls:
  - `app/ui/terminal_container.py`
- Terminal now includes:
  - shell selector (`auto`, `pwsh`, `powershell`, `cmd`, `bash`, `zsh`, `sh`)
  - output pane
  - command input
  - run button
  - clear button
  - restart button
- No dependency on removed `app/html/*` or `app/static/*` terminal assets.

### 4. Shell Process Behavior (PowerShell + CMD)
- Upgraded terminal process manager:
  - `app/ui/terminal_process.py`
- Shell resolution now prioritizes Windows shells correctly.
- Added startup bootstrap behavior:
  - `cmd`: set UTF-8 codepage (`chcp 65001>nul`)
  - PowerShell variants: set UTF-8 output encoding
- Added restart support and active shell reporting.

## Compatibility
- Existing chat/session RPC flow remains intact.
- Runtime bridge now launches local runtime with configured model/base URL/timeout.
- Saved runtime settings are applied to bridge settings for future reconnects.

## Validation
- `python -m compileall app genesis` passed.
- Runtime settings load smoke test passed.
- Terminal process smoke test passed (`cmd` launch + command execution + stop).
