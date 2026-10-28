undefined

## AltServer upstream links and local uninstaller (v0.2.0+15)

SideLoader uses the **maintained [jaakkopalvaila/AltServer-Linux NG branch](https://github.com/jaakkopalvaila/AltServer-Linux/tree/ng)**, not the older NyaMisty fork. The Apps dashboard displays the backend's actual Docker-built commit with **GitHub source** and **Recent commits** links immediately beside the revision, plus the existing **Check for updates** button. The pinned revision remains `5c32531fe0eb6ff87ed8f7b137da803c91945a02` until an upstream upgrade is reviewed and tested. GitHub source updates never change an installed Docker image on their own.

To **uninstall** the local SideLoader service on Mac or Ubuntu/Linux, run `./bin/uninstall.sh`. It stops and removes the dedicated `sideloop` Docker Compose containers (including its anisette container), and on Mac removes only SideLoader's own USB relay LaunchAgent. It **preserves** IPA files, device pairing, signing data, source lists and GitHub token, Compose volumes, and the Docker image, so reinstalling is possible without reconfiguring. It does **not** remove any app from your iPhone.

For a permanent local data wipe, run `./bin/uninstall.sh --purge-data` and type `DELETE` at the prompt. Alternatively, `./bin/uninstall.sh --purge-data --yes` explicitly confirms deletion without prompting. This permanently removes `build/sideloop/data/`, the upstream checkout's `.env` file, and the Compose project's anisette Docker volume. Use `--remove-image` to additionally delete the local `sideloop` Docker image (requires confirmation, or `--yes`). `./bin/uninstall.sh --purge-data --remove-image --yes` performs both cleanup options. The scripts do **not** remove your SideLoader Git checkout, the ignored upstream source checkout, unrelated images, or your iPhone's installed apps. Run the default uninstall before any data purge if you want to preserve a recoverable configuration.


## Build and version visibility (v0.2.0+16)

`./bin/pull-latest.sh` displays the **local and GitHub SideLoader versions and commit IDs before updating**, the changed-file summary, and both versions afterward. It preserves local commits, uncommitted changes, and ignored `build/` data; a successful pull never pushes. `./bin/pull-latest.sh --force` remains destructive and should only be used when you deliberately want to discard local work.

`./bin/build-docker.sh` applies the patches to the persistent upstream checkout and **then builds/restarts** the Docker container. A source-overlay migration failure before the Docker command does *not* rebuild the image. `./bin/build-docker.sh --no-cache` forces all image layers to rebuild from scratch; normal builds reuse unchanged Docker layers. The build prints a clear start message, the upstream Sideloop revision, and running container status.

The Apps page displays **Sideloop core** separately from AltServer-Linux: the Sideloop upstream Git commit (`filippofinke/sideloop`), the **SideLoader overlay version**, and a UTC preparation timestamp. This is an identifiable Git-based source revision, not an invented Sideloop semantic release version. It comes from a build manifest embedded in the Docker image so an old running container cannot report a newer checkout just because local files changed. Both original Sideloop source files and SideLoader overlay code contribute to the running app. The Step 1 navigation migration now safely detects already-upgraded four-step dashboards and no longer aborts on their newer labels.

## Pull script version report (v0.2.0+17)

`./bin/pull-latest.sh` always prints the local SideLoader version before contacting GitHub, then shows local/GitHub versions and commit IDs before and after synchronizing. It also reports changed files, preserves local commits/edits and ignored build data, and does not rebuild Docker or push to GitHub. If the updater script itself changes, it invokes the new version in read-only report mode to show the updated version immediately without another Git fetch or pull. `--force` remains explicitly destructive and never deletes ignored `build/` data.


## Existing-checkout installation workflow migration (v0.2.0+18)

`./bin/build-docker.sh` can be run repeatedly against the existing ignored `build/sideloop/` checkout. The Step 4 Install migration recognizes both the old dashboard's immediate closing template tag and the newer navigation overlay's separate closing line. It also recognizes the navigation overlay's `data-step-open="3"` control instead of expecting only `data-go="settings"`. Both layouts are validated before removing the duplicate install controls. If an unknown dashboard layout is encountered, the patch stops without writing a partially migrated index page. This fixes `Cannot safely locate duplicate install controls` without deleting IPAs, account information, pairing, or other runtime data. Four targeted regression tests cover both markup variants, repeat builds, JavaScript syntax, and safety checks.


## Responsive layout and Apple authentication status (v0.2.0+19)

The Apps screen uses a wider desktop layout and wraps AltServer-Linux version, GitHub source, recent commits, and update controls without overlapping at different browser zoom levels. The original mobile layout remains. The responsive patch runs on every build and is repeat-safe for existing `build/sideloop` checkouts.

AltServer error `-36607` is now classified explicitly as an **Apple authentication response** (possibly involving the configured anisette service), **not** proof that the Apple Account is locked or the password is wrong. After the first unsuccessful signing attempt, SideLoader's persistent guard continues blocking unattended and manual retries until explicitly resumed. The Activity log includes the actual Apple Account passed to AltServer. Avoid repeated attempts; verify the account in a browser and inspect the anisette configuration before intentionally resuming.
