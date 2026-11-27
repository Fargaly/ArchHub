"""Before/after compare: what worked on the installed build must still work on the candidate."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('crawl_compare', ROOT / '03.TOOLS/tools/real_app_check/crawl_compare.py')
crawl_compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crawl_compare)


def crawl(*blocks):
    return {'all': [{'surface': s, 'size': '1920x1032', 'rows': rows, **extra} for s, rows, extra in blocks]}


def row(name, cls, **more):
    return {'name': name, 'design': '', 'nth': 0, 'cls': cls, **more}


def test_a_control_that_worked_and_now_is_dead_or_gone_fails_the_candidate():
    installed = crawl(('Settings:This PC', [row('Show all', 'opened-dialog-or-menu'), row('Check all', 'did-its-action'), row('Retry', 'DEAD')], {}))
    candidate = crawl(('Settings:This PC', [row('Show all', 'DEAD')], {}))
    result = crawl_compare.compare(installed, candidate)
    assert not result['pass']
    assert {(r['key'].split('|')[2], r['now']) for r in result['regressions']} == {('Show all', 'DEAD'), ('Check all', 'gone')}


def test_same_behaviour_with_changed_counts_passes_and_a_fix_is_reported():
    installed = crawl(('Home', [row('3 need you', 'opened-a-design-place'), row('Open', 'DEAD')], {}))
    candidate = crawl(('Home', [row('4 need you', 'opened-a-design-place'), row('Open', 'did-its-action')], {}))
    result = crawl_compare.compare(installed, candidate)
    assert result['pass'] and len(result['fixed']) == 1


def test_a_removal_on_purpose_is_reported_not_failed_and_a_lost_surface_fails():
    installed = crawl(('Settings:This PC', [row('Updates & About', 'opened-dialog-or-menu')], {}), ('Workspaces', [row('Open', 'did-its-action')], {}))
    candidate = crawl(('Settings:This PC', [], {}), ('Workspaces', [], {'opened': False}))
    key = 'Settings:This PC|1920x1032|Updates & About||0'
    result = crawl_compare.compare(installed, candidate, {key: 'design: no inline page in The app'})
    assert [r['key'] for r in result['removed_on_purpose']] == [key]
    assert [r['now'] for r in result['regressions']] == ['does not open']


def test_the_command_line_exits_nonzero_on_a_regression(tmp_path, capsys):
    (tmp_path / 'a.json').write_text(json.dumps(crawl(('Canvas', [row('Run', 'did-its-action(stubbed-effect)')], {}))), encoding='utf-8')
    (tmp_path / 'b.json').write_text(json.dumps(crawl(('Canvas', [row('Run', 'error')], {}))), encoding='utf-8')
    assert crawl_compare.main([str(tmp_path / 'a.json'), str(tmp_path / 'b.json'), '--out', str(tmp_path / 'r.json')]) == 1
    assert 'REGRESSION Canvas|1920x1032|Run||0: was did-its-action(stubbed-effect), now error' in capsys.readouterr().out
    assert json.loads((tmp_path / 'r.json').read_text(encoding='utf-8'))['pass'] is False
