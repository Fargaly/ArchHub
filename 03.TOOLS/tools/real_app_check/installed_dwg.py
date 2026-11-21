"""Windows guest QA. Run with the selected installation's .venv/Scripts/python.exe -I -B."""
import hashlib
import os
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from urllib.request import urlopen

install = Path(sys.executable).resolve().parents[2]
assert sys.flags.isolated and sys.dont_write_bytecode
sys.path.insert(0, str(install))
sample = 'https://raw.githubusercontent.com/DomCR/ACadSharp/6ef32981983904695060e055c66acbe5a6220b89/samples/'
drawings = {'2013': ('sample_AC1027.dwg', '4c63508dd794d5cdfb56c60aded47928999b02619ea8c2ef435a4b74e60d24d6'),
            '2018': ('sample_AC1032.dwg', '0e8faaca949c9429c92240082d9ea4d3524aca5baf7c7815ec439245c321b528')}
image_hash = '55e9a686d51f82692ca6bbfb2be367f899fa0f16d3c408e80d7930ddae72d4ff'

deadline = time.monotonic() + timedelta(minutes=int(os.environ['VERIFY_MINUTES'])).total_seconds()

def fixture(name, digest):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('The Windows verification budget expired before the fixture download.')
    with urlopen(sample + name, timeout=remaining) as response:
        data = response.read(2_000_000)
    assert hashlib.sha256(data).hexdigest() == digest, name
    return data

with tempfile.TemporaryDirectory(prefix='archhub-installed-dwg-') as temp:
    root = Path(temp).resolve()
    os.environ['ARCHHUB_TEST_STATE_DIR'] = str(root/'state')
    import ezdwg
    from nodelang import clean_revit_adapter as adapter, session_files, settings_owner
    from nodelang.nodeslib_v2_engines import dwg_export_request
    from nodelang.nograph_server import JsonFile
    for module in (ezdwg, adapter, session_files, settings_owner):
        assert Path(module.__file__).resolve().is_relative_to(install), module.__file__
    assert (install/'runtime/acompiler/archhub-compiler.exe').is_file()
    JsonFile(root/'state/settings/workspaces.json', {}).write({'roots':[{'root_id':'dwg-qa','name':'QA','path':str(root),'privacy':'private'}]})
    model = root/'Disposable.rvt'
    model.touch()  # Only the registered input path is checked. A host is never invoked.
    node = next(n for n in session_files.catalogue() if n['id']=='file_export_dwg')
    assert next(p['type'] for p in node['paramDefs'] if p['id']=='path')=='text'
    doc = session_files.new_document('DWG QA')
    settings_owner.preference_settings('setAppearance', ['Projects.DWG export setup','Office DWG export'])
    raster = fixture('image.JPG', image_hash)
    for version, (name, digest) in drawings.items():
        settings_owner.preference_settings('setAppearance', ['Projects.DWG version',version])
        stage, out = root/('stage-'+version), root/('issued-'+version)
        stage.mkdir()
        req = dwg_export_request({**node['params'],'project_id':'dwg-qa','session':'48884','document':str(model),
                                  'path':str(out),'views':['41','52']}, {}, doc)
        assert (req['version'],req['setup'],req['views']) == (version,'Office DWG export',[41,52])
        (stage/name).write_bytes(fixture(name,digest))
        try:
            adapter._dwg_manifest(stage,[name],version)
        except adapter.RevitUnreachable as refused:
            assert 'missing' in str(refused), str(refused)
        else:
            raise AssertionError('Missing referenced JPEG accepted')
        (stage/'image.JPG').write_bytes(raster)
        files = {name:digest,'image.JPG':image_hash}
        assert adapter._dwg_manifest(stage,list(files),version) == files
        stage.rename(out)
        assert adapter._dwg_manifest(out,list(files),version) == files
        ref, = adapter._dwg_references(ezdwg.raw,out/name)
        assert hashlib.sha256((out/ref).read_bytes()).hexdigest() == image_hash
        print('PASS installed reader, Projects settings, typed IDs and linked JPEG',version)
    print('BUILD', (install/'BUILD_ID').read_text().strip(), '| protected UI needs authenticated app | no live Revit invoked')
