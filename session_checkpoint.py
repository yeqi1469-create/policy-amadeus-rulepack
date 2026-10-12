"""Private local draft recovery across automatic verified app replacement."""
import json
from pathlib import Path
from update_storage import write_json

def save(path,expected_version,config,step,policies,settings):
    record={'schema':1,'expected_version':expected_version,'consumed':False,'config':config,
            'step':min(2,max(0,int(step))),'saved_policy_result':{'policies':policies,'settings':settings}}
    write_json(Path(path),record)
    # Read back before allowing the UI to exit. These private records are
    # NEVER part of the public source/release or legal-review payload.
    if json.loads(Path(path).read_text(encoding='utf-8'))!=json.loads(json.dumps(record)):
        raise RuntimeError('Draft checkpoint verification failed; do not close application')

def restore(path,version):
    from app_updater import version_key
    try:
        record=json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError): return None
    try:
        if record.get('schema')!=1 or record.get('consumed') or version_key(version)<version_key(record.get('expected_version','')):
            return None
    except (ValueError,TypeError,RuntimeError): return None
    if not isinstance(record.get('config'),dict): return None
    if type(record.get('step')) is not int or not 0<=record['step']<=2: return None
    return record

def acknowledge(path):
    record=json.loads(Path(path).read_text(encoding='utf-8'))
    record['consumed']=True
    write_json(Path(path),record)
