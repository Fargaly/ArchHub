"""Research effects use the existing graph, registry and immutable message identity."""
import json
import hashlib

from .universal_cell import Cell, InvalidCell
from .cell_protocols import prepare_append_relation_members
from .canvas_graph_owner import CanvasOwner
from .universal_pipeline import run_universal_pipeline

# Only pure registered executors: host/provider/terminal ancestors retain their own admission paths.
PURE = frozenset({'research.weighted','text.ops','math.expression','math.series','data.constant','data.list',
    'input.parameter','output.parameter','watch.preview','reroute','note','shape.filter','shape.map',
    'shape.sort','shape.group','shape.unique','shape.pluck','shape.count','shape.slice','shape.flatten',
    'shape.concat','library.filter_field','library.filter_compare','library.filter_rule',
    'library.rule_check','library.set_field','library.group_by','library.sort_by','library.merge'})
ACTIONS = ('runValuation','setResearchReview','runResearchNode','correctAnswerSource')


def encoded(value):
    raw = json.dumps(value,ensure_ascii=False,allow_nan=False)
    if len(raw.encode()) > 65536:
        raise InvalidCell('Research metadata exceeds 64 KiB; existing evidence is unchanged')
    return raw


class ResearchOwner:
    def __init__(self, api):
        self.api = api
        api.admit()
        self.ops = CanvasOwner(api.owner.universal_store,api.owner.universal_registry,api.binding.context)

    def _rows(self, root):
        self.ops._node(self.ops.canvas(),root)
        return {key:row['value'] for key,row in self.ops._rows(None,root).items()}

    def _save(self, root, key, value):
        raw = encoded(value)
        self.api.guard()
        self.ops.set_property(root,key,raw)

    def node(self, root):
        rows = self._rows(root)
        run = json.loads(rows.get('research_run','{}'))
        return {'id':root,'output':run.get('output',[]),'preset':run.get('preset'),
            'review':json.loads(rows.get('research_review','{"items":{}}'))}

    def read(self):
        nodes = {}
        for node in self.ops.canvas()['nodes']:
            rows = self.ops._rows(None,node['id'])
            if 'research_run' in rows or 'research_review' in rows:
                nodes[node['id']] = self.node(node['id'])
        return {'actions':list(ACTIONS),'nodes':nodes}

    def run(self, root, *, valuation=False):
        from .pipeline_engines import PIPELINE_ENGINES
        from .library_engines import engine_runs
        rows = self._rows(root)
        engine = rows.get('engine','')
        if valuation and engine != 'research.weighted':
            raise InvalidCell('Choose a Weighted valuation node wired to actual rows')
        if engine not in PURE or not engine_runs(engine,PIPELINE_ENGINES):
            raise InvalidCell('No registered pure research executor for kind: '+engine)
        canvas = self.ops.canvas()
        roots = self.ops._upstream(canvas,root)
        if any(self._rows(upstream).get(flag) == 'true' for upstream in roots for flag in ('frozen','pinned')):
            raise InvalidCell('Unfreeze and unpin the research workflow before recomputing it')
        if any(self._rows(upstream).get('engine','') not in PURE for upstream in roots):
            raise InvalidCell('Research has an effectful or unknown upstream kind; run through its admitted workflow')
        preset = {key:value for key,value in rows.items() if key not in {
            'status','research_run','research_review','engine','frozen','pinned'}}
        self.api.guard()
        result = run_universal_pipeline(self.ops.store,self.ops.registry,
            effect_engines={key:value for key,value in PIPELINE_ENGINES.items() if key in PURE},
            authentication_context=self.ops.context,only_roots=roots,revalidate=self.api.guard)
        output = result.get('outputs',{}).get(root,{})
        if result.get('pending') or 'out' not in output or output.get('ok') is False:
            raise InvalidCell('Research executor did not produce a successful output: '+str(result.get('display',{})))
        self._save(root,'research_run',{'output':output['out'],'preset':preset,'engine':engine})
        return self.node(root)

    def review(self, root, values):
        if type(values) is not dict or not values or set(values)-{'item','state','selected','usePreset'}:
            raise InvalidCell('Review accepts an item state, selected result or saved preset')
        node = self.node(root)
        review = node['review']
        output = node['output'] if type(node['output']) is list else [node['output']]
        identities = {str(row.get('id',row.get('element',index))) if type(row) is dict else str(index)
                      for index,row in enumerate(output)}
        if 'item' in values or 'state' in values:
            if (set(values) != {'item','state'} or type(values['item']) is not str
                    or values['item'] not in identities or values['state'] not in ('included','excluded','needs-review')):
                raise InvalidCell('Choose an actual result item and included/excluded/needs-review state')
            review['items'][values['item']] = values['state']
        elif 'selected' in values:
            if set(values) != {'selected'} or type(values['selected']) is not str or values['selected'] not in identities:
                raise InvalidCell('Choose an actual result item')
            review['selected'] = values['selected']
        elif set(values) != {'usePreset'} or values['usePreset'] is not True or not node['preset']:
            raise InvalidCell('Run this node successfully before recalling its preset')
        else:
            self.api.guard()
            for key,value in node['preset'].items():
                self.ops.set_property(root,key,value)
            review['lastPreset'] = node['preset']
        self._save(root,'research_review',review)
        return self.node(root)

    def _citation_root(self, message):
        return self.api.root + ':answer-sources:' + hashlib.sha256(message.encode()).hexdigest()

    def sources(self, message, evidence, works):
        from .workshop_mailbox import ROUTING_EVIDENCE
        if evidence and evidence[0] == ROUTING_EVIDENCE:
            evidence = ()
        cell = self.api.admit().cells.get(self._citation_root(message))
        if cell:
            if cell.link0 not in works or cell.link1 != self.api.binding.subject_root:
                raise InvalidCell('Citation attachment belongs to another Work or account')
            return json.loads(cell.atom)
        return {'sources':[{'sourceId':source,'excerpt':'','status':'Included'} for source in evidence],
                'sourceRevisions':[]}

    def correct(self, message, index, values):
        if type(message) is not str or type(index) is not int or index < 0:
            raise InvalidCell('Choose an existing message source')
        if (type(values) is not dict or not values or set(values)-{'excerpt','status'}
                or ('excerpt' in values and (type(values['excerpt']) is not str or len(values['excerpt']) > 32000))
                or ('status' in values and values['status'] not in ('Included','Excluded','Corrected'))):
            raise InvalidCell('A source correction accepts bounded excerpt text and Included/Excluded/Corrected status')
        matches = {}
        parent = None
        for work in self.api._works():
            messages = self.api._messages(work['root'])[0]
            for row in messages:
                if row['id'] == message:
                    matches[row['id']] = row
                    parent = work['root']
        if message not in matches or index >= len(matches[message]['sources']):
            raise InvalidCell('Message or source is outside this Workshop')
        current = matches[message]
        sources = current['sources']
        revisions = current['sourceRevisions'] or [{'revision':0,'sources':json.loads(encoded(sources))}]
        sources[index] = {**sources[index],**values}
        revisions.append({'revision':len(revisions),'sources':json.loads(encoded(sources))})
        record = {'sources':sources,'sourceRevisions':revisions}
        raw = encoded(record).encode()
        root = self._citation_root(message)
        from . import universal_application as app
        snapshot = self.api.admit()
        cell = Cell(root,parent,self.api.binding.subject_root,raw)
        exists = root in snapshot.cells
        patch = prepare_append_relation_members(snapshot,parent,
            () if exists else ((self.ops.registry.roles['member'],root),))
        view, context = app._view_session_for_context(self.ops.registry,self.ops.context)
        self.api.guard()
        app._commit_universal_user_change(self.ops.store,self.ops.registry,view,context,snapshot,
            route=self.api.route,command_name='catalog.configure',authorization_scope_root=self.api.root,
            create=(*patch.create,*((cell,) if not exists else ())),
            replace=(*patch.replace,*((cell,) if exists else ())))
        return {'id':message,**record}
