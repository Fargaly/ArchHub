"""Real host boundary and inert dry-run for the GitHub rehearsal harness."""
import hashlib
import json
import os
import subprocess

from tests_replica.test_mainrel_rollback import PWSH, SCRIPT

PREP = SCRIPT.with_name('rollback-rehearsal-ci') / 'prepare-rehearsal.ps1'

def prepare_args(tmp_path):
    files = []
    for name in ('0400.exe','main.exe','python.exe'):
        path = tmp_path / name
        path.write_bytes(('not executable: '+name).encode())
        files.append(path)
    def notes(path,build):
        return 'BUILD_ID: '+build+'\nSHA256 ArchHub-Setup-0.exe: '+hashlib.sha256(path.read_bytes()).hexdigest()+'\n'
    return [PWSH,'-NoProfile','-File',str(PREP),'-DryRun','-WorkRoot',str(tmp_path / 'plan'),
        '-BaseInstaller',str(files[0]),'-CandidateInstaller',str(files[1]),
        '-BaseNotes',notes(files[0],'20261018-0400-fd62cb8'),
        '-CandidateNotes',notes(files[1],'main-fixture'),'-PythonInstaller',str(files[2])]


def test_ci_dry_run_verifies_hashes_and_never_publishes_acceptance(tmp_path):
    args=prepare_args(tmp_path)
    run=subprocess.run(args,capture_output=True,text=True,check=False)
    assert run.returncode==0,run.stdout+run.stderr
    plan=json.loads((tmp_path/'plan/MainrelInput/plan.json').read_text(encoding='utf-8-sig'))
    assert plan['mode']=='DRY-RUN'
    assert plan['fixture_requested_bytes']==8937168896
    assert plan['step_deadline']==1800
    assert plan['main_build_id']=='main-fixture'
    assert not (tmp_path/'plan/MainrelResults/result.json').exists()
    assert 'no downloads, installers or workflow started' in run.stdout


def test_ci_wrong_release_hash_refuses_before_plan(tmp_path):
    args=prepare_args(tmp_path)
    args[args.index('-CandidateNotes')+1]='BUILD_ID: main-fixture\nSHA256 ArchHub-Setup-0.exe: '+'0'*64+'\n'
    run=subprocess.run(args,capture_output=True,text=True,check=False)
    assert run.returncode!=0
    assert 'differs from its release notes' in run.stderr
    assert not (tmp_path/'plan/MainrelInput/plan.json').exists()


def test_ci_existing_plan_is_not_overwritten(tmp_path):
    args=prepare_args(tmp_path)
    first=subprocess.run(args,capture_output=True,text=True,check=False)
    assert first.returncode==0,first.stderr
    path=tmp_path/'plan/MainrelInput/plan.json'
    original=path.read_bytes()
    second=subprocess.run(args,capture_output=True,text=True,check=False)
    assert second.returncode!=0
    assert path.read_bytes()==original


def test_ci_host_cannot_become_runneradmin_by_environment_spoofing(tmp_path):
    env=dict(os.environ,GITHUB_ACTIONS='true',RUNNER_OS='Windows',RUNNER_ENVIRONMENT='github-hosted',
             GITHUB_REPOSITORY='Fargaly/archhub-rehearsal',GITHUB_RUN_ID='123',
             USERNAME='runneradmin',USERPROFILE='C:\\Users\\runneradmin')
    run=subprocess.run([PWSH,'-NoProfile','-File',str(SCRIPT),'-Guest','-PlanPath','C:\\MainrelInput\\plan.json'],
                       capture_output=True,text=True,check=False,env=env)
    assert run.returncode!=0
    assert 'requires the Windows Sandbox account and mapped plan' in run.stderr
    run=subprocess.run([PWSH,'-NoProfile','-File',str(PREP),'-BaseTag','base','-CandidateTag','main',
                        '-WorkRoot',str(tmp_path/'refused')],capture_output=True,text=True,check=False,env=env)
    assert run.returncode!=0
    assert 'Only the approved GitHub-hosted' in run.stderr
    assert not (tmp_path/'refused').exists()


def test_ci_workflow_permissions_dispatch_and_failure_artifacts():
    workflow=SCRIPT.with_name('rollback-rehearsal-ci')/'.github/workflows/rollback-rehearsal.yml'
    # JSON is a YAML subset accepted by Actions, without a new parser dependency.
    data=json.loads(workflow.read_text(encoding='utf-8-sig'))
    assert set(data['on'])=={'workflow_dispatch'}
    assert set(data['on']['workflow_dispatch']['inputs'])=={'base_tag','candidate_tag'}
    assert data['permissions']=={'contents':'read'}
    job=data['jobs']['rehearse']
    assert job['runs-on']=='windows-latest' and job['timeout-minutes']==360
    upload=job['steps'][-1]
    assert upload['if']=='always()'
    assert upload['with']['if-no-files-found']=='error'
    assert upload['with']['retention-days']==7
    assert job['steps'][1]['with']['persist-credentials'] is False
