"""The site's BM25 owner, shared with its desktop client; no second corpus or model answer."""
from collections import Counter
import json
import math
from pathlib import Path
import re
from urllib import parse, request as http

from .baboom_persona import IDENTITY, identity_answer, speech

SITE = 'https://baboom.archhub.io'
STANDARD_NODE = {'id': 'baboom.standard', 'params': {'request_seconds': 10}}
_STOP = set('the a an of to and or in on for is are be how what which where do does i we my our it this that with by at as from can use go should must put keep standard std'.split())


def words(text):
    return [w for w in re.findall(r'[\w]+', text.casefold()) if w not in _STOP]


class Index:
    """Fitted from the existing site server: BM25 k1=1.2, b=.75, heading weight=3."""
    def __init__(self, path):
        self.chunks = json.loads(Path(path).read_text(encoding='utf-8'))['chunks']
        self.tf = [Counter(words(c['text']) + words(f"{c['id']} {c['title']} {c['head']}") * 3) for c in self.chunks]
        self.df = Counter(w for f in self.tf for w in f)
        self.n = len(self.chunks)
        self.avg = sum(map(lambda f: sum(f.values()), self.tf)) / max(1, self.n)

    def search(self, question, k=6):
        ids = {f'STD-{int(n):02d}' for n in re.findall(r'(?:std|standard|bbm)[\s-]*(\d{1,2})\b', question, re.I)}
        if ids - {c['id'] for c in self.chunks}:
            return []
        query = words(re.sub(r'(?:std|standard|bbm)[\s-]*(\d{1,2})\b', r' \1 ', question, flags=re.I))
        if not query or not ids and sum(w in self.df for w in set(query)) < max(1, math.ceil(len(set(query)) * .6)):
            return []
        scores = []
        for i, terms in enumerate(self.tf):
            if ids and self.chunks[i]['id'] not in ids:
                continue
            length = sum(terms.values())
            score = sum(math.log(1 + (self.n - self.df[w] + .5) / (self.df[w] + .5)) * terms[w] * 2.2 /
                        (terms[w] + 1.2 * (.25 + .75 * length / max(1, self.avg))) for w in query if w in terms)
            if self.chunks[i]['id'] in ids:
                score += 8
            if score > 0:
                scores.append((score, i))
        scores.sort(reverse=True)
        return [self.chunks[i] for _, i in scores[:k]]


def answer(index, question, token='', page='/'):
    """Extract only indexed wording. Authentication never changes the rule or its citation."""
    identity = identity_answer(question)
    if identity:
        return {'answer': identity, 'links': []}
    hits = [c for c in index.search(question) if c.get('id')]
    if not hits:
        return {'answer': IDENTITY + ' I cannot find that rule in the standard index.', 'links': []}
    best = hits[0]
    citation = 'STD ' + best['id'].removeprefix('STD-')
    budget = 140 - len(citation) - len(IDENTITY) - 5
    candidates = re.split(r'(?<=[.!?])\s+', best['text'])
    candidates.sort(key=lambda t: len(set(words(question)) & set(words(t))), reverse=True)
    excerpt = candidates[0][:budget]
    if len(candidates[0]) > budget:
        excerpt = excerpt.rsplit(' ', 1)[0] + '…'
    return {'answer': speech(f'{IDENTITY} {excerpt} [{citation}]', f'{IDENTITY} See [{citation}].'),
            'links': [{'title': citation, 'href': '/' + parse.quote(best['href']), 'sub': best['head'][:110]}]}


class _NoRedirect(http.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def ask_standard(question):
    """Desktop and future phone clients ask the existing site owner, never a local rule copy."""
    request = http.Request(SITE + '/api/chat',
                                    json.dumps({'question': question, 'page': '/'}).encode(),
                                    {'Content-Type': 'application/json'}, method='POST')
    with http.build_opener(_NoRedirect).open(request, timeout=STANDARD_NODE['params']['request_seconds']) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError('Standard answer exceeds its display budget')
    result = json.loads(raw)
    if not isinstance(result, dict) or not isinstance(result.get('answer'), str) or not isinstance(result.get('links'), list):
        raise ValueError('Standard answer is invalid')
    # Older deployments return sign-in prose rather than a rule; never present it as a grounded answer.
    cited = bool(re.search(r'\[STD[ -][\w-]+\]', result['answer']))
    if not cited and result['answer'] != IDENTITY + ' I cannot find that rule in the standard index.':
        return {'answer': 'The standard answer is unavailable. Open the standard site.', 'links': []}
    return {**result, 'answer': speech(result['answer'])}


def is_standard_question(question):
    return bool(re.match(r'\s*(where|what|how|which|why|when|explain)\b', question, re.I)
                and re.search(r'\b(standard|std[ -]|project folders?|folder structure|naming rule)\b', question, re.I))
