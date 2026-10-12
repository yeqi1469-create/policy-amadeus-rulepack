"""Real signed EXE replacement/relaunch, isolated from the user's program."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from update_storage import write_json

candidate=Path(sys.argv[1]).resolve()
version=sys.argv[2]
root=Path('tmp/startup_relaunch_audit')/str(time.time_ns())
root=root.resolve()
root.mkdir(parents=True,exist_ok=True)
target,stage=root/'Policy Amadeus.exe',root/'staged.exe'
shutil.copyfile(candidate,target)
shutil.copyfile(candidate,stage)
expected=hashlib.sha256(stage.read_bytes()).hexdigest()
environment=dict(os.environ,LOCALAPPDATA=str(root/'data'),POLICY_AMADEUS_STARTUP_AUDIT='1',PYINSTALLER_RESET_ENVIRONMENT='1')
run=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-WindowStyle','Hidden',
    '-File',str(Path('apply_app_update.ps1').resolve()),'-ParentPid',str(os.getpid()),
    '-Target',str(target),'-Staged',str(stage),'-ExpectedHash',expected,
    '-StatusFile',str(root/'status.json'),'-CandidateVersion',version,'-RestartAfterInstall'],
    env=environment,capture_output=True,timeout=90)
assert run.returncode==0
status=json.loads((root/'status.json').read_text(encoding='utf-8-sig'))
assert status['state']=='installed',status['state']
probe=root/'data/Policy Amadeus/startup_relaunch_probe.json'
deadline=time.monotonic()+60
while not probe.exists() and time.monotonic()<deadline:
    time.sleep(.25)
assert probe.exists(),'Verified installed program did not automatically restart'
result=json.loads(probe.read_text(encoding='utf-8'))
assert result=={'auto_relaunched':True,'app_version':version}
assert hashlib.sha256(target.read_bytes()).hexdigest()==expected
write_json(root/'audit_result.json',{'installed':True,'auto_relaunched':True,'version':version,'sha256':expected})
print(json.dumps({'installed':True,'auto_relaunched':True,'version':version}),flush=True)
