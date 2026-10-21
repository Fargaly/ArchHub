"""Sequential PRESENCE1 round2 courts; invoke only inside run-heavy."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '05.EVIDENCE/presence1'


def main():
    os.chdir(ROOT)
    os.environ.update(CARGO_HOME=r'C:\Users\fargaly\AppData\Local\rs\cargo',
        RUSTUP_HOME=r'C:\Users\fargaly\AppData\Local\rs\rustup',
        PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1', QT_QPA_PLATFORM='offscreen')
    cache = ROOT / 'node_modules/.cache'
    cache.mkdir(parents=True, exist_ok=True)
    run_state = Path(tempfile.mkdtemp(prefix='presence1-courts-', dir=cache))
    for key in ('APPDATA','LOCALAPPDATA','TEMP','TMP'):
        folder = run_state / key
        folder.mkdir()
        os.environ[key] = str(folder)
    python = sys.executable
    files = ['test_presence1.py','test_presence1_acceptance.py','test_baboom_native_companion.py',
        'test_baboom_user_controls.py','test_baboom_startup_setting.py','test_baboom_native_runtime.py',
        'test_baboom5.py','test_baboom_confirm_names_what_it_does.py','test_baboom_is_an_agent.py',
        'test_baboom_atlas_is_inspected_off_the_gui_thread.py','test_site_export.py','test_website_docs_pages.py']
    courts = [
        ('native-final', [python,'02.TESTS/tests_replica/presence1_native_probe.py']),
        ('studio-build', [os.environ['COMSPEC'],'/d','/c','npm run build:studio']),
        ('studio-courts', ['node','--test','--test-concurrency=1','--test-force-exit',
            '02.TESTS/tests_replica/test_studio_baboom_startup.cjs']),
        ('focused-green', [python,'-m','pytest','-q','-p','no:cacheprovider',
            '--basetemp='+str(run_state/'focused'),
            *['02.TESTS/tests_replica/'+name for name in files],'--tb=short']),
        ('zero-idle', [python,'-m','pytest','-q','-p','no:cacheprovider',
            '--basetemp='+str(run_state/'zero-idle'),
            '02.TESTS/tests/test_zero_idle_growth.py','--tb=short']),
        ('whole-ratchet', [python,'03.TOOLS/tools/ratchet.py','compare','.','05.EVIDENCE/ratchet.json',
            '--whole-tree','--context','05.EVIDENCE/presence1/intent-context.json']),
        ('strict-final', [python,'03.TOOLS/tools/pipeline/strict_check.py','--changed',
            '--context','05.EVIDENCE/presence1/intent-context.json']),
    ]
    results = []
    for name, command in courts:
        with (OUT/('r2-'+name+'.txt')).open('wb') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
        results.append({'name':name,'exit':result.returncode})
        (OUT/'r2-final-exits.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
        print(name+' exit='+str(result.returncode),flush=True)
    return int(any(item['exit'] for item in results))


if __name__ == '__main__':
    sys.exit(main())
