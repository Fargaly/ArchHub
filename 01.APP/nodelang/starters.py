"""The nine built-in starters (Book ch.12 "Your daily work, one click"), each a real .archhub workflow.

Every step is a node the canvas already has. A step no host node does yet is an agent node whose
instructions say the step, so a connected agent does it through its own tools; nothing fakes output.
Every chain ends at an Approval gate: Start runs until that Approve point.
"""
from __future__ import annotations

import copy

# (item id in the session catalogue, title shown on the canvas, params)
def _agent(title, instructions):
    return ('thing:agent:claude', title, {'instructions': instructions})


STARTERS = [
    {'id': 'starter:submittal', 'title': 'Submittal turnaround', 'programs': ['revit', 'pdf'],
     'stops_at': 'Stops at one Approve card with every sheet before/after',
     'steps': [('n_file', 'Markup PDF', {'extensions': '.pdf'}),
               ('pdf_extract_text', 'Read markups', {}),
               _agent('Clouds', 'Place and tighten revision clouds for every marked change in the open Revit model.'),
               _agent('Titleblock', 'Update the title block and the revision row on every changed sheet; check signatures.'),
               ('o_pdf_handoff', 'Print', {}),
               _agent('Package', 'Print PDF and DWG in drawing-list order and file the submittal package.'),
               ('g_approval_gate', 'QC · your Approve', {'operation': 'submittal'})]},
    {'id': 'starter:redline-qc', 'title': 'Redline QC with proof table', 'programs': ['revit', 'pdf'],
     'stops_at': 'Stops at accept/reject per row; rejected rows go back to Submittal turnaround',
     'steps': [('n_file', 'Sheets PDF', {'extensions': '.pdf'}),
               ('pdf_extract_text', 'Compare', {}),
               ('pdf_snip', 'Comments · image proof', {}),
               ('f_write_table', 'Proof table', {'format': 'xlsx'}),
               ('g_approval_gate', 'Accept / reject per row', {'operation': 'redline-qc'})]},
    {'id': 'starter:sheets', 'title': 'Sheets production', 'programs': ['revit'],
     'stops_at': 'Stops at a strip of every new sheet',
     'steps': [('thing:host:revit', 'Views', {}),
               ('b_create_sheets', 'Sheets', {}),
               ('d_place_sheet', 'Place and centre', {}),
               ('b_renumber', 'Number and order', {}),
               ('g_approval_gate', 'Strip of new sheets', {'operation': 'sheets'})]},
    {'id': 'starter:cad-detail', 'title': 'CAD detail into the model', 'programs': ['acad', 'revit'],
     'stops_at': 'Stops at your marks on the view if something is off',
     'steps': [('thing:host:acad', 'CAD file', {}),
               _agent('Detail', 'Find the requested detail in the open AutoCAD drawing.'),
               _agent('Place', 'Bring only that detail into the Revit model view.'),
               _agent('Align', 'Align the detail to the level.'),
               _agent('Fix dims', 'Fix leaders, dimensions, hatches and the break line.'),
               ('g_approval_gate', 'Your marks on the view', {'operation': 'cad-detail'})]},
    {'id': 'starter:email-triage', 'title': 'Email triage in house format', 'programs': ['outlook'],
     'stops_at': 'Stops before anything is sent: nothing leaves until you Approve',
     'steps': [('outlook_search', 'Inbox and sent', {}),
               ('s_group', 'Sort by project', {}),
               ('outlook_reply_draft', 'Draft reply · your signature', {}),
               ('g_approval_gate', 'Your OK', {'operation': 'email-triage'})]},
    {'id': 'starter:research-notion', 'title': 'Research to Notion', 'programs': ['notion'],
     'stops_at': 'Stops at one Approve for the page and its plan row',
     'steps': [('n_list', 'Links', {}),
               _agent('Read', 'Read every dropped link in Chrome and judge what is useful.'),
               ('ai_master', 'Findings', {}),
               _agent('Notion page', 'Write one page in the Notion system and fold it into the plan.'),
               ('g_approval_gate', 'Approve page and plan row', {'operation': 'research-notion'})]},
    {'id': 'starter:text-standard', 'title': 'One title block and text standard', 'programs': ['revit', 'acad'],
     'stops_at': 'Stops at the diff first; text is never shrunk silently',
     'steps': [('thing:host:revit', 'Text styles', {}),
               _agent('Propose a standard', 'List every text style and size in Revit and AutoCAD and propose one standard.'),
               ('g_dryrun_diff', 'Diff', {}),
               ('g_approval_gate', 'Approve the standard', {'operation': 'text-standard'})]},
    {'id': 'starter:print-defects', 'title': 'Printed-set defect sweep', 'programs': ['revit', 'pdf'],
     'stops_at': 'Stops at approving the new print',
     'steps': [('n_file', 'Printed set', {'extensions': '.pdf'}),
               ('pdf_extract_text', 'Find defects', {}),
               _agent('Fix at the source', 'Fix stray viewport lines, wrong colours and empty fields in the model, then reprint.'),
               ('g_approval_gate', 'Approve the new print', {'operation': 'print-defects'})]},
    {'id': 'starter:workspace-cleanup', 'title': 'Workspace cleanup', 'programs': [],
     'stops_at': 'Stops before anything leaves WIP: only you move it out',
     'steps': [('thing:file', 'Folder', {}),
               _agent('File loose items', 'File loose items into the right folders, rebuild the register, archive old items; never delete.'),
               ('g_approval_gate', 'Your move out of WIP', {'operation': 'workspace-cleanup'})]},
]

PROGRAM_NAMES = {'revit': 'Revit', 'acad': 'AutoCAD', 'outlook': 'Outlook', 'notion': 'Notion'}


def missing_programs(starter, host_rows):
    """Programs a starter needs that this PC has not got (pdf and files need nothing installed)."""
    present = {str(row.get('id', '')).split('-')[0] for row in host_rows or () if row.get('state') not in ('absent', 'off')}
    return [PROGRAM_NAMES[p] for p in starter['programs'] if p in PROGRAM_NAMES and p not in present]


def listing(host_rows):
    """Home cards: name, chain, Stops-at line, Needs chips. Book order; no counters before real runs."""
    return [{'id': s['id'], 'title': s['title'], 'stops_at': s['stops_at'], 'needs': missing_programs(s, host_rows),
             'children': [{'title': title} for _item, title, _params in s['steps']], 'run_count': None}
            for s in STARTERS]


def document(starter_id):
    """The starter as a fresh .archhub document: its nodes in a row, each wired to the next."""
    from .session_files import catalogue, new_document, validate
    starter = next((s for s in STARTERS if s['id'] == starter_id), None)
    if starter is None:
        raise ValueError('No built-in starter %r' % starter_id)
    items = {row['id']: row for row in catalogue()}
    doc = new_document(starter['title'])
    previous = None
    for index, (item_id, title, params) in enumerate(starter['steps']):
        item = items[item_id]
        node = {'id': 'n%d' % (index + 1), 'item': item_id, 'type': item['engine'], 'title': title,
                'params': {**copy.deepcopy(item.get('params') or {}), **params}, 'position': {'x': 40 + index * 260, 'y': 120}}
        doc['nodes'].append(node)
        if previous is not None:
            out = (previous[1].get('ports') or {}).get('source') or []
            into = (item.get('ports') or {}).get('target') or []
            target = next((p for p in into if p['id'] in ('in', 'task', 'prompt', 'value')), into[0] if into else None)
            if out and target:
                doc['wires'].append({'id': 'w%d' % index, 'from': {'node': previous[0]['id'], 'socket': out[0]['id']},
                                     'to': {'node': node['id'], 'socket': target['id']}})
        previous = (node, item)
    doc['notes'] = [{'text': starter['stops_at']}]
    return validate(doc)
