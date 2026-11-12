"""Outlook reply drafts carry exactly one house skeleton (Dear, / Thank you and best regards).

Fixtures follow the founder-hit shape (2026-11-06, 2026-11-12): a Word-saved
windows-1252 signature whose close is split across CRLF and whose pictures
appear twice (VML imagedata plus the plain <img>), and an Outlook ReplyAll
body that already holds Outlook's own reply signature above the From: header.
No real Outlook, mailbox or signature folder is touched.
"""
from __future__ import annotations

import re

import pytest

from nodelang import library_engines as L

_NAME = 'House'


def _signature(tmp_path, *, split_close: bool, vml: bool):
    folder = tmp_path / 'Signatures'
    images = folder / (_NAME + '_files')
    images.mkdir(parents=True)
    pictures = ''
    for n in (1, 2):
        (images / ('image00%d.png' % n)).write_bytes(b'\x89PNG\r\n\x1a\n')
        src = '%s_files/image00%d.png' % (_NAME, n)
        if vml:
            pictures += ('<!--[if gte vml 1]><v:shape style=\'width:90pt\'><v:imagedata src="%s" '
                         'o:title=""/></v:shape><![endif]--><![if !vml]><img width=120 src="%s" '
                         'v:shapes="Picture_%d"><![endif]>' % (src, src, n))
        else:
            pictures += '<img width=120 src="%s">' % src
    close = 'Thank you\r\nand best regards,' if split_close else 'Thank you and best regards,'
    html = ('<html><head><meta http-equiv=Content-Type content="text/html; charset=windows-1252">'
            '<style>p.MsoNormal{margin:0in}</style></head><body lang=EN-US><div class=WordSection1>'
            '<p class=MsoNormal><span style=\'font-family:"Calibri",sans-serif\'>Dear,</span>'
            '<b><span style=\'color:#1F497D\'><o:p></o:p></span></b></p>'
            '<p class=MsoNormal><span style=\'font-family:"Calibri",sans-serif;mso-ligatures:none\'>'
            + close + '<o:p></o:p></span></p><p class=MsoNormal>Caf\xe9 Studio ' + pictures
            + '</p></div></body></html>')
    (folder / (_NAME + '.htm')).write_bytes(html.encode('windows-1252'))
    return folder, html


class _Attachment:
    def __init__(self, path):
        self.path = path
        self.PropertyAccessor = self

    def SetProperty(self, name, value):
        self.cid = value


class _Attachments(list):
    def Add(self, path):
        self.append(_Attachment(path))
        return self[-1]


class _Mail:
    def __init__(self, body=''):
        self.HTMLBody = body
        self.Subject = 'RE: Coordination'
        self.EntryID = 'synthetic-draft'
        self.To = ''
        self.Attachments = _Attachments()
        self.calls = []

    def Save(self):
        self.calls.append('Save')

    def Display(self):
        self.calls.append('Display')

    def Send(self):
        self.calls.append('Send')


def _outlook_reply_body(own_signature_html: str) -> str:
    """ReplyAll body: Outlook's own reply signature, then the quoted original."""
    inner = re.search(r'(?is)<div class=WordSection1>(.*)</div></body>', own_signature_html)
    own = inner.group(1) if inner else ''
    return ('<html><head><style>p.MsoNormal{margin:0in}</style></head><body lang=EN-US>'
            '<div class=WordSection1><p class=MsoNormal><o:p>&nbsp;</o:p></p>' + own +
            '<div style=\'border:none;border-top:solid #E1E1E1 1.0pt;padding:3.0pt 0in 0in 0in\'>'
            '<p class=MsoNormal><b>From:</b> Sender<br><b>Sent:</b> Monday<br>'
            '<b>Subject:</b> Coordination</p></div>'
            '<p class=MsoNormal>Dear,</p><p class=MsoNormal>Earlier letter.</p>'
            '<p class=MsoNormal>Thank you<br>and best regards,</p></div></body></html>')


class _Outlook:
    def __init__(self, reply_body=None):
        self.mail = _Mail(reply_body if reply_body is not None else '')
        self.reply_body = reply_body

    def CreateItem(self, kind):
        assert kind == 0
        return self.mail

    def GetNamespace(self, name):
        assert name == 'MAPI'
        return self

    def GetItemFromID(self, entry_id, store_id=None):
        assert entry_id == 'synthetic-original'
        outlook = self

        class _Original:
            def ReplyAll(self):
                return outlook.mail
        return _Original()


_BODY = ('<p>Hi X,</p><p>Para one.</p><table border=1><tr><td>1</td></tr><tr><td>2</td></tr>'
         '<tr><td>3</td></tr></table><ul><li>a</li><li>b</li></ul><p>Closing line.</p>')


def _words(html: str) -> str:
    return re.sub(r'\s+', ' ', L._visible_mail_text(html))


def _new_part(body: str) -> str:
    at = body.find('From:')
    return body if at < 0 else body[:at]


def _draft(monkeypatch, outlook, folder, **extra):
    monkeypatch.setattr(L, '_OUTLOOK', [lambda: outlook])
    params = {'body': _BODY, 'body_format': 'html', 'show': False, 'signature': _NAME,
              'signature_dir': str(folder), 'subject_case': 'preserve'}
    params.update(extra)
    return L.draft_email(params, {})


@pytest.mark.parametrize('split_close', [True, False], ids=['split-close', 'joined-close'])
@pytest.mark.parametrize('vml', [True, False], ids=['vml-present', 'vml-stripped'])
def test_reply_new_part_has_one_greeting_and_one_close(tmp_path, monkeypatch, split_close, vml):
    folder, signature = _signature(tmp_path, split_close=split_close, vml=vml)
    outlook = _Outlook(_outlook_reply_body(signature))
    out, said = _draft(monkeypatch, outlook, folder, reply_to='synthetic-original')
    assert out['out']['draft_only'] is True, said
    body = outlook.mail.HTMLBody
    new = _words(_new_part(body))
    assert new.count('Dear,') == 1, new
    assert new.count('Thank you and best regards') == 1, new
    assert new.find('Dear,') < new.find('Hi X,') < new.find('Thank you and best regards')
    assert 'Earlier letter.' in _words(body), 'the quoted original stays'
    assert outlook.mail.calls == ['Save']
    assert 'v:imagedata' not in body and '_files/' not in body
    assert body.count('cid:archhub-signature-') == 2


@pytest.mark.parametrize('split_close', [True, False], ids=['split-close', 'joined-close'])
def test_reply_without_outlook_signature_still_one_skeleton(tmp_path, monkeypatch, split_close):
    folder, _ = _signature(tmp_path, split_close=split_close, vml=True)
    outlook = _Outlook(_outlook_reply_body('<div class=WordSection1></div></body>'))
    _draft(monkeypatch, outlook, folder, reply_to='synthetic-original')
    new = _words(_new_part(outlook.mail.HTMLBody))
    assert new.count('Dear,') == 1 and new.count('Thank you and best regards') == 1, new


def test_reply_with_no_signature_name_uses_outlooks_own_once(tmp_path, monkeypatch):
    _, signature = _signature(tmp_path, split_close=True, vml=False)
    outlook = _Outlook(_outlook_reply_body(signature))
    out, said = _draft(monkeypatch, outlook, tmp_path, reply_to='synthetic-original', signature='')
    assert out['out']['draft_only'] is True, said
    new = _words(_new_part(outlook.mail.HTMLBody))
    assert new.count('Dear,') == 1 and new.count('Thank you and best regards') == 1, new
    assert new.find('Dear,') < new.find('Hi X,') < new.find('Thank you and best regards')


@pytest.mark.parametrize('split_close', [True, False], ids=['split-close', 'joined-close'])
@pytest.mark.parametrize('vml', [True, False], ids=['vml-present', 'vml-stripped'])
def test_new_draft_one_skeleton_and_logo_embedded(tmp_path, monkeypatch, split_close, vml):
    folder, _ = _signature(tmp_path, split_close=split_close, vml=vml)
    outlook = _Outlook()
    out, said = _draft(monkeypatch, outlook, folder, to='eng@firm.example.test', subject='Sheets')
    assert out['out']['draft_only'] is True, said
    body = outlook.mail.HTMLBody
    words = _words(body)
    assert words.count('Dear,') == 1 and words.count('Thank you and best regards') == 1, words
    assert body.count('cid:archhub-signature-') == 2
    assert 'v:imagedata' not in body and '_files/' not in body
    assert sorted(a.cid for a in outlook.mail.Attachments) == [
        'archhub-signature-0@local', 'archhub-signature-1@local']
    assert 'Caf\xe9 Studio' in words, 'windows-1252 decoded'
