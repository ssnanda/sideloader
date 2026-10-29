  on("sideloader-compact-altserver-check", "onclick", () => {
    if (altserverChecking) return;
    altserverChecking = true;
    render();
    act(async () => {
      try {
        altserverUpdateInfo = await api("/api/altserver/check-updates", {json:{}});
      } finally { altserverChecking = false; }
    });
  });
  on("sideloader-app-device", "onchange", e => {
    deviceAppTarget = e.target.value;
    deviceAppRows = [];
    deviceAppScannedFor = null;
    deviceAppSelected = new Set();
    deviceAppError = "";
    render();
  });
  on("sideloader-sideloaded-only", "onchange", e => {
    deviceAppSideloadedOnly = e.target.checked;
    render();
  });
  on("sideloader-catalog-refresh", "onclick", loadSourceCatalog);
  root.querySelectorAll("[data-source-app]").forEach(button => button.onclick = () => {
    const selected = sourceCatalog.find(app => app.bundleIdentifier === button.dataset.sourceApp);
    if (selected) importSourceApp(selected);
  });
  on("sideloader-device-app-scan", "onclick", () => {
    const d = root.querySelector("#sideloader-app-device");
    if (d) scanDeviceApps(d.value);
  });
  root.querySelectorAll("[data-device-app-pick]").forEach(input => input.onchange = e => {
    const bundle = e.target.dataset.deviceAppPick;
    if (e.target.checked) deviceAppSelected.add(bundle);
    else deviceAppSelected.delete(bundle);
    render();
  });
  root.querySelectorAll("[data-device-app-action]").forEach(button => button.onclick = async () => {
    const bundle = button.dataset.deviceAppAction;
    const d = root.querySelector("#sideloader-app-device");
    if (!d) return;
    const app = (S.apps || []).find(x=>x.bundle_id === bundle);
    if (app) {
      singleAppSigning(app, d.value, Boolean(app.targets?.some(t=>t.udid===d.value && t.installation?.state==="installed") && deviceAppScannedFor===d.value && deviceAppRows.some(x=>x.bundle_id===bundle)));
    } else if (deviceAppScannedFor === d.value && deviceAppRows.some(x=>x.bundle_id===bundle)) {
      try { await uninstallDeviceApps(d.value,[bundle]); } catch(e) { toast(e.message); }
    }
  });
  on("sideloader-device-app-sync", "onclick", async () => {
    const d = root.querySelector("#sideloader-app-device");
    if (!d || deviceAppScannedFor !== d.value || deviceAppBusy) return toast("Scan this iPhone first.");
    const removed = deviceAppRows.filter(row=>!deviceAppSelected.has(row.bundle_id)).map(row=>row.bundle_id);
    const missing = (S.apps||[]).filter(app=>!deviceAppRows.some(row=>row.bundle_id===app.bundle_id) && deviceAppSelected.has(app.bundle_id));
    if (missing.length>1) return toast("Select only one missing IPA per sync to avoid repeated Apple sign-ins.");
    if (missing.length && S.signing_guard?.blocked) return toast("Signing paused. Remove the app selection or review Activity first.");
    if (!removed.length && !missing.length) return toast("The selected apps already match the iPhone.");
    if (removed.length) {
      try {
        const ok = await uninstallDeviceApps(d.value, removed);
        if (!ok) return;
      } catch(e) { return toast(e.message); }
    }
    if (missing.length) singleAppSigning(missing[0], d.value, false);
    else toast("iPhone app selection synchronized. No Apple sign-in attempted.");
  });