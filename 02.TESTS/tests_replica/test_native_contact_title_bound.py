"""A native session whose title is four-byte characters (emoji) binds as a Workshop contact.

The contact node's title was cut to 150 characters while the primitive bounds a title at 512 UTF-8
bytes, so a session titled with more than about 125 emoji was refused at bind ("primitive text exceeds
its bounded interface", installed 20261001-2310-2d6dc02). The title is now cut on whole characters to
both bounds. Real application and routes; only the external native transport is a fixture.
"""
import pytest

from nodelang import native_contact
from nodelang import universal_application as app
from test_workshop_milestone_one import CLAUDE, harness  # noqa: F401  (harness is a pytest fixture)

FACE = '\U0001F600'


@pytest.mark.parametrize('title', [FACE * 150, FACE * 125, FACE * 126, 'a' * 150, '€' * 200,
                                   'a' * 3 + FACE * 140, FACE * 127 + 'z'])
def test_the_contact_title_is_cut_on_whole_characters_within_both_bounds(title):
    made = native_contact._contact_title({'app': 'claude', 'title': title})
    full = 'Contact: ' + title[:150]
    assert len(made.encode('utf-8')) <= native_contact.CONTACT_TITLE_BYTES == 512
    assert full.startswith(made) and len(made) <= len(full)
    if len(full.encode('utf-8')) <= 512:
        assert made == full, 'a title within the bound is unchanged'
    else:
        assert len((made + full[len(made)]).encode('utf-8')) > 512, 'the cut keeps every character that fits'


def test_a_session_titled_with_150_emoji_binds_and_its_node_title_is_bounded(harness, monkeypatch):
    monkeypatch.setitem(CLAUDE, 'title', FACE * 150)
    titles = []
    original = app.instantiate_universal_primitive

    def recording(*args, **kwargs):
        if kwargs.get('mutation_route') == '/api/universal/native-contact':
            titles.append(kwargs['title'])
        return original(*args, **kwargs)
    monkeypatch.setattr(app, 'instantiate_universal_primitive', recording)
    h = harness
    h.start()
    convo = h.conversation_with_two_agents()          # binds the Claude session over HTTP; refused before
    assert convo['claude'] and convo['claude_digest']
    titles = [title for title in titles if FACE in title]   # the Claude contact (OpenCode binds by its own title)
    assert len(titles) == 1
    assert titles[0].startswith('Contact: ' + FACE) and len(titles[0].encode('utf-8')) <= 512
    assert titles[0] == 'Contact: ' + FACE * ((512 - len('Contact: ')) // 4)
