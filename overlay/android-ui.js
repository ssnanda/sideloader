/* SideLoader Android v1 start */
// Apple/Android switch at the top of Apps. Apple keeps the existing flow;
// Android pairs a phone over Wireless debugging and installs GitHub APKs.
let slPlatform = "apple";
try { if (localStorage.getItem("sideloaderPlatform") === "android") slPlatform = "android"; } catch {}
let slPlatformInner = false;
let androidState = null, androidCatalog = null, androidPackages = null, androidPackagesFor = null;
let androidDevice = null, androidBusy = "", androidNotice = null, androidLoading = false;
let androidPairOpen = null; // Wi-Fi panel; closed until opened
const androidOpen = {usb:null}; // USB help: open while no phone is connected

function slPlatformView() {
  const pick = (value, label) => `<label class="${slPlatform === value ? "on" : ""}">
    <input type="radio" name="sl-platform" value="${value}" ${slPlatform === value ? "checked" : ""}>${label}</label>`;
  const head = `<div class="sl-platform" role="radiogroup" aria-label="Platform">${pick("apple", "Apple")}${pick("android", "Android")}</div>`;
  if (slPlatform === "android") return head + androidView();
  slPlatformInner = true;
  try { return head + appsView(); } finally { slPlatformInner = false; }
}

function androidConnected() {
  return (androidState?.devices || []).filter(d => d.state === "device");
}

async function androidLoad(force=false) {
  if (androidLoading) return;
  androidLoading = true;
  render();
  try {
    androidState = await api("/api/android/state");
    const live = androidConnected();
    if (!live.some(d => d.address === androidDevice)) androidDevice = live[0]?.address || null;
    androidCatalog = await api("/api/android/catalog" + (force ? "?force=1" : ""));
    await androidLoadPackages();
  } catch (e) {
    androidNotice = {bad:true, text:e.message};
    if (!androidState) androidState = {devices:[], discovered:[]};
    if (!androidCatalog) androidCatalog = {apps:[], repos:[], warnings:[]};
  } finally {
    androidLoading = false;
    render();
  }
}

async function androidLoadPackages() {
  androidPackages = null; androidPackagesFor = null;
  if (!androidDevice) return;
  const r = await api("/api/android/installed?device=" + encodeURIComponent(androidDevice));
  androidPackages = r.packages || {};
  androidPackagesFor = androidDevice;
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

function androidAppStatus(app) {
  if (!androidPackages || !app.package || !(app.package in androidPackages)) return "Install";
  const have = androidPackages[app.package];
  if (have == null || app.versionCode == null) return "Reinstall";
  return have >= app.versionCode ? "Installed" : "Update";
}

function androidView() {
  if (!androidState && !androidLoading) setTimeout(() => androidLoad(), 0);
  const devices = androidState?.devices || [], live = androidConnected();
  const busy = Boolean(androidBusy) || androidLoading;
  const mb = n => n ? `${(n / 1e6).toFixed(n < 1e7 ? 1 : 0)} MB` : "";
  const notice = androidNotice ? `<div class="sl-android-notice ${androidNotice.bad ? "bad" : "ok"}">${esc(androidNotice.text)}</div>` : "";
  const deviceRows = devices.map(d => {
    const on = d.state === "device", usb = d.transport === "usb";
    return `<div class="sl-app-entry">
      ${on ? `<span class="sl-app-select"><input type="radio" name="android-device" data-android-device="${esc(d.address)}" ${d.address === androidDevice ? "checked" : ""} aria-label="Use ${esc(d.name)}"></span>` : ""}
      <span class="sl-app-detail"><b>${esc(d.name)}</b>
        <small>${usb ? "USB" : "Wi-Fi"} · ${esc(d.address)} · <span class="sl-android-state ${on ? "ok" : d.state === "unauthorized" ? "warn" : ""}">${on ? "Connected" : d.state === "unauthorized" ? (usb ? "Accept “Allow USB debugging?” on the phone" : "Not authorized — pair again") : "Offline"}</span></small></span>
      ${usb ? "" : on ? `<button type="button" class="cap" data-android-disconnect="${esc(d.address)}" ${busy ? "disabled" : ""}>Disconnect</button>`
           : `<button type="button" class="cap" data-android-connect="${esc(d.address)}" ${busy ? "disabled" : ""}>Reconnect</button>`}
      ${d.saved ? `<button type="button" class="cap" data-android-forget="${esc(d.address)}" ${busy ? "disabled" : ""} aria-label="Forget ${esc(d.name)}">Forget</button>` : ""}
    </div>`;
  }).join("");
  const discovered = (androidState?.discovered || []).map(m =>
    `<button type="button" class="cap" data-android-connect="${esc(m.address)}" ${busy ? "disabled" : ""}>Connect ${esc(m.address)}</button>`).join("");
  const srv = androidState?.server || {};
  const serverLine = !androidState ? "" : `<div class="sl-android-server">ADB: ${srv.mode === "external" ? "computer's adb server · USB + Wi-Fi" : srv.usb === false && srv.hint ? "container · Wi-Fi only" : "container · Wi-Fi (USB on Linux hosts)"}${srv.hint ? `<br><span class="warn">${esc(srv.hint)}</span>` : ""}</div>`;
  const usbHelp = `<details class="sl-android-pair" id="android-usb-panel" ${(androidOpen.usb ?? !devices.length) ? "open" : ""}>
    <summary>Option 1 · USB cable</summary>
    <ol class="sl-android-steps"><li>Settings → About phone → tap <b>Build number</b> 7 times to enable Developer options.</li>
      <li>Settings → System → Developer options → turn on <b>USB debugging</b>.</li>
      <li>Plug in with a data cable (not charge-only); if asked, choose <b>File transfer</b>.</li>
      <li>Unlock the phone and tap <b>Allow</b> on “Allow USB debugging?” (tick “Always allow”), then <b>Refresh</b>.</li></ol>
  </details>`;
  const pairForm = `<details class="sl-android-pair" id="android-pair-panel" ${(androidPairOpen ?? false) ? "open" : ""}>
    <summary>Option 2 · Wi-Fi (Wireless debugging)</summary>
    <div class="sl-android-grid">
      <label>Pairing IP:port<input class="fi" id="android-pair-address" placeholder="192.168.1.20:37123" inputmode="url" autocomplete="off"></label>
      <label>Pairing code<input class="fi" id="android-pair-code" placeholder="123456" inputmode="numeric" maxlength="6" autocomplete="one-time-code"></label>
      <button type="button" class="cap solid" id="android-pair" ${busy ? "disabled" : ""}>${androidBusy === "pair" ? "Pairing…" : "Pair"}</button>
      <label>Connect IP:port<input class="fi" id="android-connect-address" placeholder="192.168.1.20:41234" inputmode="url" autocomplete="off"></label>
      <span></span>
      <button type="button" class="cap solid" id="android-connect" ${busy ? "disabled" : ""}>${androidBusy === "connect" ? "Connecting…" : "Connect"}</button>
    </div>
    ${discovered ? `<div class="sl-android-found">Found on Wi-Fi: ${discovered}</div>` : ""}
    <details class="sl-android-help"><summary>How to</summary>
      <ol><li>Phone and this computer on the same Wi-Fi; Android 11 or newer.</li>
      <li>Settings → About phone → tap <b>Build number</b> 7 times to enable Developer options.</li>
      <li>Settings → System → Developer options → turn on <b>Wireless debugging</b>.</li>
      <li>Tap <b>Pair device with pairing code</b>; enter its IP:port and 6-digit code above, then Pair.</li>
      <li>Back on the Wireless debugging screen, enter the <b>IP address &amp; port</b> shown there, then Connect.</li>
      <li>The connect port changes when Wireless debugging restarts; Reconnect or enter the new port.</li></ol>
    </details>
  </details>`;
  const apps = androidCatalog?.apps || [];
  const appRows = !androidCatalog ? `<div class="foot">Loading GitHub releases…</div>` : apps.map(app => {
    const status = androidAppStatus(app);
    const installing = androidBusy === "install:" + app.id;
    const version = app.versionName || app.tag;
    return `<div class="sl-app-entry">
      <span class="sl-app-detail"><b>${esc(app.name)}</b>
        <small>${esc(version)} · ${esc(app.owner)}/${esc(app.repo)}${app.size ? " · " + mb(app.size) : ""}${app.package ? " · " + esc(app.package) : ""}</small></span>
      <button type="button" class="cap ${status === "Installed" ? "" : "solid"}" data-android-install="${esc(app.id)}"
        ${busy || !androidDevice || status === "Installed" ? "disabled" : ""}>${installing ? "Installing…" : status}</button>
    </div>`;
  }).join("") || `<div class="foot">No .apk files in the latest GitHub releases of these repositories.</div>`;
  const repos = (androidCatalog?.repos || []).map(r => `<span class="sl-android-repo">${esc(r.owner)}/${esc(r.repo)}${r.extra
      ? `<button type="button" data-android-repo-remove="${esc(r.owner)}/${esc(r.repo)}" aria-label="Remove ${esc(r.repo)}" ${busy ? "disabled" : ""}>×</button>` : ""}</span>`).join("");
  const warnings = (androidCatalog?.warnings || []).map(w => `<div class="foot">${esc(w)}</div>`).join("");
  return `${notice}
  <section class="sl-add-category sl-android-section">
    <div class="sl-add-heading"><b>Android phone</b><button type="button" class="cap" id="android-refresh" ${busy ? "disabled" : ""}>${androidLoading ? "Checking…" : "Refresh"}</button></div>
    ${serverLine}
    ${deviceRows || `<div class="foot">No phone connected.</div>`}
    ${usbHelp}
    ${pairForm}
  </section>
  <section class="sl-add-category sl-android-section">
    <div class="sl-add-heading"><b>Apps from GitHub releases</b>${live.length ? "" : `<small>Connect a phone to install</small>`}</div>
    ${appRows}
    ${warnings}
    <div class="sl-android-repos">${repos}
      <input class="fi" id="android-repo-url" placeholder="https://github.com/owner/repo" autocomplete="off">
      <button type="button" class="cap" id="android-repo-add" ${busy ? "disabled" : ""}>Add repo</button>
    </div>
  </section>`;
}

function androidWire() {
  const val = id => (document.getElementById(id)?.value || "").trim();
  const clear = id => { const el = document.getElementById(id); if (el) el.value = ""; };
  root.querySelectorAll('input[name="sl-platform"]').forEach(input => input.onchange = () => {
    slPlatform = input.value === "android" ? "android" : "apple";
    try { localStorage.setItem("sideloaderPlatform", slPlatform); } catch {}
    render();
  });
  if (slPlatform !== "android") return;
  const panel = document.getElementById("android-pair-panel");
  if (panel) panel.ontoggle = () => { androidPairOpen = panel.open; };
  const usbPanel = document.getElementById("android-usb-panel");
  if (usbPanel) usbPanel.ontoggle = () => { androidOpen.usb = usbPanel.open; };
  const button = (id, fn) => { const el = document.getElementById(id); if (el) el.onclick = fn; };
  button("android-refresh", () => { androidNotice = null; androidLoad(true); });
  button("android-pair", async () => {
    const r = await androidAct("pair", "/api/android/pair", {address:val("android-pair-address"), code:val("android-pair-code")}, r => r.message);
    if (r) { clear("android-pair-code"); clear("android-pair-address"); }
  });
  const connect = async address => {
    const r = await androidAct("connect", "/api/android/connect", {address}, r => `Connected to ${r.name}.`);
    if (r) { androidDevice = address; clear("android-connect-address"); await androidLoad(); }
  };
  button("android-connect", () => connect(val("android-connect-address")));
  root.querySelectorAll("[data-android-connect]").forEach(b => b.onclick = () => connect(b.dataset.androidConnect));
  root.querySelectorAll("[data-android-disconnect]").forEach(b => b.onclick = async () => {
    await androidAct("disconnect", "/api/android/disconnect", {address:b.dataset.androidDisconnect}, "Disconnected.");
    await androidLoad();
  });
  root.querySelectorAll("[data-android-forget]").forEach(b => b.onclick = async () => {
    if (!window.confirm("Forget this phone? Pair again to reconnect.")) return;
    await androidAct("forget", "/api/android/disconnect", {address:b.dataset.androidForget, forget:true}, "Phone forgotten.");
    await androidLoad();
  });
  root.querySelectorAll("[data-android-device]").forEach(r => r.onchange = async () => {
    androidDevice = r.dataset.androidDevice;
    try { await androidLoadPackages(); } catch (e) { androidNotice = {bad:true, text:e.message}; }
    render();
  });
  root.querySelectorAll("[data-android-install]").forEach(b => b.onclick = async () => {
    const app = (androidCatalog?.apps || []).find(a => a.id === b.dataset.androidInstall);
    if (!app || !androidDevice) return;
    const r = await androidAct("install:" + app.id, "/api/android/install", {id:app.id, device:androidDevice},
      r => `${app.name} ${r.versionName || ""} installed.`);
    if (r) await androidLoad();
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
