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
  on("sideloader-add-app", "onclick", () => {
    appAddOpen = !appAddOpen;
    if (appAddOpen && !sourceCatalogLoaded && !sourceCatalogBusy) loadSourceCatalog();
    render();
  });
  on("sideloader-import-ipa", "onclick", () => root.querySelector("#file")?.click());
  root.querySelectorAll("[data-source-app]").forEach(button => button.onclick = () => {
    const selected = sourceCatalog.find(app => app.bundleIdentifier === button.dataset.sourceApp);
    if (selected) importSourceApp(selected);
  });
  root.querySelectorAll("[data-device-source-action]").forEach(button => button.onclick = () => {
    const selected = sourceCatalog.find(app => app.bundleIdentifier === button.dataset.deviceSourceAction);
    if (selected) importSourceApp(selected, true);
  });
  root.querySelectorAll("[data-imported-app]").forEach(button => button.onclick = () => {
    const app = (S.apps || []).find(item => item.id === button.dataset.importedApp);
    const d = root.querySelector("#sideloader-app-device");
    if (!app || !d) return;
    const installed = deviceAppScannedFor === d.value && deviceAppRows.some(row =>
      deviceBundleMatches(row.bundle_id, app.bundle_id) || normalizedAppName(row.name) === normalizedAppName(app.name));
    singleAppSigning(app, d.value, installed);
  });
  on("sideloader-device-app-scan", "onclick", () => {
    const d = root.querySelector("#sideloader-app-device");
    if (d) scanDeviceApps(d.value);
  });
  on("sideloader-resign-all", "onclick", () => {
    const d = root.querySelector("#sideloader-app-device");
    if (d) slStartBackgroundResignAll(d.value);
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
      singleAppSigning(app, d.value, Boolean(app.targets?.some(t=>t.udid===d.value && t.installation?.state==="installed") && deviceAppScannedFor===d.value && deviceAppRows.some(x=>deviceBundleMatches(x.bundle_id,bundle))));
    } else if (deviceAppScannedFor === d.value && deviceAppRows.some(x=>x.bundle_id===bundle)) {
      try { await uninstallDeviceApps(d.value,[bundle]); } catch(e) { toast(e.message); }
    }
  });
  root.querySelectorAll("[data-device-app-remove]").forEach(button => button.onclick = () => {
    const d = root.querySelector("#sideloader-app-device");
    if (!d || deviceAppScannedFor !== d.value) return toast("Scan this iPhone first.");
    const bundle = button.dataset.deviceAppRemove;
    if (deviceAppRows.some(row => row.bundle_id === bundle)) slRemoveApps(d.value, [bundle]);
  });
  on("sideloader-device-app-sync", "onclick", async () => {
    const d = root.querySelector("#sideloader-app-device");
    if (!d || deviceAppScannedFor !== d.value || deviceAppBusy) return toast("Scan this iPhone first.");
    const removed = deviceAppRows.filter(row=>!deviceAppSelected.has(row.bundle_id)).map(row=>row.bundle_id);
    const missing = (S.apps||[]).filter(app=>!deviceAppRows.some(row=>deviceBundleMatches(row.bundle_id,app.bundle_id)) && deviceAppSelected.has(app.bundle_id));
    if (missing.length>1) return toast("Select only one missing IPA per sync to avoid repeated Apple sign-ins.");
    if (missing.length && S.signing_guard?.blocked) return slScreen("paused",{appId:missing[0].id,name:missing[0].name,udid:d.value,installed:false});
    if (!removed.length && !missing.length) return toast("The selected apps already match the iPhone.");
    if (removed.length) {
      slRemoveApps(d.value, removed, missing.length ? missing[0].id : null);
      return; // Wait for on-screen confirmation; do not uninstall immediately.
    }
    if (missing.length) singleAppSigning(missing[0], d.value, false);
    else slMessage("Already synchronized", "The selected apps already match the iPhone.");
  });
