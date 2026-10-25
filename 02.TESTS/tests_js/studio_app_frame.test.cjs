const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const studio=path.resolve(__dirname,'../../01.APP/nodelang/studio');
const read=name=>fs.readFileSync(path.join(studio,name),'utf8');
const sources=()=>JSON.parse(read('compiled/manifest.json')).files.map(file=>read(file.source)).join('\n');

test('DSYS-060 plate sample data does not ship in the changed Studio JSX', () => {
  for (const sample of [
    'Revit 2025',
    'Nile_Tower',
    'Omar',
    'sara@firm.com',
    'Clinic',
    '46 doors',
    'L3-D001',
    '09:14',
    'run #48',
  ]) {
    assert.equal(sources().includes(sample), false, 'Studio still contains plate sample ' + JSON.stringify(sample));
  }
});
