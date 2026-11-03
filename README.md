# LMN516 WeChat Sender

Independent macOS WeChat text sending with the existing five-step keyboard workflow. No OCR, screenshots, coordinates, private WeChat APIs, or LMN516 private executables. Community project; not affiliated with Tencent.

## Requirements
macOS, desktop WeChat already logged in, Python 3.9+, Accessibility permission for your terminal or invoking host.

## Install
    python3 -m venv .venv
    . .venv/bin/activate
    python -m pip install .

## Dry run (does not send)
    lmn-wechat-sender send --contact "Example" --text "Hello" --dry-run

## Send (sends immediately)
    lmn-wechat-sender send --exact --contact "Example" --text "Hello"
    printf '%s' 'Hello' | lmn-wechat-sender send --contact "Example" --stdin

Use --stdin to avoid putting message text in shell history. An optional WECHAT_APP_PATH or --app-path specifies a custom application path.

## Workflow
1. Activate WeChat and Cmd+F; clear search and paste exact supplied contact.
2. Enter opens that conversation.
3. Cmd+A then Delete clears active composer.
4. Paste the unmodified message using the clipboard.
5. Enter once to attempt the send.

Each keyboard command checks that WeChat is frontmost. The program does **not** verify uniqueness of search results, identity of selected contact, client acceptance, delivery, or reading. Use a deliberate test contact first. The clipboard is overwritten, not restored.

## Results
- enter-dispatched-unverified: final Enter dispatched, delivery unverified.
- ambiguous-do-not-resend: Enter might have been dispatched. Never retry automatically.
- not-attempted: failed before final Enter.
- dry-run: no GUI actions occurred.

## Local one-time jobs
    lmn-wechat-sender schedule-once --after-minutes 10 --contact "Example" --text "Hello"
    lmn-wechat-sender schedule-once --at "2026-11-04T09:00:00+08:00" --contact "Example" --text "Hello"
    lmn-wechat-sender schedule-list
    lmn-wechat-sender schedule-cancel --id JOB_ID
    lmn-wechat-sender run-due --dry-run
    lmn-wechat-sender run-due

Scheduling stores a job only: invoke run-due periodically from a logged-in macOS user session using launchd or manually. Never run as root or on a headless machine. One-shot jobs are claimed before execution; failures are not auto-retried. Schedule files include plaintext messages, stored with mode 0600 in ~/Library/Application Support/lmn516-wechat-sender/.

## Tests
    python3 -m unittest discover -s tests -v

No real sends in tests. This code is standalone, not a modification to the existing M4 production controller; integration to an MCP endpoint is deliberately out of scope. Do not expose local sending through unauthenticated network endpoints. WeChat keyboard behavior can change across versions.
