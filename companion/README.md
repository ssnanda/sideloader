# SideLoader Companion

Native iOS viewer for apps managed by SideLoader. It signs in to the existing
SideLoader dashboard API, lists apps assigned to each registered iPhone, and
shows the server-verified installed/missing/offline state and signing lifetime.

iOS does not permit an ordinary app to enumerate every installed App Store app.
This companion therefore displays SideLoader-managed apps only and does not use
private frameworks or hidden entitlements.

Open `SideLoaderCompanion.xcodeproj` in Xcode for development. The default
server is the current Mac NetBird address, `http://100.106.150.135:38080`; users
can replace it with a LAN or HTTPS address on the login screen. Saved dashboard
passwords use the device-only iOS Keychain.

Build an unsigned IPA for SideLoader to sign during installation:

```sh
./bin/companion-ipa.sh --build-only
```

After user-owned device verification and creation of the matching SideLoader
GitHub release, publish the IPA asset:

```sh
./bin/companion-ipa.sh
```
