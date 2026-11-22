# SideLoader Menu Bar

Initial source-only menu-bar iteration for macOS 13 or later.

Current scope:

- Poll the local SideLoader health endpoint every 30 seconds.
- Show online, offline, or checking state in the menu bar.
- Open Apps, Activity, Sources, and Roadmap.
- Perform no Apple authentication and start no signing job.

Next slices:

- Package as a signed `.app` and register it as a login item.
- Add an authenticated, least-privilege local status endpoint.
- Show connected phone, nearest signing expiry, active job and failures.
- Add notifications and explicitly confirmed actions.

The user owns compilation and runtime verification. From this directory:

```bash
swift build
swift run SideLoaderMenuBar
```
