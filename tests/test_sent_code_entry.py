"""Front-end flow: Apple says code sent before AltServer's stdin is ready."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCREEN = ROOT / "overlay" / "screen-flow-ui.js"

NODE_CASE = r"""
const fs = require('fs');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const S = {
  registered:[{udid:'p',name:'Test iPhone'}],
  apps:[], watcher:{running:false}, signing_guard:{blocked:false}, job:null
};
const ctx = {
  S, view:'apps', lastPage:'', jobLines:[], dismissedJob:null,
  setupChoice:null, setupDoneSnapshot:null, pending:null,
  document:{getElementById(){return null},querySelectorAll(){return []}},
  window:{scrollTo(){}}, history:{replaceState(){}},
  render(){}, loadLogs(){}, refresh:async()=>{}, pullJob:async()=>{},
  poll:async()=>{}, scanDeviceApps:async()=>{}, watched:new Set(),
  deviceAppRows:[], api:async()=>({}),
  esc:s=>String(s??'').replace(/</g,'&lt;')
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
ctx.slScreen('job',{jobId:'123',title:'Installing app'});
S.job = {
  id:'123', kind:'refresh', running:true, needs_input:false,
  accepts_input:true, stage:'signin', verification_delivery:'not_reported'
};
let html=ctx.slScreenView();
assert(!html.includes('id="sl-screen-otp"'), 'no code means no entry');

S.job.verification_delivery='reported_sent';
html=ctx.slScreenView();
assert(html.includes('Apple reports verification code sent'), 'show sent state');
assert(html.includes('id="sl-screen-otp"'), 'show entry immediately');
assert(html.includes('disabled>Preparing verification…'), 'do not send early');

S.job.needs_input=true;
S.job.verification_seconds_remaining=45;
html=ctx.slScreenView();
assert(html.includes('id="sl-screen-otp"'), 'keep entry visible');
assert(html.includes('>Verify code</button>'), 'enable submit on PTY request');
assert(html.includes('45 seconds'), 'show actual countdown');

S.job.verification_delivery='requested_unconfirmed';
html=ctx.slScreenView();
assert(html.includes('Verification code requested · delivery unconfirmed'));
assert(html.includes('id="sl-screen-otp"'));

S.job.running=false; S.job.rc=1; S.job.needs_input=false;
html=ctx.slScreenView();
assert(!html.includes('id="sl-screen-otp"'), 'close entry on failure');

console.log('Sent-code entry flow passed all 5 simulated states');
"""

class SentCodeEntryTests(unittest.TestCase):
    def test_sent_code_opens_input_before_console_callback(self):
        which=subprocess.run(["which", "node"], capture_output=True)
        if which.returncode:
            self.skipTest("Node.js unavailable")
        result=subprocess.run(
            ["node","-e",NODE_CASE,str(SCREEN)],
            text=True,capture_output=True
        )
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)

if __name__=="__main__":
    unittest.main()
