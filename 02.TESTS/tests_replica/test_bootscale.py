"""Progress renews the real-work lease without repeating its opening message."""
import pytest
from nodelang import persistence


def test_home_default_fits_bootlimit_and_setting_accepts_full_canvas_budget():
    from nodelang.universal_application import _application_setting_default, _APPLICATION_SETTING_SPECS
    from test_launcher_boot_refusal import _launcher_names
    deadlines = []
    phase = _launcher_names('_boot_phase', _boot_surface=None,
        _start_boot_phase=lambda label, **kwargs: deadlines.append(kwargs['timeout_seconds']))['_boot_phase']
    phase(1)
    assert deadlines == [300.0]
    assert _application_setting_default('home_load_ms') == deadlines[0] * 1000 - 10000
    assert _APPLICATION_SETTING_SPECS['home_load_ms'][1]['max'] == 300000


def test_opening_reports_once_but_keeps_renewing_real_work(monkeypatch, capsys):
    now = [0.0]
    monkeypatch.setattr(persistence.time, 'monotonic', lambda: now[0])
    callbacks = []
    progress = persistence._MigrationProgress(30, callbacks.append)
    for second in range(25):
        now[0] = float(second)
        progress.advance('Opening saved graph')
    assert capsys.readouterr().out.count('Opening saved graph') == 1
    assert len(callbacks) == 25
    now[0] = 55.0
    with pytest.raises(TimeoutError, match='no progress'):
        progress()


def test_quantified_migration_still_reports_progress(monkeypatch, capsys):
    now = [0.0]
    monkeypatch.setattr(persistence.time, 'monotonic', lambda: now[0])
    callbacks = []
    progress = persistence._MigrationProgress(30, callbacks.append)
    for completed in range(4):
        now[0] = float(completed)
        progress.advance('Copying', completed, 3)
    output = capsys.readouterr().out
    assert all(f'{n}/3' in output for n in range(4))
    assert len(callbacks) == 4


@pytest.mark.parametrize('seed_refused', [False, True])
def test_launcher_starts_services_once_after_ready_even_when_optional_seed_refuses(monkeypatch, seed_refused):
    from types import SimpleNamespace
    import traceback
    from nodelang import brain_cloud_runner
    from test_launcher_boot_refusal import _launcher_names
    events = []
    monkeypatch.setattr(brain_cloud_runner, 'start', lambda: events.append('brain'))
    owner = SimpleNamespace(workshop_injection=SimpleNamespace(start=lambda: events.append('workshop')),
        universal_store=object(), universal_registry=object())

    def seed(*args, **kwargs):
        events.append('seed')
        if seed_refused:
            raise RuntimeError('optional seed refused by court')

    view = SimpleNamespace(page=lambda: SimpleNamespace(runJavaScript=lambda script, observed: observed(True)))
    launcher = _launcher_names('_prepare_pipeline', '_prepare_pipeline_after_home',
        server=owner, view=view, first_boot=False, traceback=traceback,
        _pipeline_start={'started': False}, _boot_phase_finish_all=lambda held: events.append('ready'),
        _start_background_refresh=lambda server, target, **kwargs: target(),
        _initialize_startup_pipeline=seed, _settle_canvas_content=lambda server: events.append('settle'))
    launcher['_prepare_pipeline_after_home'](object())
    assert events[:4] == ['ready', 'workshop', 'brain', 'seed']
    assert events.count('settle') == (0 if seed_refused else 1)
    original = list(events)
    launcher['_prepare_pipeline_after_home'](object())
    assert events == original


@pytest.mark.parametrize('refused', ['workshop', 'brain', 'seed'])
def test_deferred_failures_do_not_escape_or_skip_other_starts(monkeypatch, capsys, refused):
    from types import SimpleNamespace
    import traceback
    from nodelang import brain_cloud_runner
    from test_launcher_boot_refusal import _launcher_names
    events = []

    def start(name):
        events.append(name)
        if name == refused:
            raise RuntimeError(name + ' court refusal')

    monkeypatch.setattr(brain_cloud_runner, 'start', lambda: start('brain'))
    owner = SimpleNamespace(workshop_injection=SimpleNamespace(start=lambda: start('workshop')),
        universal_store=object(), universal_registry=object())
    prepare = _launcher_names('_prepare_pipeline', server=owner, first_boot=True, traceback=traceback,
        _initialize_startup_pipeline=lambda *args, **kwargs: start('seed'))['_prepare_pipeline']
    prepare()
    assert events == ['workshop', 'brain', 'seed']
    assert capsys.readouterr().out.count(refused + ' court refusal') == 1


@pytest.mark.parametrize('store,registry', [(None, None), (None, object()), (object(), None)])
def test_deferred_brain_requires_both_store_and_registry(monkeypatch, store, registry):
    from types import SimpleNamespace
    import traceback
    from nodelang import brain_cloud_runner
    from test_launcher_boot_refusal import _launcher_names
    events = []
    monkeypatch.setattr(brain_cloud_runner, 'start', lambda: events.append('brain'))
    owner = SimpleNamespace(workshop_injection=SimpleNamespace(start=lambda: events.append('workshop')),
        universal_store=store, universal_registry=registry)
    prepare = _launcher_names('_prepare_pipeline', server=owner, first_boot=True, traceback=traceback,
        _initialize_startup_pipeline=lambda *args, **kwargs: events.append('seed'))['_prepare_pipeline']
    prepare()
    assert events == ['workshop', 'seed']
