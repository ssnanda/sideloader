# SideLoader (self-hosted)

A minimal, source-driven **three-app Wi-Fi renewal** manager for one iPhone with a **free Apple ID**, deployable on **macOS or Ubuntu**. Uses the MIT-licensed [Sideloop](https://github.com/filippofinke/sideloop) signing/refresh backend and adds an AltStore JSON source browser. You don't need AltStore or SideStore on the iPhone.

**Project:** https://github.com/ssnanda/sideloader  •  **Dashboard:** `http://SERVER-IP:38080`  •  **Sources:** `http://SERVER-IP:38080/sources`

## Three no-argument scripts

| Script | Default behavior |
|---|---|
| `./bin/pull-latest.sh` | Siftidy-style **stash → pull --rebase → restore** (including untracked edits). `-f` explicitly replaces local work, but leaves ignored `build/` untouched. If running from a ZIP, clone into `~/Projects/sideloader`. |
| `./bin/bump-version.sh` | Siftidy-style **patch/minor/major/build/custom/no-bump** menu, using `X.Y.Z+B` in `VERSION` and the highest published Git tag as a version floor. **Enter = patch**, **Enter = commit and push** with `[skip ci]`. Supports `--no-push`, `--yes`, `--no-bump`. |
| `./bin/build-docker.sh` | Siftidy-style local builder: check prerequisites, download Sideloop to ignored `build/sideloop/` if absent, patch/validate, build and start Docker. `--no-start` builds only; `--open` opens dashboard; `--logs` follows logs. |

All three scripts accept **no arguments**; defaults match the Siftidy workflow. Run the build script again after source updates to rebuild/restart. To stop it, use `docker compose` with the two files shown below, or Docker Desktop's container UI. Runtime state lives in **ignored** `build/sideloop/data/` and is never committed (Apple password, pairing data, IPA files).

## Workflow and local build isolation

- **Pull:** by default, preserve staged, unstaged, and untracked edits using an autostash, rebase on the current branch, then restore edits. On conflicts, stop rather than overwrite. `-f` intentionally discards local changes and unpushed commits; ignored Docker build data remains.
- **Bump:** stores version as `X.Y.Z+B` (starting `0.1.1+1`). Press Enter twice to choose patch and confirm commit/push. The remote branch is synchronized through `pull-latest.sh` before pushing. The `build/` directory and secrets are ignored.
- **Build:** fetches no SideLoader GitHub changes, creates no release, and publishes no Docker image. Upstream Sideloop code, generated container data, phone pairing, settings and IPA cache are in `build/sideloop/`, never GitHub. The `--no-start` flag builds without restarting containers.

## First install on Ubuntu

1. Install Docker Engine with the Docker Compose v2 plugin, `git` and `python3`. Confirm your user can run Docker, or run the script from a Docker-authorized account.
2. Clone the repository to your preferred directory, then run `./bin/build-docker.sh` without arguments.
3. Open `http://localhost:38080` on the server. Set a strong dashboard password **before** entering any Apple ID credentials.
4. Connect iPhone to Ubuntu by USB, tap **Trust**, follow the dashboard pairing instructions, add the phone and use a dedicated Apple ID with 2FA.
5. Browse to `http://SERVER-IP:38080/sources`; paste a published AltStore source JSON URL, such as `https://example.com/altstore.json` (HTTPS by default). Click Install on up to three apps.
6. Once you have a successful first install, unplug the phone and check Wi-Fi discovery and refresh. In Settings, leave **automatic check** enabled, with **renew 2 days before expiry** (default).

## First install on macOS

1. Install Docker Desktop **4.34+**, `git`, `python3`, and `socat` (`brew install socat`).
2. In Docker Desktop, open **Settings → Resources → Network → Enable host networking** and restart Docker Desktop. Enable Docker Desktop launch at login; keep your Mac awake while you expect renewals.
3. Clone the repository and run `./bin/build-docker.sh`. It installs a per-user LaunchAgent to forward macOS `usbmuxd` securely from `127.0.0.1:27015` into the Docker host networking stack.
4. Connect iPhone to your Mac over USB. Trust the Mac and in Finder turn on **Show this iPhone when on Wi-Fi**. Then follow the same dashboard and Sources steps above.

macOS Docker Desktop host networking works at TCP/UDP level; it is **not** full layer-2 access to the Mac's LAN. Initial pairing and Wi-Fi discovery on your specific iOS version must be verified.

## What “AltStore JSON source” means here

- **Reuse an existing JSON source URL**, no change to its `.ipa` hosting path or `downloadURL` is needed.
- Supports standard AltStore source `apps[]` entries with `bundleIdentifier` plus either a top-level `downloadURL` or a `versions[]` list.
- Selecting **Install** imports the referenced IPA to the local server, validates its bundle ID, and starts the signing/install job (if account/device are configured).
- Sideloop then renews its **locally cached IPA copy** over Wi-Fi; a new version published to the JSON feed is **not** auto-updated. Return to Sources and select **Update** to import the new IPA.
- HTTPS public URLs are enabled by default. To use LAN-hosted JSON/IPA, set `ALLOW_HTTP_SOURCES=1` and/or `ALLOW_PRIVATE_SOURCE_URLS=1` in `build/sideloop/.env` and rebuild/restart. **Enabling private URLs increases SSRF exposure.** Do not expose the dashboard to the public internet.

## Networking

The Docker container listens on TCP **38080**. Linux uses the upstream service's `network_mode: host`, and the UI itself listens on 38080. Mac uses opt-in Docker Desktop host networking and a loopback-only macOS USB mux relay. Docker's bundled anisette server is published **only** to the host loopback on TCP 6969. The relay is **only** on TCP 27015 loopback. Protect the dashboard with its password; allow 38080 on your trusted LAN only, and **never port-forward 38080** to the internet. The dashboard uses HTTP; use a VPN/reverse proxy with TLS if remote access is required.

Compose configuration (paths based on the checked-out SideLoader project):

- Ubuntu: `docker compose -f build/sideloop/docker-compose.yml -f deploy/ubuntu-host.yml ...`
- macOS: `docker compose -f build/sideloop/docker-compose.yml -f deploy/mac-host.yml ...`

For example, append `ps`, `logs -f`, `down`, or `up -d --build` to the command above. On macOS the USB relay is managed by `bin/lib/macos-relay.sh install|uninstall`.

## Constraints and transparency

- **No bypass** of Apple signing requirements. A free Apple ID has **7-day** provisioning profiles and **up to three active apps per device**; extensions consume additional limited App IDs. Automatic renewal is best-effort, **not permanent signing**.
- An iPhone must be reachable, normally unlocked, on the same network, and running a compatible iOS device service when a renewal happens. Test an actual seven-day cycle before relying on it.
- Some iOS 27 combinations may fail device discovery or signing as Apple interfaces change. The installer may not preserve data if the signing identity/bundle ID changes. Keep backups.
- Third-party Sideloop / AltServer-Linux receive your Apple ID credentials. Use a separate Apple ID and review their implementations.
- `bin/build-docker.sh` **does not silently update the upstream Sideloop checkout** on subsequent runs. Review it before updating. The upstream clone is intentionally ignored by Git.
- This project was checked with Bash syntax, Python compilation and local unit tests, **not** deployed or tested with a real iPhone or a Docker daemon here.

## Licensing

SideLoader's own added files are distributed under MIT (see `LICENSE`), and use the MIT-licensed Sideloop backend. Upstream dependencies retain their respective licenses.
