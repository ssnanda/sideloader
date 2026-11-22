undefined

## Android APK install (Apple/Android switch on Apps)

The top of **Apps** (`/#apps`) has an **Apple / Android** switch, remembered per browser. Apple keeps the existing flow unchanged.

**Android** installs signed `.apk` files with ADB, over a USB cable or Wi-Fi. It needs no Apple ID, re-signing or 7-day refresh.

1. **USB cable.** Turn on Developer options → **USB debugging**, plug in with a data cable, then accept **Allow USB debugging?** on the phone.
   - On macOS, Docker Desktop can't see USB devices. The container therefore uses the **Mac's adb server** (`SIDELOADER_ADB_SERVER=127.0.0.1:5037` in `deploy/mac-host.yml`), which `build-docker.sh` starts when Android platform-tools is installed.
   - If the Mac server isn't running, SideLoader falls back to an adb server inside the container (Wi-Fi only) and shows a hint.
   - On Linux, the container's own adb server sees USB through `/dev/bus/usb`.
2. **Wi-Fi (Android 11+, same network).** Open Developer options → **Wireless debugging** → **Pair device with pairing code**. Enter the pairing IP:port and the 6-digit code, then click **Pair**. Then enter the **IP address & port** from the main Wireless debugging screen and click **Connect**.
   - SideLoader remembers the phone and reconnects on later visits.
   - The connect port changes when Wireless debugging restarts; use **Reconnect** or enter the new port.
The Android side mirrors Apple's steps:

- **Step 1 · Connect your Android** lists phones (USB or Wi-Fi) with the two connection options above.
- **Step 2 · Apps** has a phone picker, **Scan Android** and **Add app**.
  - **Installed apps** lists sideloaded apps (not installed by a store). **Show store apps** lists everything.
  - Each installed app has **Uninstall** (after confirmation; this deletes its data). An **Update** button appears when a newer version is known.
- **Add app** opens two panels, like Apple:
  - **From Sources** lists Android entries from your saved `altstore.json` sources, plus `.apk` assets of each source repository's newest GitHub release (one row per download URL).
  - **Imported APKs** holds uploaded `.apk` files (**Import APK**).
- Installs run `adb install -r`, which keeps app data. Install refuses:
  - an APK whose package differs from its source listing;
  - an APK signed with a different key than the installed copy (uninstall that copy first).

Android entries in `altstore.json` go in a top-level `android` object (or list), or in an `android` object inside an iOS app entry:

```json
"android": {"name": "AJ Ops", "packageName": "com.itspector.ajops", "version": "1.3.15",
            "buildVersion": "118", "type": "apk",
            "downloadURL": "https://github.com/ssnanda/ajopsios/releases/download/android-latest/ajopsios.apk"}
```

`buildVersion` is the Android versionCode. It lets SideLoader show **Install**, **Update** or **Installed** without downloading the APK.

Implementation notes:

- The image gains Debian's `adb` package.
- The container's fallback adb server uses port 5038, so it never clashes with a host adb on 5037.
- The adb key, saved phones, imported APKs (`apks/`), extra repositories and APK metadata live in `build/sideloop/data/android/`. Rebuilds don't require re-pairing.
- GitHub release listings are cached for 5 minutes. **Refresh** forces a reload.
- The saved read-only GitHub token, if any, is used for private repositories.
- The overlay is `overlay/patch-android.py`, `android.py`, `android-ui.js` and `android.css`. Tests are in `tests/test_android.py`.

## AltServer upstream links and local uninstaller (v0.2.0+15)

SideLoader uses the **maintained [jaakkopalvaila/AltServer-Linux NG branch](https://github.com/jaakkopalvaila/AltServer-Linux/tree/ng)**, not the older NyaMisty fork. The Apps dashboard displays the backend's actual Docker-built commit with **GitHub source** and **Recent commits** links immediately beside the revision, plus the existing **Check for updates** button. The pinned revision remains `5c32531fe0eb6ff87ed8f7b137da803c91945a02` until an upstream upgrade is reviewed and tested. GitHub source updates never change an installed Docker image on their own.

To **uninstall** the local SideLoader service on Mac or Ubuntu/Linux, run `./bin/uninstall.sh`. It stops and removes the dedicated `sideloop` Docker Compose containers (including its anisette container), and on Mac removes only SideLoader's own USB relay LaunchAgent. It **preserves** IPA files, device pairing, signing data, source lists and GitHub token, Compose volumes, and the Docker image, so reinstalling is possible without reconfiguring. It does **not** remove any app from your iPhone.

For a permanent local data wipe, run `./bin/uninstall.sh --purge-data` and type `DELETE` at the prompt. Alternatively, `./bin/uninstall.sh --purge-data --yes` explicitly confirms deletion without prompting. This permanently removes `build/sideloop/data/`, the upstream checkout's `.env` file, and the Compose project's anisette Docker volume. Use `--remove-image` to additionally delete the local `sideloop` Docker image (requires confirmation, or `--yes`). `./bin/uninstall.sh --purge-data --remove-image --yes` performs both cleanup options. The scripts do **not** remove your SideLoader Git checkout, the ignored upstream source checkout, unrelated images, or your iPhone's installed apps. Run the default uninstall before any data purge if you want to preserve a recoverable configuration.


## Build and version visibility (v0.2.0+16)

`./bin/pull-latest.sh` displays the **local and GitHub SideLoader versions and commit IDs before updating**, the changed-file summary, and both versions afterward. It preserves local commits, uncommitted changes, and ignored `build/` data; a successful pull never pushes. `./bin/pull-latest.sh --force` remains destructive and should only be used when you deliberately want to discard local work.

`./bin/build-docker.sh` applies the patches to the persistent upstream checkout and **then builds/restarts** the Docker container. A source-overlay migration failure before the Docker command does *not* rebuild the image. `./bin/build-docker.sh --no-cache` forces all image layers to rebuild from scratch; normal builds reuse unchanged Docker layers. The build prints a clear start message, the upstream Sideloop revision, and running container status. If the checkout has uncommitted changes, it first runs `./bin/bump-version.sh` (interactive; commits and pushes after confirmation). Use `--skip-bump` to build without it, or `--no-push` to commit locally only.

The Apps page displays **Sideloop core** separately from AltServer-Linux: the Sideloop upstream Git commit (`filippofinke/sideloop`), the **SideLoader overlay version**, and a UTC preparation timestamp. This is an identifiable Git-based source revision, not an invented Sideloop semantic release version. It comes from a build manifest embedded in the Docker image so an old running container cannot report a newer checkout just because local files changed. Both original Sideloop source files and SideLoader overlay code contribute to the running app. The Step 1 navigation migration now safely detects already-upgraded four-step dashboards and no longer aborts on their newer labels.

## Pull script version report (v0.2.0+17)

`./bin/pull-latest.sh` always prints the local SideLoader version before contacting GitHub, then shows local/GitHub versions and commit IDs before and after synchronizing. It also reports changed files, preserves local commits/edits and ignored build data, and does not rebuild Docker or push to GitHub. If the updater script itself changes, it invokes the new version in read-only report mode to show the updated version immediately without another Git fetch or pull. `--force` remains explicitly destructive and never deletes ignored `build/` data.


## Existing-checkout installation workflow migration (v0.2.0+18)

`./bin/build-docker.sh` can be run repeatedly against the existing ignored `build/sideloop/` checkout. The Step 4 Install migration recognizes both the old dashboard's immediate closing template tag and the newer navigation overlay's separate closing line. It also recognizes the navigation overlay's `data-step-open="3"` control instead of expecting only `data-go="settings"`. Both layouts are validated before removing the duplicate install controls. If an unknown dashboard layout is encountered, the patch stops without writing a partially migrated index page. This fixes `Cannot safely locate duplicate install controls` without deleting IPAs, account information, pairing, or other runtime data. Four targeted regression tests cover both markup variants, repeat builds, JavaScript syntax, and safety checks.


## Responsive layout and Apple authentication status (v0.2.0+19)

The Apps screen uses a wider desktop layout and wraps AltServer-Linux version, GitHub source, recent commits, and update controls without overlapping at different browser zoom levels. The original mobile layout remains. The responsive patch runs on every build and is repeat-safe for existing `build/sideloop` checkouts.

AltServer error `-36607` is now classified explicitly as an **Apple authentication response** (possibly involving the configured anisette service), **not** proof that the Apple Account is locked or the password is wrong. After the first unsuccessful signing attempt, SideLoader's persistent guard continues blocking unattended and manual retries until explicitly resumed. The Activity log includes the actual Apple Account passed to AltServer. Avoid repeated attempts; verify the account in a browser and inspect the anisette configuration before intentionally resuming.


## Single authorized AltServer invocation (v0.2.0+20)

SideLoader now **atomically reserves one signing attempt on disk immediately before invoking AltServer-Linux**, rather than waiting to record a failure after the process exits. This protects against duplicate Install clicks, scheduler races, cancellation, `SIGTERM`, Docker restarts, timeouts, and lost output. A reserved attempt **remains blocked until either the app is signed and its device provisioning profile has been verified, or the user explicitly selects "Issue resolved — allow one new attempt"**. On a recognized failure, Activity displays the Apple error; on an interrupted job, SideLoader explains that the outcome is unknown. Switching Apple Accounts does not implicitly clear the global lock or authorize another Apple request. Automatic renewal for an unverified account stays disabled.

The guard uses an attempt-specific random token so a stale signing process cannot falsely clear a newer attempt. The state stores only hashed account identity, timestamp, error code and actionable text; it does not store the password, email address, raw AltServer output, or 2FA code. A read-only device check does not spend the attempt allowance. Local `build/sideloop/data` remains intact across rebuilds.

**One attempt means one AltServer process launch per explicit installation action**, not necessarily one HTTP request. Apple's two-factor authentication may involve several network exchanges inside that single invocation. AltServer-Linux NG currently does not provide a supported native Apple web-login/session handoff. A successful login at `account.apple.com` proves access to Apple's website but does not authenticate the AltServer developer-signing protocol. Apple app-specific passwords are intended for authorized third-party services and are not verified here for AltServer's developer signing. Never treat a saved password as verified until a successful signed installation.

After upgrading, if the previous Apple Account failed, save the new account first, review its status, and explicitly permit one new manual installation. Do not enable scheduled renewals until the first successful manual install. There is no fixed Apple cooldown that guarantees avoiding account security locks.


## Repeat-build repair for AltServer links (v0.2.0+21)

When an existing `build/sideloop/sideloop/index.html` has already received the AltServer source links and responsive desktop layout, `patch-backend-info.py` now recognizes the fully installed **GitHub source**, **Recent commits**, and **Check for updates** controls without expecting the old `<span>${version}</span>` HTML structure. Rebuilding does not duplicate links or discard the responsive wrapper. Partial or ambiguous UI state fails safely. The issue appeared as `Cannot safely patch AltServer backend prominent upstream repository and commit links: expected 1 anchor, got 0`; it was a source-migration error before Docker started, not an Apple sign-in problem. `./bin/build-docker.sh` remains safe for preserved IPAs, pairing data and signing settings. Regression tests cover first builds, repeat builds after the responsive overlay, and partial links.


## Prominent pull status and app-specific-password diagnostics (v0.2.0+22)

`./bin/pull-latest.sh` now shows bold terminal banners with wide separators: **CHECKING GITHUB**, **UPDATE AVAILABLE**, **UPDATING SIDELOADER**, and **UPDATE COMPLETE** when it actually downloads and applies changes. When the local commit is exactly the GitHub commit it instead displays **ALREADY ON LATEST VERSION** and does **not** run an unnecessary rebase or touch the local worktree. When local commits already include the latest GitHub commit, it displays **LATEST GITHUB VERSION ALREADY INCLUDED — LOCAL COMMITS RETAINED**. The script continues to report local/GitHub versions, commit IDs, and changes and to preserve user edits and ignored Docker data. Interactive macOS/Linux terminals render banners in bold (plain uppercase text in redirected logs). A `--force` operation is explicitly labeled **FORCE RESET**, not a normal update. The updater does not rebuild or restart Docker.

AltServer error **`-22406`** now receives a distinct signing-failure message: the provided password was rejected. The user's observed app-specific password was rejected by the AltServer developer-signing flow, even though Apple website login can succeed with the regular password. Do not retry app-specific passwords for this backend; use the ordinary account password only after checking account access and signing configuration, and make one explicitly authorized attempt. The existing persistent single-attempt reservation remains active after a failure. A failed password is not by itself evidence of an Apple Account security lock.


## Clear old Activity logs (v0.2.0+23)

Open **Activity → Clear old logs** to erase the saved `refresh.log` and in-memory output of completed jobs, after a destructive-action confirmation. This authenticated, same-origin POST refuses to run during a manual or automatic job. It does not delete Apple Account settings, the one-attempt signing guard, IPAs, device pairing, app profiles, other state or Docker engine logs. The sanitized Diagnostics report still shows the signing guard's blocked status, code, and reason after old messages are cleared. Removing logs does not fix Apple authentication `-36607`; do not repeatedly retry the same account.


## Unified Apps step, iPhone inventory, and compact versions (v0.2.0+24)

The dashboard now has three setup steps: **1 Connect iPhone**, **2 Apple Account**, **3 Apps**. Steps 1–2 are slim, and their connection/verification status appears to the right when closed; the **Apps** step stays expanded by default. Step 3 combines an imported IPA list, **Scan apps** for the selected registered iPhone, checkboxes for currently installed user apps and stored IPAs, **Sync selection**, and individual **Install/Re-sign/Remove** controls. Device scanning uses `ideviceinstaller list --user --xml` (read-only, no Apple sign-in); it can show Xcode-installed apps, but **also App Store apps**, because iOS doesn't consistently expose which apps were sideloaded. Unrecognized app origins are marked as unverified rather than falsely declaring them sideloaded.

Checking an imported IPA missing from the iPhone and choosing **Sync selection** permits **one** explicit AltServer signing action. Selecting two or more missing IPAs is blocked to prevent repeated Apple requests. Unchecking currently installed apps and choosing Sync requests **uninstallation from the iPhone**, with an explicit confirmation listing names and warning that app data may be erased. The backend refuses removal during active jobs, validates bundle IDs and registered devices, rechecks current inventory, and does not touch saved IPAs, Apple credentials, signing locks, or pairing data. Installing and re-signing individually still require explicit confirmation and remain disabled while the one-attempt guard is blocked. The server never silently reinstalls an app whose original IPA is missing.

The large Sideloop/AltServer version cards are replaced with a short footer-style status strip: SideLoader overlay version and Sideloop source revision on the left, pinned AltServer NG revision, a manual **Check updates** button, and a status indicator on the right. The indicator turns red only when GitHub comparison confirms a newer backend revision. Checking is read-only; it neither downloads signing binaries nor authenticates with Apple. The previous provenance functions are retained unused internally to keep overlay migrations repeat-safe.


## Apple two-factor prompt safeguards (v0.2.0+25)

SideLoader's pinned AltServer-Linux NG source already contains the October 2026 trusted-device 2FA support (GrandSlam `hsc 409` without `au`, including refreshed anisette between sign-in steps). This release does **not** patch or upgrade the signing backend, trigger Apple login, or alter credentials/provisioning/pairing data.

The existing **Verification Code** prompt now validates a six-digit numeric code in the browser **and** again in the server's PTY input handler, permits submission only when an interactive manual refresh job is actively requesting a code, and blocks repeated submissions to the same prompt. The submitted code is cleared from the browser input and redacted if the terminal echoes it, including if output arrives in pieces. Logs and the API output mask standalone six-digit code tokens. After a failed signing attempt, the existing persistent one-invocation guard continues blocking retries until explicitly resumed.

No Apple Account or real device sign-in is performed by the unit tests. This is prompt safety, **not** a fix for `-36607`, `-80046`, SMS delivery, or Apple's server-side restrictions. Rebuild locally to activate the patch.


## Persistent-checkout Apps migration hotfix (v0.2.0+26)

Fixes `Apps dashboard patch inventory import: expected one anchor, got 3` after a local repeat build. The Apps overlay now inserts its inventory import beside the unique original Sideloop module import instead of relying on the number of earlier log-maintenance imports. It also recognizes an inventory import already present in another position. Added regression fixtures for repeated log imports, already imported inventory, repeat migrations and an unknown original import. This migration only rewrites application source in the ignored upstream checkout; saved `build/sideloop/data` IPAs, devices, credentials, and signing safety state remain untouched. Rebuild with `./bin/pull-latest.sh && ./bin/build-docker.sh`.


## Repeat-build overlay hardening (v0.2.0+28)

Fixed a persistent-checkout `Apps dashboard patch uninstall POST route: expected one anchor, got 4/5` failure and the analogous GET-route failure by finding the actual POST route dictionary and authenticated GET handler, rather than counting duplicated old log-route lines. Added a single inventory route even where older overlays left 3–10 duplicate logging entries. The Apple-verification, AltServer-backend, log-maintenance and Sideloop-version patchers now check for their own feature symbols before reinserting imports, methods or routes, preventing those overlays from repeatedly duplicating one another on every rebuild. Regression fixtures cover repeated logs and fail-closed handling of unrecognized server layout. No runtime IPA, pairing, Apple credential, or signing guard data is changed; no Apple sign-in is initiated.
