# Apple sign-in and two-factor verification — audited 2026-10-30

## What SideLoader can and cannot promise

SideLoader cannot force Apple to issue a six-digit verification code or verify delivery to a particular iPhone. The local backend can (a) request trusted-device verification where Apple requires it, (b) recognize when Apple has already initiated verification, and (c) expose a secure code-entry screen **only once the AltServer terminal callback is waiting for a code**.

A signed-in/trusted session can proceed without another verification code. An authentication error before the challenge — notably `-36607` — must not display a code-entry box or claim that Apple sent a code.

## Source-level comparison

1. **Apple authentication states:** The AltSign implementation vendored by `jaakkopalvaila/AltServer-Windows`, branch `ng-fixes`, checks `hsc == 409` when the `au` field is absent. This is Apple's October 2026 automatic trusted-device challenge. It sets `isCodeAlreadySent` and calls the verification handler **without requesting another code**, avoiding invalidation of the code already pushed by Apple. When `au == trustedDeviceSecondaryAuth`, `RequestTwoFactorCode` sends `GET /auth/verify/trusteddevice` before calling the handler. It sends the entered six-digit code to Apple's `/grandslam/GsService2/validate` endpoint, refreshes anisette data, and authenticates again.
2. **Actual Linux console:** `jaakkopalvaila/AltServer-Linux` `makefiles/rewrite_altserver_source.py` rewrites its `AltServerApp::Authenticate` callback to print exactly `Enter two factor code` and read from `std::cin`. The SideLoader PTY parser recognizes this explicit prompt, including when terminal output arrives in split chunks.
3. **SideLoader interface:** `overlay/patch-apple-2fa-safety.py` starts a 60-second deadline only after an actual input prompt; accepts exactly one six-digit code; masks OTP echo; and blocks automatic retries. `overlay/patch-screen-flow.py` switches to the full Apps screen on a pending prompt, with code entry provided by `overlay/screen-flow-ui.js`. An active challenge is polled about every 500 ms; other running jobs about every 800 ms.
4. **Identity compatibility:** SideLoader uses AltServer-Linux NG's Mac anisette configuration. The newer AltStore authentication PRs confirm that GrandSlam headers, provider identity and client User-Agent need to match. `deploy/mac-host.yml` and `deploy/ubuntu-host.yml` configure a default Mac-provider-matching `ALTSERVER_GSA_USER_AGENT`. Those values are overridable for other anisette providers.
5. **Important distinction:** AltStore Classic 2.3.2/AltServer 1.8.3 and AltServer-Linux NG are *not the same binary or anisette provisioning implementation*. Matching their 2FA state transitions does not prove identical Apple acceptance or that a particular account will receive a code.

## Code-delivery indicator (Step 3, SideLoader 0.2.0+44)

The active installation screen displays one of three statuses, updated from
the current AltServer job (not prior logs):

- **Apple reports verification code sent:** AltSign received the automatic
  trusted-device challenge (`hsc=409`) and logged that Apple had already
  initiated a code. This does **not** confirm receipt by this particular iPhone.
- **Verification code requested · delivery unconfirmed:** The interactive
  AltServer callback is awaiting six-digit input, without an explicit
  `hsc=409` sent report. The input field opens automatically.
- **Verification code not reported sent:** No code-delivery signal has appeared
  in this signing attempt. This is not proof that Apple did not send one.

The state is job-scoped, preserved for the job result, and read-only. When
Apple reports a sent code (the `hsc=409` signal), SideLoader immediately shows
the six-digit entry field in Step 3. The user can type immediately; the **Verify**
button becomes available when AltServer's interactive callback is ready to read
the code. The code is never submitted prematurely. The callback still starts
the 60-second timer. No second code is requested and no Apple notification
receipt API is available through this backend.

## Observable outcomes

| Apple / backend behavior | SideLoader behavior |
| --- | --- |
| Sign-in accepted without challenge | Continues signing without showing an OTP field |
| `hsc=409`: Apple already initiated trusted-device code | Backend does not request a second code; its console handler prints `Enter two factor code`; SideLoader opens code entry |
| Explicit trusted-device challenge | Backend requests code, then prints `Enter two factor code`; SideLoader opens code entry |
| Apple returns `-36607` before terminal 2FA prompt | Signing stops; failure displayed with explanation that no code entry was requested |
| Challenge active, code not entered for 60 seconds | Local signing cancelled and recorded as user cancellation; no automatic retries |
| Invalid or repeated code submission | Rejected by backend input validation, with no second code submission |
| App not confirmed by current iPhone inventory | Never mark the IPA installed based on cached provisioning alone |

## Known limits and safety

- A successful HTTP response when requesting a trusted-device code is **not proof that the notification was displayed on the user's iPhone**. SideLoader has no OS-level access to Apple's notification delivery receipt.
- The Linux fork's `RequestTwoFactorCode` currently follows the send-code request with its verification handler without explicitly checking the returned HTTP status in that chain. That is an upstream limitation; the SideLoader UI cannot honestly claim confirmed code delivery. If the code does not arrive, do not guess or submit repeated codes.
- The Linux command-line wrapper's `AltServerMain.cpp` catches certain install errors but may exit with status zero. SideLoader must check actual device inventory and classify captured Apple errors instead of interpreting that exit code alone as success.
- No automated Apple sign-in test was run during this audit. No Apple Account credentials, tokens or verification codes were read or transmitted, and the signing safety lock was not automatically reset.
- Repeated automatic retries remain disabled because Apple's anti-abuse protections may lock accounts.

## Relevant upstream code and discussions

- https://github.com/jaakkopalvaila/AltServer-Linux/blob/ng/makefiles/rewrite_altserver_source.py
- https://github.com/jaakkopalvaila/AltServer-Linux/blob/ng/src/AltServerMain.cpp
- https://github.com/jaakkopalvaila/AltServer-Windows/blob/ng-fixes/AltSign/AppleAPI%2BAuthentication.cpp
- https://github.com/altstoreio/AltStore/pull/1834
- https://github.com/altstoreio/AltStore/pull/1851
- https://github.com/altstoreio/AltStore/issues/1827
- https://github.com/altstoreio/AltStore/issues/1842
