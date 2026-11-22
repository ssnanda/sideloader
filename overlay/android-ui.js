/* SideLoader Android v1 start */
// Apple/Android switch at the top of Apps. Apple keeps the existing flow;
// Android mirrors it: Step 1 connects a phone (USB or Wi-Fi ADB), Step 2
// scans installed apps and adds APKs from Sources or imported files.
let slPlatform = "apple";
try { if (localStorage.getItem("sideloaderPlatform") === "android") slPlatform = "android"; } catch {}
let slPlatformInner = false;
let androidState = null, androidCatalog = null, androidImported = null;
let androidRows = null, androidScannedFor = null, androidScanError = "";
let androidDevice = null, androidBusy = "", androidNotice = null, androidLoading = false;
let androidAddOpen = false, androidShowAll = false;
let androidPairOpen = null;      // Wi-Fi panel; closed until opened
const androidOpen = {usb:null};  // USB help: open while no phone is connected

function slPlatformView() {
  const pick = (value, label) => `<label class="${slPlatform === value ? "on" : ""}">
    <input type="radio" name="sl-platform" value="${value}" ${slPlatform === value ? "checked" : ""}>${label}</label>`;
  const head = `<div class="sl-platform" role="radiogroup" aria-label="Platform">${pick("apple", "Apple")}${pick("android", "Android")}</div>`;
  if (slPlatform === "android") return head + androidView();
  slPlatformInner = true;
  try { return head + appsView(); } finally { slPlatformInner = false; }
}

const androidConnected = () => (androidState?.devices || []).filter(d => d.state === "device");

async function androidLoad(force=false) {
  if (androidLoading) return;
  androidLoading = true;
  render();
  try {
    androidState = await api("/api/android/state");
    const live = androidConnected();
    if (!live.some(d => d.address === androidDevice)) androidDevice = live[0]?.address || null;
    const [catalog, imported] = await Promise.all([
      api("/api/android/catalog" + (force ? "?force=1" : "")), api("/api/android/imported")]);
    androidCatalog = catalog; androidImported = imported.apks || [];
    if (androidDevice && (force || androidScannedFor !== androidDevice)) await androidScan(false);
    else if (!androidDevice) { androidRows = null; androidScannedFor = null; }
  } catch (e) {
    androidNotice = {bad:true, text:e.message};
    androidState ||= {devices:[], discovered:[], server:{}};
    androidCatalog ||= {apps:[], repos:[], warnings:[]};
    androidImported ||= [];
  } finally {
    androidLoading = false;
    render();
  }
}

async function androidScan(paint=true) {
  if (!androidDevice) return;
  if (paint) { androidBusy = "scan"; androidScanError = ""; render(); }
  try {
    const r = await api("/api/android/installed?device=" + encodeURIComponent(androidDevice));
    androidRows = r.packages || {};
    androidScannedFor = androidDevice;
    androidScanError = "";
  } catch (e) {
    androidRows = null; androidScannedFor = null;
    androidScanError = e.message || "Cannot scan installed apps";
  } finally {
    if (paint) { androidBusy = ""; render(); }
  }
}

async function androidAct(label, path, body, ok) {
  if (androidBusy) return;
  androidBusy = label; androidNotice = null; render();
  try {
    const r = await api(path, {json:body});
    androidNotice = {bad:false, text: typeof ok === "function" ? ok(r) : ok};
    return r;
  } catch (e) {
    androidNotice = {bad:true, text:e.message};
  } finally {
    androidBusy = "";
    render();
  }
}

// Compare a catalog/imported APK with the scanned phone.
function androidStatus(pkg, versionCode) {
  const row = pkg && androidRows ? androidRows[pkg] : null;
  if (!row) return "Install";
  if (row.versionCode == null || versionCode == null) return "Reinstall";
  return row.versionCode >= versionCode ? "Installed" : "Update";
}

function androidStep1(expanded, busy) {
  const devices = androidState?.devices || [], live = androidConnected();
  const srv = androidState?.server || {};
  const first = live.find(d => d.address === androidDevice) || live[0];
  const subtitle = first ? `${esc(first.name)} · ${first.transport === "usb" ? "USB" : "Wi-Fi"}` :
    androidState ? "Not connected" : "Checking…";
  const serverLine = !androidState ? "" : `<div class="sl-android-server">ADB: ${srv.mode === "external" ? "computer's adb server · USB + Wi-Fi" : srv.hint ? "container · Wi-Fi only" : "container · Wi-Fi (USB on Linux hosts)"}${srv.hint ? `<br><span class="warn">${esc(srv.hint)}</span>` : ""}</div>`;
  const deviceRows = devices.map(d => {
    const on = d.state === "device", usb = d.transport === "usb";
    return `<div class="sl-app-entry">
      <span class="sl-app-detail"><b>${esc(d.name)}</b>
        <small>${usb ? "USB" : "Wi-Fi"} · ${esc(d.address)} · <span class="sl-android-state ${on ? "ok" : d.state === "unauthorized" ? "warn" : ""}">${on ? "Connected" : d.state === "unauthorized" ? (usb ? "Accept “Allow USB debugging?” on the phone" : "Not authorized — pair again") : "Offline"}</span></small></span>
      ${usb && on ? `<button type="button" class="cap solid" data-android-enable-wifi="${esc(d.address)}" ${busy ? "disabled" : ""}>${androidBusy === "wifi:" + d.address ? "Connecting…" : "Use over Wi-Fi"}</button>` : ""}
      ${usb ? "" : on ? `<button type="button" class="cap" data-android-disconnect="${esc(d.address)}" ${busy ? "disabled" : ""}>Disconnect</button>`
           : `<button type="button" class="cap" data-android-connect="${esc(d.address)}" ${busy ? "disabled" : ""}>Reconnect</button>`}
      ${d.saved ? `<button type="button" class="cap" data-android-forget="${esc(d.address)}" ${busy ? "disabled" : ""} aria-label="Forget ${esc(d.name)}">Forget</button>` : ""}
    </div>`;
  }).join("");
  const discovered = (androidState?.discovered || []).map(m =>
    `<button type="button" class="cap" data-android-connect="${esc(m.address)}" ${busy ? "disabled" : ""}>Connect ${esc(m.address)}</button>`).join("");
  const usbHelp = `<details class="sl-android-pair" id="android-usb-panel" ${(androidOpen.usb ?? !live.length) ? "open" : ""}>
    <summary>Option 1 · USB cable</summary>
    <ol class="sl-android-steps"><li>Settings → About phone → tap <b>Build number</b> 7 times to enable Developer options.</li>
      <li>Settings → System → Developer options → turn on <b>USB debugging</b>.</li>
      <li>Plug in with a data cable (not charge-only); if asked, choose <b>File transfer</b>.</li>
      <li>Unlock the phone and tap <b>Allow</b> on “Allow USB debugging?” (tick “Always allow”), then <b>Refresh</b>.</li></ol>
  </details>`;
  const wifi = `<details class="sl-android-pair" id="android-pair-panel" ${androidPairOpen ? "open" : ""}>
    <summary>Option 2 · Wi-Fi (Wireless debugging)</summary>
    ${devices.some(d=>d.transport==="usb"&&d.state==="device") ? '<p class="sl-android-auto-hint">USB phone detected. Use <b>Use over Wi-Fi</b> above to configure its Wi-Fi address automatically—no pairing IP, code, or connect port required.</p>' : ''}
    <div class="sl-android-grid">
      <label>Pairing IP:port<input class="fi" id="android-pair-address" placeholder="192.168.1.20:37123" inputmode="url" autocomplete="off"></label>
      <label>Pairing code<input class="fi" id="android-pair-code" placeholder="123456" inputmode="numeric" maxlength="6" autocomplete="one-time-code"></label>
      <button type="button" class="cap solid" id="android-pair" ${busy ? "disabled" : ""}>${androidBusy === "pair" ? "Pairing…" : "Pair"}</button>
      <label>Connect IP:port<input class="fi" id="android-connect-address" placeholder="192.168.1.20:41234" inputmode="url" autocomplete="off"></label>
      <span></span>
      <button type="button" class="cap solid" id="android-connect" ${busy ? "disabled" : ""}>${androidBusy === "connect" ? "Connecting…" : "Connect"}</button>
    </div>
    ${discovered ? `<div class="sl-android-found">Found on Wi-Fi: ${discovered}</div>` : ""}
    <ol class="sl-android-steps"><li>Android 11+, same Wi-Fi. Developer options → turn on <b>Wireless debugging</b>.</li>
      <li>Tap <b>Pair device with pairing code</b>; enter its IP:port and code above, then Pair.</li>
      <li>Enter the <b>IP address &amp; port</b> from the Wireless debugging screen, then Connect.</li>
      <li>The connect port changes when Wireless debugging restarts; Reconnect or enter the new port.</li></ol>
  </details>`;
  return renderSetupStep(1, "Connect your Android", subtitle, live.length > 0, `
    <div class="sl-android-step-tools"><button type="button" class="cap" id="android-refresh" ${busy ? "disabled" : ""}>${androidLoading ? "Checking…" : "Refresh"}</button></div>
    ${serverLine}
    <div class="list">${deviceRows || `<div class="foot">No phone connected.</div>`}</div>
    ${usbHelp}
    ${wifi}`, expanded);
}

function androidStep2(expanded, busy) {
  const live = androidConnected();
  const scanned = androidScannedFor && androidScannedFor === androidDevice && androidRows;
  const catalog = androidCatalog?.apps || [], imported = androidImported || [];
  const names = {};
  for (const a of catalog) if (a.package) names[a.package] ||= a.name;
  for (const a of imported) if (a.package) names[a.package] ||= a.name;
  const newest = {};
  for (const a of [...catalog, ...imported]) {
    if (!a.package || a.versionCode == null) continue;
    if (!newest[a.package] || a.versionCode > newest[a.package].versionCode) newest[a.package] = a;
  }
  const all = scanned ? Object.entries(androidRows).map(([pkg, r]) => ({pkg, ...r, name: r.name || names[pkg] || pkg})) : [];
  const rows = all.filter(r => androidShowAll || r.sideloaded || names[r.pkg])
    .sort((a, b) => a.name.localeCompare(b.name));
  const sideloadedCount = all.filter(r => r.sideloaded || names[r.pkg]).length;
  const subtitle = scanned ? `${sideloadedCount} installed sideloaded app${sideloadedCount === 1 ? "" : "s"}` :
    live.length ? "Scan Android to view installed apps" : "Connect a phone in Step 1";
  const mb = n => n ? `${(n / 1e6).toFixed(n < 1e7 ? 1 : 0)} MB` : "";
  const installedList = rows.map(r => {
    const upd = newest[r.pkg];
    const update = upd && r.versionCode != null && upd.versionCode > r.versionCode;
    const action = update ? (upd.origin ? `data-android-install="${esc(upd.id)}"` : `data-android-imported="${esc(upd.id)}"`) : "";
    return `<div class="sl-app-entry" data-package="${esc(r.pkg)}">
      <span class="sl-app-detail"><span class="sl-installed-main"><b>${esc(r.name)}</b>${update ? `<strong class="sl-android-update">Update ${esc(upd.versionName || "")} available</strong>` : ""}</span>
        <small>${esc(r.pkg)}${r.versionName ? " · " + esc(r.versionName) : ""}${r.versionCode != null ? " (" + r.versionCode + ")" : ""}${r.installer ? " · via " + esc(r.installer) : ""}</small></span>
      ${update ? `<button type="button" class="cap solid" ${action} ${busy ? "disabled" : ""}>${androidBusy === "install:" + upd.id ? "Updating…" : "Update"}</button>` : ""}
      <button type="button" class="cap" data-android-uninstall="${esc(r.pkg)}" ${busy ? "disabled" : ""}>${androidBusy === "uninstall:" + r.pkg ? "Removing…" : "Uninstall"}</button>
    </div>`;
  }).join("");
  const sourceRows = !androidCatalog ? `<div class="foot">Loading saved sources…</div>` : catalog.map(app => {
    const status = androidStatus(app.package, app.versionCode);
    const version = app.versionName || app.tag || "";
    return `<div class="sl-app-entry">
      <span class="sl-app-detail"><b>${esc(app.name)}</b>
        <small>${esc(version)}${version ? " · " : ""}${esc(app.source_name || "")}${app.size ? " · " + mb(app.size) : ""}</small></span>
      <button type="button" class="cap" data-android-install="${esc(app.id)}"
        ${busy || !androidDevice || status === "Installed" ? "disabled" : ""}>${androidBusy === "install:" + app.id ? "Installing…" : status}</button>
    </div>`;
  }).join("") || `<div class="foot">No Android apps in saved sources. Add an "android" entry to altstore.json or attach an .apk to a GitHub release.</div>`;
  const repos = (androidCatalog?.repos || []).filter(r => r.extra).map(r => `<span class="sl-android-repo">${esc(r.owner)}/${esc(r.repo)}<button type="button" data-android-repo-remove="${esc(r.owner)}/${esc(r.repo)}" aria-label="Remove ${esc(r.repo)}" ${busy ? "disabled" : ""}>×</button></span>`).join("");
  const warnings = (androidCatalog?.warnings || []).map(w => `<div class="foot">${esc(w)}</div>`).join("");
  const sources = `<section class="sl-add-category">
    <div class="sl-add-heading"><b>From Sources</b><a href="/sources">Manage sources</a></div>
    ${sourceRows}${warnings}
    <div class="sl-android-repos">${repos}
      <input class="fi" id="android-repo-url" placeholder="Extra GitHub repo with .apk releases" autocomplete="off">
      <button type="button" class="cap" id="android-repo-add" ${busy ? "disabled" : ""}>Add repo</button>
    </div>
  </section>`;
  const importedMarkup = `<section class="sl-add-category">
    <div class="sl-add-heading"><b>Imported APKs</b><button type="button" class="cap" id="android-import-apk" ${busy ? "disabled" : ""}>${androidBusy === "upload" ? "Importing…" : "Import APK"}</button>
      <input type="file" id="android-apk-file" accept=".apk,application/vnd.android.package-archive" hidden></div>
    ${imported.map(a => {
      const status = androidStatus(a.package, a.versionCode);
      return `<div class="sl-app-entry"><span class="sl-app-detail"><b>${esc(a.name)}</b>
        <small>${esc(a.versionName || "")}${a.versionCode != null ? " (" + a.versionCode + ")" : ""} · ${esc(a.package)}${a.size ? " · " + mb(a.size) : ""}</small></span>
        <button type="button" class="cap" data-android-imported="${esc(a.id)}" ${busy || !androidDevice || status === "Installed" ? "disabled" : ""}>${androidBusy === "install:" + a.id ? "Installing…" : status}</button>
        <button class="iconbtn" data-android-imported-remove="${esc(a.id)}" aria-label="Remove ${esc(a.name)}" ${busy ? "disabled" : ""}>${ic("trash-outline", 20)}</button></div>`;
    }).join("") || `<div class="foot">No imported APK files.</div>`}
  </section>`;
  const body = !live.length ? `<div class="foot">Connect an Android phone in Step 1 before managing apps.</div>` : `<div class="sl-app-manager">
    <div class="sl-app-toolbar">
      <label for="android-device-select">Android</label>
      <select class="fi" id="android-device-select">${live.map(d => `<option value="${esc(d.address)}" ${d.address === androidDevice ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</select>
      <button type="button" class="cap" id="android-scan" ${busy ? "disabled" : ""}>${androidBusy === "scan" ? "Scanning…" : "Scan Android"}</button>
      <button type="button" class="cap solid" id="android-add-app" ${busy ? "disabled" : ""}>${androidAddOpen ? "Close" : "Add app"}</button>
      <label class="sl-android-all"><input type="checkbox" id="android-show-all" ${androidShowAll ? "checked" : ""}> Show store apps</label>
    </div>
    ${androidScanError ? `<div class="foot" style="color:var(--red)">${esc(androidScanError)}</div>` : ""}
    <div class="sl-installed-title"><b>Installed apps</b>${scanned ? `<span>${rows.length}</span>` : ""}</div>
    ${!scanned ? '<div class="sl-empty-installed">Scan this phone to show installed apps.</div>' :
      rows.length ? `<div class="list sl-app-list">${installedList}</div>` : '<div class="sl-empty-installed">No sideloaded apps on this phone.</div>'}
    ${androidAddOpen ? `<div class="sl-add-apps">${sources}${importedMarkup}</div>` : ""}
  </div>`;
  return renderSetupStep(2, "Apps", subtitle, Boolean(scanned && sideloadedCount), body, expanded);
}

function androidView() {
  if (!androidState && !androidLoading) setTimeout(() => androidLoad(), 0);
  const busy = Boolean(androidBusy) || androidLoading;
  // Share the Apple steps' open/closed choice; default to the next useful step.
  const preferred = androidConnected().length ? 2 : 1;
  const expanded = setupChoice === null ? preferred : setupChoice;
  const notice = androidNotice ? `<div class="sl-android-notice ${androidNotice.bad ? "bad" : "ok"}">${esc(androidNotice.text)}</div>` : "";
  return `${notice}${androidStep1(expanded, busy)}${androidStep2(expanded, busy)}`;
}

async function androidUpload(file) {
  if (!file || androidBusy) return;
  if (!/\.apk$/i.test(file.name)) { androidNotice = {bad:true, text:"Choose an .apk file"}; render(); return; }
  androidBusy = "upload"; androidNotice = null; render();
  try {
    const r = await fetch("/api/apk", {method:"PUT", body:file,
      headers:{"X-Requested-With":"sideloop", "X-Filename":encodeURIComponent(file.name)}});
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    androidImported = [...(androidImported || []).filter(a => a.id !== data.apk.id), data.apk];
    androidNotice = {bad:false, text:`${data.apk.name} ${data.apk.versionName || ""} imported.`};
    androidAddOpen = true;
  } catch (e) {
    androidNotice = {bad:true, text:"Import failed: " + e.message};
  } finally {
    androidBusy = "";
    render();
  }
}

function androidWire() {
  const val = id => (document.getElementById(id)?.value || "").trim();
  const clear = id => { const el = document.getElementById(id); if (el) el.value = ""; };
  root.querySelectorAll('input[name="sl-platform"]').forEach(input => input.onchange = () => {
    slPlatform = input.value === "android" ? "android" : "apple";
    try { localStorage.setItem("sideloaderPlatform", slPlatform); } catch {}
    setupChoice = null;
    render();
  });
  if (slPlatform !== "android") return;
  const button = (id, fn) => { const el = document.getElementById(id); if (el) el.onclick = fn; };
  const panel = document.getElementById("android-pair-panel");
  if (panel) panel.ontoggle = () => { androidPairOpen = panel.open; };
  const usbPanel = document.getElementById("android-usb-panel");
  if (usbPanel) usbPanel.ontoggle = () => { androidOpen.usb = usbPanel.open; };
  button("android-refresh", () => { androidNotice = null; androidLoad(true); });
  button("android-pair", async () => {
    const r = await androidAct("pair", "/api/android/pair", {address:val("android-pair-address"), code:val("android-pair-code")}, r => r.message);
    if (r) { clear("android-pair-code"); clear("android-pair-address"); }
  });
  const connect = async address => {
    const r = await androidAct("connect", "/api/android/connect", {address}, r => `Connected to ${r.name}.`);
    if (r) { androidDevice = address; clear("android-connect-address"); setupChoice = 2; await androidLoad(); }
  };
  button("android-connect", () => connect(val("android-connect-address")));
  root.querySelectorAll("[data-android-connect]").forEach(b => b.onclick = () => connect(b.dataset.androidConnect));
  root.querySelectorAll("[data-android-enable-wifi]").forEach(b => b.onclick = async () => {
    const serial=b.dataset.androidEnableWifi;
    const r=await androidAct("wifi:"+serial,"/api/android/enable-wifi",{device:serial},r=>r.message);
    if(r){androidDevice=r.address;androidPairOpen=false;await androidLoad(true);}
  });
  root.querySelectorAll("[data-android-disconnect]").forEach(b => b.onclick = async () => {
    await androidAct("disconnect", "/api/android/disconnect", {address:b.dataset.androidDisconnect}, "Disconnected.");
    await androidLoad();
  });
  root.querySelectorAll("[data-android-forget]").forEach(b => b.onclick = async () => {
    if (!window.confirm("Forget this phone? Pair again to reconnect over Wi-Fi.")) return;
    await androidAct("forget", "/api/android/disconnect", {address:b.dataset.androidForget, forget:true}, "Phone forgotten.");
    await androidLoad();
  });
  const select = document.getElementById("android-device-select");
  if (select) select.onchange = () => { androidDevice = select.value; androidRows = null; androidScannedFor = null; androidScan(); };
  button("android-scan", () => androidScan());
  button("android-add-app", () => { androidAddOpen = !androidAddOpen; render(); });
  const all = document.getElementById("android-show-all");
  if (all) all.onchange = () => { androidShowAll = all.checked; render(); };
  const install = async (body, name) => {
    const key = "install:" + (body.id || body.imported);
    const r = await androidAct(key, "/api/android/install", {...body, device:androidDevice},
      r => `${name} ${r.versionName || ""} installed.`);
    if (r) await androidScan();
  };
  root.querySelectorAll("[data-android-install]").forEach(b => b.onclick = () => {
    const app = (androidCatalog?.apps || []).find(a => a.id === b.dataset.androidInstall);
    if (app && androidDevice) install({id:app.id}, app.name);
  });
  root.querySelectorAll("[data-android-imported]").forEach(b => b.onclick = () => {
    const apk = (androidImported || []).find(a => a.id === b.dataset.androidImported);
    if (apk && androidDevice) install({imported:apk.id}, apk.name);
  });
  root.querySelectorAll("[data-android-uninstall]").forEach(b => b.onclick = async () => {
    const pkg = b.dataset.androidUninstall;
    const name = androidRows?.[pkg]?.name || pkg;
    if (!window.confirm(`Uninstall ${name} from this phone? Its app data is deleted.`)) return;
    const r = await androidAct("uninstall:" + pkg, "/api/android/uninstall",
      {device:androidDevice, package:pkg, acknowledge:true}, `${name} uninstalled.`);
    if (r) await androidScan();
  });
  const file = document.getElementById("android-apk-file");
  button("android-import-apk", () => file?.click());
  if (file) file.onchange = () => androidUpload(file.files[0]);
  root.querySelectorAll("[data-android-imported-remove]").forEach(b => b.onclick = async () => {
    if (!window.confirm("Remove this imported APK file? Installed apps stay on the phone.")) return;
    const id = b.dataset.androidImportedRemove;
    const r = await androidAct("imported", "/api/android/imported/remove", {id}, "Imported APK removed.");
    if (r) { androidImported = (androidImported || []).filter(a => a.id !== id); render(); }
  });
  button("android-repo-add", async () => {
    const r = await androidAct("repo", "/api/android/repos/add", {url:val("android-repo-url")}, "Repository added.");
    if (r) { clear("android-repo-url"); await androidLoad(true); }
  });
  root.querySelectorAll("[data-android-repo-remove]").forEach(b => b.onclick = async () => {
    const [owner, repo] = b.dataset.androidRepoRemove.split("/");
    const r = await androidAct("repo", "/api/android/repos/remove", {owner, repo}, "Repository removed.");
    if (r) await androidLoad(true);
  });
}
/* SideLoader Android v1 end */
