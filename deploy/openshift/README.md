# SideLoader remote-pairing deployment

This deployment is opt-in and is not a finished, tested OpenShift installation.

1. Build the **patched SideLoader** image from the existing local build process and push it to an accessible registry. Separately build the [AltKeeper](https://github.com/BartolomeoRusso9/altkeeper) Docker image. Substitute both registry references in `remote-server.yaml`. No `./bin/*.sh` changes are needed.
2. On a computer connected to your unlocked iPhone over USB, use **AltKeeper `pair-usb`** once. Securely place its resulting `rp-pairing.plist` at `/data/rp-pairing.plist` in the AltKeeper persistent volume. This is a sensitive pairing credential; never commit it to GitHub.
3. Create an OpenShift Secret named `sideloader-remote-auth` with keys `altkeeper-pin` (long private PIN), `iphone-udid` (paired device identifier), and `iphone-netbird-address` (the iPhone VPN IP and RemotePairing port, e.g. `100.106.194.227:49152`). The iPhone must be on Wi-Fi with NetBird active.
4. Deploy the [NetBird Kubernetes Operator](https://docs.netbird.io/use-cases/kubernetes/client-sidecar) and configure suitable VPN ACLs. Apply `netbird-sidecar.yaml` **before** `remote-server.yaml`; its operator sidecar may need OpenShift administrator security-policy approval.
5. Start the AltKeeper account login once via its private loopback dashboard or CLI (access using `oc port-forward`). It uses its **own** Apple account/session, separate from SideLoader's legacy AltServer credentials. Persist its data securely.
6. Open SideLoader at the Pod's NetBird IP on TCP `38080`, or through a private routed service, and sign in. Use **Test VPN & pairing**. A successful TCP connection to `49152` alone does *not* establish an Apple pairing handshake.
7. Try one explicit **Re-sign**, then **Reinstall latest**. SideLoader's legacy automatic watcher is disabled in remote mode; use AltKeeper's own schedule after verifying remote device behavior.

There is intentionally **no public OpenShift Route**, no public AltKeeper service, and no pairing file or password in these manifests. The backend refuses URLs that do not point to Pod loopback. This deployment supports one explicitly configured iPhone per SideLoader instance; do not scale replicas without splitting credentials and persistent volumes.

App presence cannot yet be confirmed independently through the remote server, so remote screens display provisioning profiles, not a verified installed-app inventory. Bulk renewals stay disabled to avoid reinstalling apps a user removed.

**Important:** If the iPhone's RemotePairing service isn't reachable through NetBird on a different Wi-Fi, OpenShift alone cannot fix that iOS networking constraint. The fallback is an on-device installation engine, not opening internet ports.
