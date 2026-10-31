/* SideLoader screen workflow v1: actions replace Apps screen, never open a modal. */
let slFlow=null, slFlowError="", slFlowBusy=false;

function slScreen(mode,data={}) {
  slFlow={...data,mode}; slFlowError="";
  view=data.screenView==="activity"?"activity":"apps"; history.replaceState(null,"","#"+view);
  lastPage=null; render(); window.scrollTo({top:0,behavior:"smooth"});
}
function slHome(){slFlow=null;slFlowError="";lastPage=null;render();if(view==="activity")loadLogs();}
function slMessage(title,message){slScreen("message",{title,message});}
function slInstall(app,udid,installed=false){
  if(!app||!udid)return slMessage("Select an iPhone","Choose an iPhone and an app first.");
  if(S.job?.running||S.watcher?.running)return slMessage("Task in progress","Finish the current task before installing another app.");
  const data={appId:app.id,name:app.name,udid,installed};
  slScreen(S.signing_guard?.blocked?"paused":"confirm",data);
}
function slRemoveApps(udid,bundles,nextApp=null){
  if(!udid||!bundles.length)return;
  const names=bundles.map(id=>deviceAppRows.find(r=>r.bundle_id===id)?.name||id);
  slScreen("uninstall",{udid,bundles,names,nextApp});
}
function slScreenView(){
  if(!slFlow)return "";
  const f=slFlow,j=f.mode==="job"&&f.jobId&&S.job?.id===f.jobId?S.job:null;
  const name=esc(f.name||""),phone=esc((S.registered||[]).find(d=>d.udid===f.udid)?.name||"iPhone");
  let title="",body="",buttons="";
  if(f.mode==="confirm"){
    title=f.installed?"Re-sign app":"Install on iPhone";
    body='<div class="sl-screen-emoji">📱</div><h2>'+name+'</h2><p>Device: <b>'+phone+'</b></p><p>This starts one Apple signing attempt. A six-digit code may be requested. You will have 60 seconds to enter it on this screen.</p><p class="sl-screen-note">Failed signing is never automatically retried.</p>';
    buttons='<button type="button" class="btn" id="sl-screen-install">Confirm '+(f.installed?"re-sign":"install")+'</button>';
  }else if(f.mode==="paused"||f.mode==="resume"){
    title="Signing paused";
    body='<div class="sl-screen-emoji">🔒</div><h2>No new Apple request was started</h2><p>'+
      esc(S.signing_guard?.message||"The last signing attempt was not verified.")+'</p><p class="sl-screen-note">'+
      esc(S.signing_guard?.action||"Review the issue before allowing another attempt.")+'</p><p>Unlocking the safety lock does not contact Apple. You must separately confirm installation.</p>';
    buttons='<button type="button" class="btn" id="sl-screen-resume">Issue resolved — allow one attempt</button>';
  }else if(f.mode==="uninstall"){
    title="Remove apps from iPhone";
    body='<div class="sl-screen-emoji">🗑️</div><h2>Confirm device removal</h2><p>These apps and their on-device data may be deleted from '+phone+':</p><ul>'+
      (f.names||[]).map(n=>'<li>'+esc(n)+'</li>').join("")+
      '</ul><p class="sl-screen-note">Saved IPA files remain. This does not sign in to Apple.</p>';
    buttons='<button type="button" class="btn sl-screen-danger" id="sl-screen-uninstall">Remove from iPhone</button>';
  }else if(f.mode==="logs"){
    title="Clear Activity logs";
    body='<div class="sl-screen-emoji">🧹</div><h2>Delete old Activity logs?</h2><p>This permanently clears saved signing logs and completed job output. Saved IPAs, pairing, Apple credentials and the signing safety lock remain unchanged.</p><p class="sl-screen-note">No Apple sign-in is started. Logs cannot be cleared during an active job.</p>';
    buttons='<button type="button" class="btn sl-screen-danger" id="sl-screen-clear-logs">Clear old logs</button>';
  }else if(f.mode==="account"){
    title="Remove Apple Account";
    body='<div class="sl-screen-emoji">🔐</div><h2>Delete saved credentials?</h2><p>SideLoader removes your saved Apple Account credentials and disables renewal. Saved IPAs and pairing remain.</p>';
    buttons='<button type="button" class="btn sl-screen-danger" id="sl-screen-remove-account">Remove saved account</button>';
  }else if(f.mode==="job"){
    const verifying=!!(j?.running&&j.needs_input&&j.accepts_input);
    const finished=!!(j&&!j.running);
    const failed=finished&&(j.rc!==0||(j.kind==="refresh"&&S.signing_guard?.blocked));
    const good=finished&&!failed;
    const last=(jobLines||[]).filter(t=>/error|failed|unable to|could not|cancel|[-]36607|[-]80046/i.test(t)).slice(-1)[0];
    const explanation=failed?(S.signing_guard?.message||last||"The operation failed."):"Installation finished and verified by the server.";
    title=verifying?"Apple verification":failed?"Installation failed":good?"Installation complete":esc(j?.title||f.title||"Installing…");
    body='<div class="sl-screen-emoji">'+(verifying?"🔢":failed?"⚠️":good?"✅":"⚙️")+
      '</div><h2>'+title+'</h2>';
    if(verifying){
      body+='<p>Enter the code Apple sent to your trusted device. You have '+(j.verification_seconds_remaining??60)+' seconds remaining.</p>'+
        '<form id="sl-screen-otp-form"><label for="sl-screen-otp">Six-digit code</label>'+
        '<input id="sl-screen-otp" type="text" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" minlength="6" required placeholder="000000">'+
        '<button type="submit" class="btn" '+(slFlowBusy?"disabled":"")+'>Verify</button></form>';
    }else if(finished){
      body+='<p>'+esc(explanation)+'</p>';
    }else{
      const stages=["Apple sign-in","Signing IPA","Sending to device","Verifying installation"];
      const idx=Math.max(0,["signin","sign","send","install"].indexOf(j?.stage||""));
      const percent=Math.min(98,Math.round((idx*23)+8+10*(j?.fraction||0)));
      body+='<p>Keep your iPhone unlocked and connected.</p><div class="sl-screen-meter"><span style="width:'+percent+'%"></span></div>'+
        '<ol class="sl-screen-stages">'+stages.map((n,i)=>'<li class="'+(i===idx?"active":i<idx?"done":"")+'">'+n+'</li>').join("")+'</ol>';
    }
    body+='<details class="sl-screen-details"><summary>Technical details</summary><pre>'+esc((jobLines||[]).slice(-35).join("\n")||"Starting…")+'</pre></details>';
    if(j?.running)buttons='<button type="button" class="cap" id="sl-screen-cancel">Cancel attempt</button>';
  }else{
    title=f.title||"Notice";
    body='<div class="sl-screen-emoji">ℹ️</div><h2>'+esc(title)+'</h2><p>'+esc(f.message||"")+'</p>';
  }
  const context=f.screenView==="activity"?"Activity":"Apps / Step 3";
  return '<section class="sl-screen" aria-label="'+esc(title)+'">'+
    '<div class="sl-screen-top"><button type="button" class="cap" id="sl-screen-back">← '+(f.screenView==="activity"?"Activity":"Apps")+'</button><span>'+context+'</span></div>'+
    '<div class="sl-screen-body">'+body+(slFlowError?'<p class="sl-screen-error" role="alert">'+esc(slFlowError)+'</p>':"")+
    '<div class="sl-screen-actions">'+buttons+'</div></div></section>';
}
async function slStartJob(path,payload={}){
  if(slFlowBusy)return;
  slFlowBusy=true;
  slScreen("job",{jobId:null,title:path==="/api/recheck"?"Checking installed apps":path==="/api/pair"?"Connecting iPhone":"Installing app"});
  try{
    // A newly imported source IPA may not yet be assigned to this iPhone.
    // Preserve its existing targets; assigning locally does not sign in to Apple.
    if(path==="/api/refresh"&&payload.app&&payload.device){
      const app=(S.apps||[]).find(a=>a.id===payload.app);
      if(app&&!(app.targets||[]).some(t=>t.udid===payload.device)){
        const devices=[...(app.targets||[]).map(t=>t.udid),payload.device];
        await api("/api/app/devices",{json:{app:app.id,devices}});
        await refresh();
      }
    }
    const r=await api(path,{json:payload});
    if(!r?.job)throw Error("The server did not create a task.");
    watched.add(r.job);dismissedJob=null;slFlow.jobId=r.job;
    await refresh();
    if(S.job?.id===r.job)await pullJob();
    slFlowBusy=false;render();poll();
  }catch(e){slFlowBusy=false;slMessage("Task not started",e.message);}
}
async function slAcceptInstall(){
  if(slFlowBusy||slFlow?.mode!=="confirm")return;
  const data={app:slFlow.appId,device:slFlow.udid,force:true};
  if(S.signing_guard?.blocked)return slScreen("paused",slFlow);
  await slStartJob("/api/refresh",data);
}
async function slResume(){
  if(slFlowBusy)return;slFlowBusy=true;render();
  const previous={...slFlow};
  try{
    await api("/api/signing/resume",{json:{acknowledge:true}});await refresh();slFlowBusy=false;
    if(previous.appId&&previous.udid)slScreen("confirm",previous);
    else slMessage("Signing unlocked","One new attempt is permitted. Choose an app in Step 3 to continue.");
  }catch(e){slFlowBusy=false;slFlowError=e.message;render();}
}
async function slConfirmRemove(){
  if(slFlowBusy||slFlow?.mode!=="uninstall")return;
  const f={...slFlow};slFlowBusy=true;render();
  try{
    await api("/api/device/apps/remove",{json:{device:f.udid,bundles:f.bundles,acknowledge:true}});
    await scanDeviceApps(f.udid);slFlowBusy=false;
    const next=(S.apps||[]).find(app=>app.id===f.nextApp);
    if(next)slInstall(next,f.udid,false);
    else slMessage("Apps removed","The device removal was confirmed. Saved IPA files are untouched.");
  }catch(e){slFlowBusy=false;slFlowError=e.message;render();}
}
async function slConfirmAccount(){
  if(slFlowBusy)return;slFlowBusy=true;render();
  try{
    await api("/api/appleid/remove",{json:{}});await refresh();slFlowBusy=false;
    setupChoice=2;setupDoneSnapshot=null;
    slMessage("Account removed","Saved credentials were cleared; your apps and pairing were preserved.");
  }catch(e){slFlowBusy=false;slFlowError=e.message;render();}
}
async function slClearLogs(){
  if(slFlowBusy)return;
  slFlowBusy=true;render();
  try{
    await api("/api/logs/clear",{json:{acknowledge:true}});
    slFlowBusy=false;slScreen("message",{title:"Logs cleared",message:"Old Activity logs were deleted. The signing safety lock and saved apps were preserved.",screenView:"activity"});
  }catch(e){slFlowBusy=false;slFlowError=e.message;render();}
}
async function slVerifyCode(e){
  e.preventDefault();
  const input=document.getElementById("sl-screen-otp");
  const code=input?.value.trim()||"";
  if(!/^[0-9]{6}$/.test(code)){slFlowError="Enter exactly six digits.";render();return;}
  if(!S.job?.running||!S.job.needs_input){slFlowError="No active verification request.";render();return;}
  if(slFlowBusy)return;
  input.value="";slFlowBusy=true;slFlowError="";render();
  try{await api("/api/job/input",{json:{text:code}});}catch(err){slFlowError=err.message;}
  slFlowBusy=false;await poll();
}
function slWireScreen(){
  const on=(id,event,fn)=>{const el=document.getElementById(id);if(el)el[event]=fn;};
  on("sl-screen-back","onclick",slHome);
  on("sl-screen-install","onclick",slAcceptInstall);
  on("sl-screen-resume","onclick",slResume);
  on("sl-screen-uninstall","onclick",slConfirmRemove);
  on("sl-screen-remove-account","onclick",slConfirmAccount);
  on("sl-screen-clear-logs","onclick",slClearLogs);
  on("sl-screen-otp-form","onsubmit",slVerifyCode);
  on("sl-screen-cancel","onclick",async()=>{
    try{await api("/api/job/cancel",{json:{}});await poll();}
    catch(e){slFlowError=e.message;render();}
  });
  // Older Step 3 install buttons use data-sign (not the Apps manager
  // data-device-app-action handler). Both must show the same confirmation
  // screen before a single Apple authentication request is permitted.
  document.querySelectorAll("[data-sign]").forEach(button => {
    button.onclick = () => {
      const app=(S.apps||[]).find(a=>a.id===button.dataset.sign);
      const udid=button.dataset.dev||(S.registered||[])[0]?.udid;
      const installed=Boolean(app?.targets?.some(t=>t.udid===udid&&t.installation?.state==="installed"));
      slInstall(app,udid,installed);
    };
  });
  on("signall","onclick",()=>slMessage("Choose one app","Use Install or Re-sign on an app in Step 3. Bulk signing is not started."));
  // Override legacy browser confirmation handlers with in-page screens.
  on("sideloader-resume","onclick",()=>slScreen("resume"));
  on("useipa","onclick",async()=>{
    if(!pending?.filename)return slMessage("No IPA selected","Choose an IPA in Step 3 first.");
    const filename=pending.filename;
    try{
      await api("/api/ipa/use",{json:{filename}});
      pending=null;
      await refresh();
      slMessage("IPA imported", filename+" is saved in SideLoader. Select Install in Apps / Step 3 to add it to your iPhone.");
    }catch(e){slMessage("IPA import failed",e.message);}
  });
  on("sideloader-remove-account","onclick",()=>slScreen("account"));
  on("sideloader-clear-logs","onclick",()=>slScreen("logs",{screenView:"activity"}));
}
