# SideLoader v0.1.2+2 — installation state, October Apple sign-in, diagnostics

## Update on macOS or Ubuntu

Run the existing no-argument `./bin/pull-latest.sh`, followed by `./bin/build-docker.sh`. All compilation and runtime happen locally, not in GitHub Actions. The builder preserves everything under ignored `build/sideloop/data` (IPAs, credentials and pairing). Do not use `pull-latest.sh --fresh` when you want to retain those files.

## Actual iPhone application inventory

SideLoader now uses `ideviceinstaller` inside its Docker image. The dashboard distinguishes Installed, Not installed on iPhone, Device offline (unverified), and Installation status unknown. A stale provisioning profile alone never counts as an installed app. `Check Everything` confirms the app inventory separately from the provisioning profile. A successfully returned AltServer process also requires an installed-app check before being marked successful. Failed or unavailable checks report Unknown, never incorrectly report Missing.

## Apple sign-in error -80046

The Docker build now uses the maintained `jaakkopalvaila/AltServer-Linux` `ng` branch at the reviewed commit `5c32531fe0eb6ff87ed8f7b137da803c91945a02` (commit check prevents silently switching to later unreviewed code). This branch documents a successful October 27, 2026 test with iOS 27, after Apple's October auth change. The existing Sideloop provisioning-profile and chunked-upload patches are retained. The expected exact source revision can be reviewed in `overlay/patch-v2.py`.

Sign-ins now default to `https://mac-ani.jkcoxson.com`, since the existing Android-based anisette container no longer works reliably after the October change. This provider is a third party: it sees your IP and requests for anisette metadata, but SideLoader does not directly send your Apple password, 2FA code or app IPA to that server. The external service supplies a shared machine identity, which can affect Apple's rate limits and reliability. To change providers, set `SIDELOADER_ANISETTE_SERVER` in ignored `build/sideloop/.env` before building. The old bundled anisette service remains present but is no longer the signing default.

Repeated authentication failures may cause temporary Apple account lockouts. Avoid repeated force refreshes if -80046 continues after the update. The login fix is based on external upstream testing; it has **not** been verified using your Apple ID or iPhone.

## One-click sanitized diagnostics

Open `http://localhost:38080` (or the server IP on the trusted LAN) and select **Copy Diagnostics**. When clipboard permissions are available, the sanitized report is copied. Otherwise, a selectable text area opens; copy the text and paste it into chat. The report summarizes actual installation checks, service health, last 250 refresh-log lines and the current/last job. It filters Apple credentials, device IDs, common signing headers, obvious verification codes and IPs. Always review reports before sharing.

The browser clipboard API generally requires localhost or HTTPS. On plain LAN HTTP, use the selectable text fallback. Do not expose port 38080 on the public internet.

## Checks and limitations

- Shell syntax and Python compilation verified, unit tests for inventory parsing and privacy filtering passed; upstream overlay patcher tested against fixtures and repeated patch application.
- Not tested against your actual Docker daemon or iOS 27 phone; successful signing and Wi-Fi refresh cannot be guaranteed without that test.
- Device inventory detection depends on `ideviceinstaller` working on the device's iOS release. If it fails, SideLoader reports **unknown** rather than incorrectly claiming the app is installed or absent.
