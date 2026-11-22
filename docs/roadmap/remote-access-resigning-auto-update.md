# SideLoader — Remote Access, Re-Signing & Auto-Update Roadmap

Planning date: November 22, 2026  
Repository: https://github.com/ssnanda/sideloader

## Vision

Transform SideLoader from a locally accessible signing and installation tool into a self-hosted, remotely accessible signing, refreshing, and updating service. It must preserve USB and local Wi-Fi support, reserve all three free-development app slots for custom apps, and require no sideloaded companion app.

Remote dashboard access and remote iPhone installation are separate capabilities. Tailscale provides private connectivity, but does not automatically make Apple discovery, pairing, lockdown, or installation protocols work remotely.

## Capability targets

| Capability | Current | Target |
| --- | --- | --- |
| Docker deployment on macOS | Working | Preserve |
| USB installation | Working | Preserve |
| Local Wi-Fi installation | Working | Preserve |
| Remote web dashboard | Not established | Tailscale |
| Remote iPhone installation | Unverified | Investigate |
| Remote re-signing | Not established | On demand |
| Background jobs | To review | Persistent |
| Automatic refresh | In development | Scheduled |
| Automatic app updates | Planned | Source-based |
| Companion iOS app | Not required locally | Not allowed |

## Phase 1 — Remote connectivity

Technical feasibility gate.

- [ ] Configure Tailscale on macOS and iPhone.
- [ ] Verify authenticated Docker dashboard access over cellular.
- [ ] Trace Apple pairing, lockdown, discovery, signing, and installation paths.
- [ ] Investigate direct paired-device targeting without Bonjour/mDNS.
- [ ] Test remote installation without an iOS companion app.
- [ ] Document limitations and select the viable architecture.

No remote installation automation should be enabled until this phase succeeds.

## Phase 2 — Remote dashboard

- [ ] Display connected and previously paired iPhones.
- [ ] Show installed apps, versions, and exact signing expiration.
- [ ] Keep certificate expiry separate from rolling App ID registration limits.
- [ ] Display connection and installation readiness.
- [ ] Provide history, diagnostics, Re-sign, and Re-sign All.
- [ ] Add a mobile-first PWA without consuming an app slot.

Unavailable Apple account information must never be fabricated.

## Phase 3 — Remote re-signing

- [ ] Persist signing and installation jobs after the browser closes.
- [ ] Expose authenticated dashboard, PWA, and Shortcuts triggers.
- [ ] Handle Apple ID verification through the web interface.
- [ ] Prevent overlapping jobs and unsafe retries.
- [ ] Preserve bundle identifiers and application data.

Signing an IPA may be possible without an active phone connection. Installing or refreshing it requires a proven device channel.

## Phase 4 — Automated refresh

- [x] Schedule installed apps when signing validity falls below six hours.
- [x] Process eligible app/device pairs sequentially.
- [x] Prevent automatic reinstallation of removed apps.
- [ ] Queue work while devices are unavailable.
- [ ] Resume when devices become reachable.
- [ ] Notify users about failures and approaching expiration.
- [ ] Validate remote installation before enabling remote automation.

## Phase 5 — Automatic application updates

- [ ] Check configured sources periodically.
- [ ] Compare installed and available versions.
- [ ] Download updated IPA files.
- [ ] Support per-app automatic or approval-required updates.
- [ ] Sign and install approved updates while preserving data and identity.
- [ ] Maintain update history and diagnostics.

## Android connectivity

- [x] When an authorized Android phone is connected by USB, detect its Wi-Fi address, enable ADB TCP mode, connect it, and remember it automatically.
- [ ] Clearly distinguish classic USB-authorized ADB-over-Wi-Fi from Android 11 TLS Wireless Debugging.
- [ ] Restore the remembered Wi-Fi connection after service restarts when the phone remains reachable.

## Architecture principles

- Keep the existing macOS Docker deployment.
- Use a private Tailscale network; require no public port forwarding.
- Protect credentials, pairing records, and signing material.
- Reuse existing pairing and installation components.
- Preserve USB and local Wi-Fi behavior.
- Do not assume Bonjour or multicast crosses a VPN.
- Do not add an iOS companion app.
- Treat remote device installation as a measured feasibility question.

## Immediate execution plan

Milestone 1 remains the feasibility assessment: review Docker networking and device communication, validate cellular dashboard access, test the paired-device transport, and record a go/no-go architecture decision.

## macOS menu bar

- [x] Create the source-only macOS menu-bar target.
- [x] Show local SideLoader reachability and dashboard shortcuts.
- [ ] Package and sign the helper as a macOS application.
- [ ] Add explicit Launch at Login control.
- [ ] Add an authenticated least-privilege local status channel for phone, job, and expiration details.
- [ ] Add renewal success and action-required notifications.

## Success criteria

1. Open SideLoader from an iPhone anywhere.
2. View installed apps and exact remaining validity.
3. Tap Re-sign All.
4. Let the Mac complete signing and installation in the background.
5. Eventually eliminate routine intervention with scheduled refreshes and source-based updates.
