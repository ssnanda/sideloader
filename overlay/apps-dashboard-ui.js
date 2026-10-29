/* SideLoader unified iPhone Apps step v1 */
let deviceAppTarget = null;
let deviceAppRows = [], deviceAppSelected = new Set(), deviceAppScannedFor = null;
let deviceAppBusy = false, deviceAppError = "";
let deviceAppSideloadedOnly = true;

// Not every sideloaded app carries a readable signer identity in iOS inventory.
// Show confirmed developer-signed apps plus IPAs known to SideLoader by default.
// Keep unknown-origin apps accessible with the filter unchecked.
function deviceAppIsSideloaded(row) {
  return Boolean(row.managed || row.origin === "Developer signed (reported)");
}

function sideLoaderVersionStrip() {
  const core = S.sideloop_build || {};
  const backend = S.altserver_build || {};
  const state = altserverUpdateInfo?.status || "not_checked";
  const flag = state === "update_available" ? "update" :
    state === "up_to_date" ? "current" : state === "not_checked" ? "unchecked" : "unknown";
  const status = state === "update_available" ? "UPDATE AVAILABLE" :
    state === "up_to_date" ? "Up to date" : state === "not_checked" ? "Not checked" : "Check unavailable";
  const coreCommit = core.revision ? core.revision.slice(0, 10) : "unknown";
  const backendCommit = backend.revision ? backend.revision.slice(0, 10) : "unknown";
  return `<div class="sl-compact-versions" aria-label="Installed components and update status">
    <div class="sl-compact-left" title="Sideloop upstream ${esc(coreCommit)} with SideLoader overlay">
      <a href="https://github.com/ssnanda/sideloader" target="_blank" rel="noopener noreferrer">SideLoader ${esc(core.side_loader_version || "unknown")}</a>
      <span>· Sideloop ${esc(coreCommit)}</span>
    </div>
    <div class="sl-compact-right" title="Pinned AltServer-Linux NG revision ${esc(backendCommit)}">
      <a href="https://github.com/jaakkopalvaila/AltServer-Linux/tree/ng" target="_blank" rel="noopener noreferrer">AltServer NG ${esc(backendCommit)}</a>
      <span class="sl-update-status ${flag}">${status}</span>
      <button type="button" class="cap" id="sideloader-compact-altserver-check" ${altserverChecking ? "disabled" : ""}>${altserverChecking ? "Checking…" : "Check updates"}</button>
    </div>
    ${altserverUpdateInfo?.message ? `<div class="sl-compact-message">${esc(altserverUpdateInfo.message)} <span>Checking does not install updates.</span></div>` : ""}
  </div>`;
}

function deviceAppsManager() {
  const devs = S.registered || [];
  const chosen = devs.find(d => d.udid === deviceAppTarget) || devs[0];
  if (!chosen) return `<div class="foot">Connect and register your iPhone in Step 1 to scan its installed apps. Importing an IPA remains available below.</div>`;
  const udid = chosen.udid;
  const scanned = deviceAppScannedFor === udid;
  const known = new Map((S.apps || []).map(app => [app.bundle_id, app]));
  const result = new Map();
  if (scanned) for (const row of deviceAppRows) result.set(row.bundle_id, {...row, managed:known.get(row.bundle_id)});
  for (const app of S.apps || []) {
    if (result.has(app.bundle_id)) continue;
    result.set(app.bundle_id, {bundle_id:app.bundle_id, name:app.name, version:app.version,
      origin:"IPA saved in SideLoader", installed:false, managed:app});
  }
  const allRows = [...result.values()].sort((a,b)=>a.name.localeCompare(b.name));
  const rows = deviceAppSideloadedOnly ? allRows.filter(deviceAppIsSideloaded) : allRows;
  const removed = scanned ? deviceAppRows.filter(a => !deviceAppSelected.has(a.bundle_id)).length : 0;
  const addable = scanned ? rows.filter(a => !a.installed && a.managed && deviceAppSelected.has(a.bundle_id)).length : 0;
  const busy = deviceAppBusy || Boolean(S.job?.running || S.watcher?.running);
  const blocked = Boolean(S.signing_guard?.blocked);
  return `<div class="sl-app-manager">
    <div class="sl-app-toolbar">
      <label for="sideloader-app-device">iPhone</label>
      <select class="fi" id="sideloader-app-device">${devs.map(d=>`<option value="${esc(d.udid)}" ${d.udid===udid?"selected":""}>${esc(d.name||d.udid.slice(0,8))}</option>`).join("")}</select>
      <button type="button" class="cap" id="sideloader-device-app-scan" ${busy?"disabled":""}>${deviceAppBusy?"Scanning…":"Scan apps"}</button>
      <button type="button" class="cap solid" id="sideloader-device-app-sync" ${!scanned||busy||!(removed||addable)?"disabled":""}>Sync selection</button>
    </div>
    <label class="sl-app-filter"><input type="checkbox" id="sideloader-sideloaded-only" ${deviceAppSideloadedOnly?"checked":""}> Sideloaded only</label>
    <div class="foot sl-app-help">Shows identified developer-signed apps and IPAs saved in SideLoader by default. iOS may not report the origin of other sideloaded apps; uncheck to see every app. The row checkboxes still control keep/remove selections, not this filter. No Apple login during scanning.</div>
    ${deviceAppError?`<div class="foot" style="color:var(--red)">${esc(deviceAppError)}</div>`:""}
    ${scanned?`<div class="sl-app-count">${rows.length} shown of ${allRows.length} · ${deviceAppRows.length} found on iPhone · ${removed} selected for removal · ${addable} selected for installation</div>`:
      `<div class="sl-app-count">Scan iPhone to compare installed apps and stored IPAs.</div>`}
    <div class="list sl-app-list">${rows.map(row=>{
      const selected = scanned ? deviceAppSelected.has(row.bundle_id) : false;
      const button = row.managed ? (row.installed?"Re-sign":"Install") : "Remove";
      const disabled = busy || (Boolean(row.managed) && blocked) || (!row.managed && !scanned);
      const subtitle = `${row.installed?"Installed on iPhone":"IPA saved · not detected on iPhone"} · ${row.managed?"SideLoader IPA available":row.origin}`;
      return `<div class="sl-app-entry" data-bundle="${esc(row.bundle_id)}">
        <label class="sl-app-select"><input type="checkbox" data-device-app-pick="${esc(row.bundle_id)}" ${selected?"checked":""} ${!scanned?"disabled":""} aria-label="Keep ${esc(row.name)} installed" /></label>
        <span class="sl-app-detail"><b>${esc(row.name)}</b><small>${esc(row.bundle_id)}${row.version?" · "+esc(row.version):""}</small><small>${esc(subtitle)}</small></span>
        <button type="button" class="cap ${row.installed?"":"solid"}" data-device-app-action="${esc(row.bundle_id)}" ${disabled?"disabled":""}>${button}</button>
      </div>`;
    }).join("") || `<div class="cell">${deviceAppSideloadedOnly?"No identified sideloaded apps. Uncheck Sideloaded only to show all.":"No saved IPAs or scanned apps to display."}</div>`}</div>
    ${blocked?`<div class="foot" style="color:var(--red)">Apple signing is paused. Scanning and removal still work; Install and Re-sign stay blocked.</div>`:""}
  </div>`;
}

async function scanDeviceApps(udid) {
  if (!udid || deviceAppBusy) return;
  deviceAppBusy = true;
  deviceAppError = "";
  render();
  try {
    const r = await api("/api/device/apps?device=" + encodeURIComponent(udid));
    deviceAppRows = r.apps || [];
    deviceAppScannedFor = udid;
    deviceAppTarget = udid;
    deviceAppSelected = new Set(deviceAppRows.map(row => row.bundle_id));
  } catch (e) {
    deviceAppRows = [];
    deviceAppScannedFor = null;
    deviceAppError = e.message || "Cannot scan installed apps";
  } finally {
    deviceAppBusy = false;
    render();
  }
}

async function uninstallDeviceApps(udid, bundles) {
  if (!bundles.length) return;
  const names = bundles.map(bundle=>deviceAppRows.find(a=>a.bundle_id===bundle)?.name || bundle);
  if (!window.confirm(`UNINSTALL ${bundles.length} app(s) from your iPhone?\n\n${names.join("\n")}\n\nTheir on-device data may be erased. Saved SideLoader IPAs remain. This does NOT sign in to Apple. Proceed?`)) return false;
  await api("/api/device/apps/remove", {json:{device:udid,bundles,acknowledge:true}});
  await scanDeviceApps(udid);
  return true;
}

function singleAppSigning(app, udid, installed) {
  if (S.signing_guard?.blocked) return toast("Signing paused. Review the earlier failure before allowing a new attempt.");
  if (S.job?.running || S.watcher?.running) return toast("Another job is running.");
  if (!window.confirm(`${installed?"Re-sign":"Install"} ${app.name} on iPhone?\n\nThis permits ONE AltServer Apple signing invocation. No automatic retries. Proceed?`)) return;
  startJob("/api/refresh", {force:true, app:app.id, device:udid});
}