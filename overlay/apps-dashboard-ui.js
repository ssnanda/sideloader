/* SideLoader unified iPhone Apps step v1 */
let deviceAppTarget = null;
let deviceAppRows = [], deviceAppSelected = new Set(), deviceAppScannedFor = null;
let deviceAppBusy = false, deviceAppError = "";
let appAddOpen = location.hash === "#apps-add";
let sourceCatalog = [], sourceCatalogError = "", sourceCatalogBusy = false;
let sourceCatalogLoaded = false;

async function loadSourceCatalog() {
  if (sourceCatalogBusy) return;
  sourceCatalogBusy = true;
  try {
    const data = await api("/api/sources");
    sourceCatalog = (data.sources || []).flatMap(source =>
      (source.apps || []).map(app => ({...app, source_id:source.id, source_name:source.name})));
    sourceCatalogError = "";
    sourceCatalogLoaded = true;
  } catch (e) {
    sourceCatalogError = e.message || "Cannot load sources";
  } finally {
    sourceCatalogBusy = false;
    render();
  }
}

async function importSourceApp(item, installed=false) {
  if (sourceCatalogBusy) return;
  sourceCatalogBusy = true;
  render();
  try {
    const r = await api("/api/sources/install", {json:{
      source:item.source_id, bundleIdentifier:item.bundleIdentifier, install_now:false
    }});
    if (!r.app_id) throw new Error("No IPA was imported");
    await refresh();
    const imported = (S.apps || []).find(app => app.id === r.app_id);
    const chosen = (S.registered || []).find(d => d.udid === deviceAppTarget) || (S.registered || [])[0];
    if (imported && chosen) singleAppSigning(imported, chosen.udid, installed);
    else slMessage("IPA imported", item.name + " is now available under Imported IPAs.");
  } catch (e) {
    slMessage("IPA import failed", e.message);
  } finally {
    sourceCatalogBusy = false;
    render();
  }
}


// Not every sideloaded app carries a readable signer identity in iOS inventory.
// Show confirmed developer-signed apps plus IPAs known to SideLoader by default.
// Keep unknown-origin apps accessible with the filter unchecked.
function deviceAppIsSideloaded(row) {
  return Boolean(row.managed || row.relatedManaged || row.origin === "Developer signed (reported)");
}

function deviceBundleMatches(deviceBundle, sourceBundle) {
  if (deviceBundle === sourceBundle) return true;
  const prefix = sourceBundle + ".";
  return deviceBundle.startsWith(prefix) && /^[A-Z0-9]{10}$/.test(deviceBundle.slice(prefix.length));
}

function normalizedAppName(name) {
  return String(name || "").trim().toLocaleLowerCase().replace(/[^a-z0-9]+/g, "");
}

function relatedSavedApp(deviceRow, savedApps) {
  const name = normalizedAppName(deviceRow.name);
  if (!name) return null;
  const matches = savedApps.filter(app => normalizedAppName(app.name) === name);
  return matches.length === 1 ? matches[0] : null;
}

function signingDaysLeft(target, scannedExpiry=0) {
  const expiry = target?.signature?.expiry || scannedExpiry;
  if (!expiry) return "Signing expiry unavailable";
  const seconds = expiry - S.now;
  if (seconds <= 0) return "Signing expired";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  if (days > 0) return `${days}d ${hours}h remaining`;
  const minutes = Math.max(1, Math.floor((seconds % 3600) / 60));
  return hours > 0 ? `${hours}h ${minutes}m remaining` : `${minutes}m remaining`;
}

function signingExpiryText(target, scannedExpiry=0) {
  const expiry = target?.signature?.expiry || scannedExpiry;
  if (!expiry) return "Expiration unavailable";
  return `Expires ${new Date(expiry * 1000).toLocaleString([], {
    month:"short", day:"numeric", hour:"numeric", minute:"2-digit"
  })}`;
}

function sideLoaderAppIdSummary(rows) {
  const tracked = rows.reduce((count, row) => {
    const app = row.managed || row.relatedManaged;
    return count + (row.scanReported && app ? 1 + (Number(app.info?.extension_count) || 0) : 0);
  }, 0);
  return `App IDs: ${tracked} in use (SideLoader-observed) · Apple remaining/pending unavailable`;
}

function importedIpaRemoveButton(app) {
  const key = "app:" + app.id;
  const armed = confirmRemove === key;
  return `<button class="iconbtn ${armed ? "armed" : ""}" data-remove="${esc(key)}" aria-label="Remove ${esc(app.name)}">${armed ? "Remove" : ic("trash-outline", 20)}</button>`;
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
  if (!chosen) return `<div class="foot">Connect an iPhone in Step 1 before managing apps.</div>`;
  const udid = chosen.udid;
  const scanned = deviceAppScannedFor === udid;
  const result = new Map();
  if (scanned) for (const row of deviceAppRows) {
    const managed = (S.apps || []).find(app => deviceBundleMatches(row.bundle_id, app.bundle_id));
    const relatedManaged = managed ? null : relatedSavedApp(row, S.apps || []);
    const sourceMatch = sourceCatalog.find(app => deviceBundleMatches(row.bundle_id, app.bundleIdentifier));
    const target = managed?.targets?.find(t => t.udid === udid);
    // A user-app inventory entry alone does not establish that a SideLoader
    // signing/install completed. The device/profile check must agree too.
    const confirmed = Boolean(managed && target?.installation?.state === "installed");
    result.set(row.bundle_id, {...row, managed, relatedManaged, sourceMatch, installed: managed ? confirmed : Boolean(row.installed),
      scanReported: Boolean(row.installed), confirmed});
  }
  const rows = [...result.values()].filter(deviceAppIsSideloaded).sort((a,b)=>a.name.localeCompare(b.name));
  const resignable = rows.filter(row => row.managed && row.installed);
  const busy = deviceAppBusy || Boolean(S.job?.running || S.watcher?.running);
  const blocked = Boolean(S.signing_guard?.blocked);
  const savedBundles = new Map((S.apps || []).map(app => [app.bundle_id, app]));
  const catalogRows = [...new Map(sourceCatalog.map(app => [app.bundleIdentifier, app])).values()]
    .sort((a,b) => a.name.localeCompare(b.name));
  const catalogMarkup = `<section class="sl-add-category">
    <div class="sl-add-heading"><b>From Sources</b><a href="/sources">Manage sources</a></div>
    ${sourceCatalogError?`<div class="foot">${esc(sourceCatalogError)}</div>`:""}
    ${!sourceCatalogLoaded?`<div class="foot">Loading saved sources…</div>`:
      catalogRows.map(app => {
        const saved = savedBundles.get(app.bundleIdentifier);
        const currentVersion = saved?.version || "";
        const identical = saved && currentVersion === app.version;
        const installed = rows.some(row => deviceBundleMatches(row.bundle_id, app.bundleIdentifier));
        const label = installed && identical ? "Installed" : identical ? "Add" : saved ? "Update & add" : "Add";
        return `<div class="sl-app-entry">
          <span class="sl-app-detail"><b>${esc(app.name)}</b>
            <small>${esc(app.version)} · ${esc(app.source_name)}</small>
          </span>
          <button type="button" class="cap" ${identical?`data-imported-app="${esc(saved.id)}"`:`data-source-app="${esc(app.bundleIdentifier)}"`}
            ${(installed&&identical)||sourceCatalogBusy?"disabled":""}>${label}</button>
        </div>`;
      }).join("") || '<div class="foot">No apps available. Add or scan for sources first.</div>'}
  </section>`;
  const importedMarkup = `<section class="sl-add-category">
    <div class="sl-add-heading"><b>Imported IPAs</b><button type="button" class="cap" id="sideloader-import-ipa">Import IPA</button></div>
    ${(S.apps || []).map(app => {
      const installed = rows.some(row => deviceBundleMatches(row.bundle_id, app.bundle_id) || row.relatedManaged?.id === app.id);
      return `<div class="sl-app-entry"><span class="sl-app-detail"><b>${esc(app.name)}</b><small>${esc(app.version)} · ${esc(app.bundle_id)}</small></span>
        <button type="button" class="cap" data-imported-app="${esc(app.id)}" ${busy?"disabled":""}>${installed?"Re-sign":"Install"}</button>
        ${importedIpaRemoveButton(app)}</div>`;
    }).join("") || '<div class="foot">No imported IPA files.</div>'}
  </section>`;
  return `<div class="sl-app-manager">
    <div class="sl-app-toolbar">
      <label for="sideloader-app-device">iPhone</label>
      <select class="fi" id="sideloader-app-device">${devs.map(d=>`<option value="${esc(d.udid)}" ${d.udid===udid?"selected":""}>${esc(d.name||d.udid.slice(0,8))}</option>`).join("")}</select>
      <button type="button" class="cap" id="sideloader-device-app-scan" ${busy?"disabled":""}>${deviceAppBusy?"Scanning…":"Scan iPhone"}</button>
      <button type="button" class="cap" id="sideloader-resign-all" ${busy||blocked||!resignable.length?"disabled":""}>Re-sign all</button>
      <button type="button" class="cap solid" id="sideloader-add-app" ${busy?"disabled":""}>${appAddOpen?"Close":"Add app"}</button>
    </div>
    ${deviceAppError?`<div class="foot" style="color:var(--red)">${esc(deviceAppError)}</div>`:""}
    <div class="sl-installed-title"><b>Installed apps</b>${scanned?`<span>${rows.length}</span>`:""}</div>
    ${!scanned?'<div class="sl-empty-installed">Scan this iPhone to show installed apps and signing time remaining.</div>':""}
    <div class="list sl-app-list">${rows.map(row=>{
      const button = row.managed || row.sourceMatch ? "Re-sign" : "Remove";
      const disabled = busy || (!row.managed && !row.relatedManaged && !scanned);
      const target = row.managed?.targets?.find(t => t.udid === udid);
      const deviceSigning = signingDaysLeft(target, row.signing_expiry);
      const expiryText = signingExpiryText(target, row.signing_expiry);
      const subtitle = row.relatedManaged ? `Saved IPA uses different bundle ID ${row.relatedManaged.bundle_id}` : row.bundle_id;
      return `<div class="sl-app-entry" data-bundle="${esc(row.bundle_id)}">
        <span class="sl-app-detail"><span class="sl-installed-main"><b>${esc(row.name)}</b><strong class="sl-signing-days">${esc(deviceSigning)}</strong></span><small>${esc(expiryText)} · ${esc(subtitle)}${row.version?" · "+esc(row.version):""}</small></span>
        <button type="button" class="cap ${row.installed?"":"solid"}" ${row.sourceMatch&&!row.managed?`data-device-source-action="${esc(row.sourceMatch.bundleIdentifier)}"`:`data-device-app-action="${esc(row.managed?.bundle_id || row.bundle_id)}"`} ${disabled?"disabled":""}>${button}</button>
      </div>`;
    }).join("")}</div>
    ${blocked?`<div class="foot" style="color:var(--red)">Apple signing is paused. Scanning and removal still work; use Install to see why signing is blocked.</div>`:""}
    ${appAddOpen?`<div class="sl-add-apps">${catalogMarkup}${importedMarkup}</div>`:""}
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
  if (!bundles?.length) return false;
  slRemoveApps(udid, bundles);
  return false; // Removal happens only on the separate confirmation screen.
}

function singleAppSigning(app, udid, installed) {
  slInstall(app, udid, installed);
}
