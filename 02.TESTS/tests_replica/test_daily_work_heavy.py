"""Daily-work heavy nodes on the real pinned runtimes and public samples.

Run through the heavy queue with DAILY_RUNTIMES (a folder the pinned runtimes
were fetched into by daily_work_nodes.ensure_runtime) and DAILY_SAMPLES (a
folder holding arabic_0.jpg from PaddleOCR's docs and jfk.wav from whisper.cpp's
samples). The IFC model and the IDS file are generated here.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

RUNTIMES, SAMPLES = os.environ.get('DAILY_RUNTIMES', ''), os.environ.get('DAILY_SAMPLES', '')
pytestmark = pytest.mark.skipif(not (RUNTIMES and SAMPLES), reason='needs DAILY_RUNTIMES and DAILY_SAMPLES (heavy queue)')

MODEL = r'''
import sys, numpy as np
sys.path.insert(0, sys.argv[2])
import ifcopenshell, ifcopenshell.api.project as project, ifcopenshell.api.root as root, ifcopenshell.api.unit as unit
import ifcopenshell.api.context as context, ifcopenshell.api.aggregate as aggregate, ifcopenshell.api.spatial as spatial
import ifcopenshell.api.geometry as geometry, ifcopenshell.api.pset as pset
f = project.create_file(version="IFC4")
proj = root.create_entity(f, ifc_class="IfcProject", name="Public sample")
unit.assign_unit(f, units=[unit.add_si_unit(f, unit_type="LENGTHUNIT"), unit.add_si_unit(f, unit_type="AREAUNIT")])
model = context.add_context(f, context_type="Model")
body = context.add_context(f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model)
site = root.create_entity(f, ifc_class="IfcSite", name="Site")
building = root.create_entity(f, ifc_class="IfcBuilding", name="Building")
aggregate.assign_object(f, relating_object=proj, products=[site])
aggregate.assign_object(f, relating_object=site, products=[building])
levels = {}
for name, z in (("L1", 0.0), ("L2", 3.0)):
    levels[name] = root.create_entity(f, ifc_class="IfcBuildingStorey", name=name)
    aggregate.assign_object(f, relating_object=building, products=[levels[name]])
def box(cls, name, x, y, length, thickness, rating=None):
    element = root.create_entity(f, ifc_class=cls, name=name)
    rep = geometry.add_wall_representation(f, context=body, length=length, height=3.0, thickness=thickness)
    geometry.assign_representation(f, product=element, representation=rep)
    matrix = np.eye(4); matrix[0][3] = x; matrix[1][3] = y
    geometry.edit_object_placement(f, product=element, matrix=matrix)
    spatial.assign_container(f, relating_structure=levels["L1"], products=[element])
    if rating:
        pset.edit_pset(f, pset=pset.add_pset(f, product=element, name="Pset_WallCommon"), properties={"FireRating": rating})
    return element
box("IfcWall", "W1", 0, 0, 5.0, 0.2, rating="60")
box("IfcWall", "W2", 0, 4, 5.0, 0.2)
box("IfcColumn", "C1", 2.0, -0.1, 0.4, 0.4)   # stands inside W1: one hard clash
box("IfcColumn", "C2", 10.0, 10.0, 0.4, 0.4)  # free standing
for level, number, name, area in (("L1", "101", "Office", 20.5), ("L1", "102", "Meeting", 14.25), ("L2", "201", "Office", 31.0)):
    space = root.create_entity(f, ifc_class="IfcSpace", name=number)
    space.LongName = name
    aggregate.assign_object(f, relating_object=levels[level], products=[space])
    pset.edit_qto(f, qto=pset.add_qto(f, product=space, name="Qto_SpaceBaseQuantities"), properties={"NetFloorArea": area})
f.write(sys.argv[1])
'''

IDS = '''<?xml version="1.0" encoding="UTF-8"?>
<ids xmlns="http://standards.buildingsmart.org/IDS" xmlns:xs="http://www.w3.org/2001/XMLSchema"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xsi:schemaLocation="http://standards.buildingsmart.org/IDS http://standards.buildingsmart.org/IDS/1.0/ids.xsd">
  <info><title>Walls carry a fire rating</title></info>
  <specifications>
    <specification name="Wall fire rating" ifcVersion="IFC4">
      <applicability minOccurs="0" maxOccurs="unbounded">
        <entity><name><simpleValue>IFCWALL</simpleValue></name></entity>
      </applicability>
      <requirements>
        <property dataType="IFCLABEL" cardinality="required">
          <propertySet><simpleValue>Pset_WallCommon</simpleValue></propertySet>
          <baseName><simpleValue>FireRating</simpleValue></baseName>
        </property>
      </requirements>
    </specification>
  </specifications>
</ids>
'''


@pytest.fixture
def daily(tmp_path, monkeypatch):
    for name in ('APPDATA', 'USERPROFILE', 'HOME', 'LOCALAPPDATA'):
        monkeypatch.setenv(name, str(tmp_path / name))
        (tmp_path / name).mkdir()
    from nodelang import daily_work_nodes
    monkeypatch.setattr(daily_work_nodes, 'runtimes_root', lambda: Path(RUNTIMES))
    return daily_work_nodes


@pytest.fixture
def ifc_sample(daily, tmp_path):
    site = daily.ensure_runtime('ifc') / 'site'
    model = tmp_path / 'sample.ifc'
    done = subprocess.run([sys.executable, '-I', '-c', MODEL, str(model), str(site)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-2000:]
    ids = tmp_path / 'walls.ids'
    ids.write_text(IDS, encoding='utf-8')
    return model, ids


def test_clash_and_ids_check_write_a_bcf_with_one_topic_per_issue(daily, ifc_sample, tmp_path):
    import zipfile
    model, ids = ifc_sample
    target = tmp_path / 'issues.bcf'
    out, shown = daily.ifc_check_bcf({'bcf_path': str(target), 'clash_a': 'IfcWall', 'clash_b': 'IfcColumn'},
                                     {'ifc': str(model), 'ids': str(ids)})
    assert [(c['a_name'], c['b_name']) for c in out['clashes']] == [('W1', 'C1')]
    assert [(f['type'], f['name']) for f in out['ids_failures']] == [('IfcWall', 'W2')]
    with zipfile.ZipFile(target) as bcf:
        markups = [n for n in bcf.namelist() if n.endswith('markup.bcf')]
        titles = sorted(bcf.read(n).decode('utf-8').split('<Title>')[1].split('</Title>')[0] for n in markups)
    assert len(markups) == 2 and titles[0].startswith('Clash: IfcWall W1 / IfcColumn C1') and titles[1].startswith('IDS: IfcWall W2')
    assert shown == '1 clash(es), 1 IDS failure(s), 2 BCF topic(s) -> issues.bcf'


def test_area_schedule_reads_ifc_space_quantities_by_storey(daily, ifc_sample):
    model, _ids = ifc_sample
    out, shown = daily.area_schedule({'group_by': 'level'}, {'ifc': str(model)})
    assert shown == '3 space(s), 65.75 m2 total over 2 level group(s)'
    assert out['totals'] == {'L1': 34.75, 'L2': 31.0} and out['total'] == 65.75
    assert [(r['number'], r['name'], r['source']) for r in out['schedule']] == [
        ('101', 'Office', 'quantity'), ('102', 'Meeting', 'quantity'), ('201', 'Office', 'quantity')]


def test_arabic_ocr_reads_a_public_arabic_sign(daily):
    out, shown = daily.arabic_ocr({'lang': 'arabic'}, {'image': str(Path(SAMPLES) / 'arabic_0.jpg')})
    assert shown.endswith('line(s) read from arabic_0.jpg')
    assert 'حلويات' in out['text'], out['lines']
    assert all(0.5 <= line['score'] <= 1 for line in out['lines'])


def test_meeting_minutes_transcribe_a_public_domain_speech(daily):
    out, shown = daily.meeting_minutes({'model': 'base-q5_1', 'language': 'en', 'title': 'JFK'},
                                       {'audio': str(Path(SAMPLES) / 'jfk.wav')})
    assert shown.endswith('of audio') and shown.startswith('%d segment(s)' % len(out['segments']))
    words = out['transcript'].lower()
    assert 'ask not what your country can do for you' in words, words
    assert out['minutes'].startswith('# Minutes: JFK') and '- [00:00:00]' in out['minutes']
    assert 10.0 <= out['segments'][-1]['end'] <= 11.5
