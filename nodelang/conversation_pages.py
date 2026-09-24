"""Durable page protection in the ordinary conversation database.

Identity and resolution are admitted by the owning application, never by page
IDs. No draft text, credentials, timer or worker lives here.
"""
import hashlib
import json
import math
import re
import uuid


PAGE_PROTECTION_VERSION = 5
# Resolver for a conversation created inside a page-protected store: every page
# it can ever have is tracked from its first moment, so it has no legacy drafts.
BIRTH_IDENTITY = ('archhub:conversation-birth',) * 5
IDENTITY_FIELDS = ('session_root', 'subject_root', 'view_root', 'tenant_root', 'assurance_root')
TRACKING_FIELDS = ('conversation_id', 'state', 'resolver_identity', 'resolved_at',
                   'resolved_activity_revision', 'resolution_digest')
PAGE_FIELDS = ('conversation_id', 'page_id', 'open_digest', *IDENTITY_FIELDS,
    'page_revision', 'state', 'draft_state', 'opened_at', 'changed_at',
    'last_request_digest', 'resolution_kind', 'resolution_reference', 'resolver_identity')


def page_schema_statements():
    return (
        """CREATE TABLE conversation_page_tracking(conversation_id TEXT PRIMARY KEY REFERENCES conversations(id),
            state TEXT NOT NULL CHECK(state IN ('unknown','ready')), resolver_identity TEXT NOT NULL,
            resolved_at REAL, resolved_activity_revision INTEGER NOT NULL CHECK(resolved_activity_revision>=0),
            resolution_digest TEXT,
            CHECK((state='unknown' AND resolver_identity='[]' AND resolved_at IS NULL
                AND resolved_activity_revision=0 AND resolution_digest IS NULL)
                OR (state='ready' AND resolved_at IS NOT NULL AND resolved_activity_revision>0
                    AND length(resolution_digest)=64)))""",
        """CREATE TABLE conversation_pages(
            conversation_id TEXT NOT NULL REFERENCES conversations(id), page_id TEXT NOT NULL,
            open_digest TEXT NOT NULL CHECK(length(open_digest)=64),
            session_root TEXT NOT NULL, subject_root TEXT NOT NULL, view_root TEXT NOT NULL,
            tenant_root TEXT NOT NULL, assurance_root TEXT NOT NULL,
            page_revision INTEGER NOT NULL CHECK(page_revision>0),
            state TEXT NOT NULL CHECK(state IN ('open','closed')),
            draft_state TEXT NOT NULL CHECK(draft_state IN ('unknown','dirty','clear')),
            opened_at REAL NOT NULL, changed_at REAL NOT NULL,
            last_request_digest TEXT NOT NULL CHECK(length(last_request_digest)=64),
            resolution_kind TEXT NOT NULL CHECK(resolution_kind IN ('none','initial-empty','saved','discard','owner-discard')),
            resolution_reference TEXT, resolver_identity TEXT NOT NULL,
            PRIMARY KEY(conversation_id,page_id), UNIQUE(conversation_id,open_digest))""",
        "CREATE INDEX conversation_pages_protected ON conversation_pages(conversation_id,page_id) WHERE state!='closed' OR draft_state!='clear'",
    )


def _text(value, label, maximum=512):
    if type(value) is not str or not value or '\0' in value or len(value.encode('utf-8')) > maximum:
        raise ValueError('invalid page ' + label)
    return value


def _integer(value, label):
    if type(value) is not int or not 0 <= value < 2**63:
        raise ValueError('invalid page ' + label)
    return value


def _identity(identity):
    if not isinstance(identity, (tuple, list)) or len(identity) != len(IDENTITY_FIELDS):
        raise ValueError('invalid stable page identity')
    return tuple(_text(value, 'identity') for value in identity)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def _valid_page(row):
    row = dict(row)
    for field in ('conversation_id', 'page_id', *IDENTITY_FIELDS):
        _text(row[field], field)
    if _integer(row['page_revision'], 'revision') == 0:
        raise ValueError('invalid page revision')
    for field in ('open_digest', 'last_request_digest'):
        if type(row[field]) is not str or len(row[field]) != 64 or any(c not in '0123456789abcdef' for c in row[field]):
            raise ValueError('invalid page digest')
    if row['state'] not in ('open', 'closed') or row['draft_state'] not in ('unknown', 'dirty', 'clear'):
        raise ValueError('invalid page state')
    for field in ('opened_at', 'changed_at'):
        value = row[field]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 253402300799:
            raise ValueError('invalid page timestamp')
    if row['changed_at'] < row['opened_at']:
        raise ValueError('page timestamp moved backwards')
    kind = row['resolution_kind']
    if kind not in ('none', 'initial-empty', 'saved', 'discard', 'owner-discard'):
        raise ValueError('invalid page resolution')
    if (kind == 'none') != (row['draft_state'] != 'clear'):
        raise ValueError('page resolution does not explain draft state')
    if kind == 'saved':
        _text(row['resolution_reference'], 'saved reference')
    elif kind == 'none' and row['draft_state'] == 'dirty' and row['resolution_reference'] is not None:
        _text(row['resolution_reference'], 'pending save reference')
    elif row['resolution_reference'] is not None:
        raise ValueError('unexpected page resolution reference')
    try:
        resolver = json.loads(row['resolver_identity'])
    except (ValueError, TypeError):
        raise ValueError('invalid page resolver') from None
    if kind == 'owner-discard':
        _identity(resolver)
    elif resolver != []:
        raise ValueError('unexpected page resolver')
    return row


def _valid_tracking(row):
    row = dict(row)
    _text(row['conversation_id'], 'conversation')
    _integer(row['resolved_activity_revision'], 'tracking activity revision')
    if row['state'] == 'unknown':
        if (row['resolver_identity'], row['resolved_at'], row['resolved_activity_revision'], row['resolution_digest']) != ('[]', None, 0, None):
            raise ValueError('invalid unknown page tracking state')
    elif row['state'] == 'ready':
        try:
            _identity(json.loads(row['resolver_identity']))
        except (ValueError, TypeError):
            raise ValueError('invalid page tracking resolver') from None
        value, digest = row['resolved_at'], row['resolution_digest']
        if (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 253402300799
                or row['resolved_activity_revision'] == 0 or type(digest) is not str or len(digest) != 64
                or any(c not in '0123456789abcdef' for c in digest)):
            raise ValueError('invalid page tracking resolution')
    else:
        raise ValueError('invalid conversation page tracking state')
    return row


def normalize_schema_sql(sql):
    # SQLite quoted literals are case/whitespace sensitive. Normalize only
    # unquoted syntax; accepting a different literal changes CHECK/index semantics.
    parts = re.split(r'''('(?:''|[^'])*'|"(?:""|[^"])*"|`(?:``|[^`])*`|\[[^\]]*\])''', sql or '')
    return ''.join(part if index % 2 else ''.join(part.lower().split()) for index, part in enumerate(parts))


def validate_page_schema(database):
    expected = {statement.split()[2].split('(', 1)[0]:statement for statement in page_schema_statements()}
    for name, statement in expected.items():
        row = database.execute('SELECT type,sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
        kind = 'index' if ' INDEX ' in statement else 'table'
        if row is None or row[0] != kind or normalize_schema_sql(row[1]) != normalize_schema_sql(statement):
            raise ValueError('invalid required page protection schema: ' + name)


def reconcile_page_protection(database, check):
    """Recovery-only bounded/deadline-aware traversal, not a normal read path."""
    validate_page_schema(database)
    for row in database.execute('SELECT ' + ','.join(TRACKING_FIELDS) + ' FROM conversation_page_tracking ORDER BY conversation_id'):
        check()
        _valid_tracking(dict(zip(TRACKING_FIELDS, row)))
    cursor = database.execute('SELECT ' + ','.join(PAGE_FIELDS) + ' FROM conversation_pages ORDER BY conversation_id,page_id')
    for values in cursor:
        check()
        _valid_page(dict(zip(PAGE_FIELDS, values)))
    if database.execute("""SELECT 1 FROM conversation_page_tracking p LEFT JOIN conversation_retention r
            ON r.conversation_id=p.conversation_id WHERE p.state='ready' AND (r.conversation_id IS NULL
            OR r.last_activity_at IS NULL OR p.resolved_activity_revision>r.activity_revision
            OR p.resolved_at>r.last_activity_at) LIMIT 1""").fetchone():
        raise ValueError('page tracking resolution is outside retained activity')
    if database.execute("""SELECT 1 FROM conversation_pages p LEFT JOIN conversation_retention r
            ON r.conversation_id=p.conversation_id WHERE r.conversation_id IS NULL OR r.last_activity_at IS NULL
            OR p.changed_at>r.last_activity_at OR p.page_revision>r.activity_revision LIMIT 1""").fetchone():
        raise ValueError('page protection is outside retained activity')
    check()


class ConversationPageProtection:
    def initialize_page_protection(self, *, before_commit=None):
        """Explicit v4-to-v5 activation; all legacy tracking remains unknown."""
        if before_commit is not None and not callable(before_commit):
            raise ValueError('page protection activation commit guard is invalid')
        with self._transaction(write=True, before_commit=before_commit):
            version = self._db.execute('PRAGMA user_version').fetchone()[0]
            identity = self._db.execute('SELECT singleton,instance_id FROM history_identity LIMIT 2').fetchall()
            if (version not in (4, PAGE_PROTECTION_VERSION) or len(identity) != 1
                    or tuple(identity[0]) != (1, self.instance_id)
                    or self._db.execute('PRAGMA application_id').fetchone()[0] != 0x41484348):
                raise ValueError('page protection initialization identity or format mismatch')
            self._validate_retention_source_schema(version)
            if version == 4:
                for statement in page_schema_statements():
                    self._db.execute(statement)
                self._db.execute('PRAGMA user_version=%d' % PAGE_PROTECTION_VERSION)
            validate_page_schema(self._db)
        return PAGE_PROTECTION_VERSION

    def _require_page_version(self):
        if self._db.execute('PRAGMA user_version').fetchone()[0] != PAGE_PROTECTION_VERSION:
            raise ValueError('durable conversation page protection is not initialized')

    @staticmethod
    def _page_guard(before_commit):
        if not callable(before_commit):
            raise ValueError('page mutation requires an admitted owner commit guard')
        before_commit()

    def _page_protection_status(self, conversation_id):
        self._require_page_version()
        self._head(conversation_id)
        tracking = self._db.execute('SELECT ' + ','.join(TRACKING_FIELDS) + ' FROM conversation_page_tracking WHERE conversation_id=?',
                                    (conversation_id,)).fetchone()
        tracking_state = _valid_tracking(tracking)['state'] if tracking is not None else 'unknown'
        if tracking_state not in ('unknown', 'ready'):
            raise ValueError('invalid conversation page tracking state')
        if tracking_state == 'ready':
            activity = self._retention_status(conversation_id, require_enabled=True)
            if (activity['last_activity_at'] is None or tracking['resolved_activity_revision'] > activity['activity_revision']
                    or tracking['resolved_at'] > activity['last_activity_at']):
                raise ValueError('page tracking resolution is outside retained activity')
        protected_page = self._db.execute("SELECT page_id FROM conversation_pages WHERE conversation_id=? "
            "AND (state!='closed' OR draft_state!='clear') LIMIT 1", (conversation_id,)).fetchone()
        return {'tracking_state':tracking_state, 'protected':tracking_state != 'ready' or protected_page is not None}

    def page_protection_status(self, conversation_id):
        with self._transaction():
            return self._page_protection_status(conversation_id)

    def _require_pages_clear(self, conversation_id):
        if self._page_protection_status(conversation_id)['protected']:
            raise ValueError('conversation has open, unsaved or unknown page protection')

    def resolve_page_tracking(self, conversation_id, *, resolver_identity, expected_activity_revision, before_commit):
        """Owner-only resolution after verifying deployed tracking and legacy state."""
        _integer(expected_activity_revision, 'activity revision')
        resolver = _identity(resolver_identity)
        digest = _digest((conversation_id, resolver, expected_activity_revision, 'resolve-tracking'))
        with self._transaction(write=True, before_commit=before_commit):
            self._page_guard(before_commit)
            self._require_page_version()
            status = self._retention_status(conversation_id, require_enabled=True)
            prior = self._db.execute('SELECT ' + ','.join(TRACKING_FIELDS) +
                ' FROM conversation_page_tracking WHERE conversation_id=?', (conversation_id,)).fetchone()
            if prior is not None:
                prior = _valid_tracking(prior)
                if (prior['resolution_digest'] == digest and prior['resolved_activity_revision'] ==
                        status['activity_revision'] == expected_activity_revision + 1):
                    return self._page_protection_status(conversation_id)
            if status['activity_revision'] != expected_activity_revision:
                raise ValueError('conversation activity changed before tracking resolution')
            current = self._page_protection_status(conversation_id)
            if current['tracking_state'] == 'ready':
                return current
            changed = self._record_activity(conversation_id)
            row = dict(conversation_id=conversation_id, state='ready', resolver_identity=json.dumps(resolver),
                resolved_at=changed['last_activity_at'], resolved_activity_revision=changed['activity_revision'],
                resolution_digest=digest)
            _valid_tracking(row)
            self._db.execute('INSERT INTO conversation_page_tracking(' + ','.join(TRACKING_FIELDS) +
                ') VALUES(' + ','.join('?' for _ in TRACKING_FIELDS) +
                ') ON CONFLICT(conversation_id) DO UPDATE SET ' +
                ','.join(field + '=excluded.' + field for field in TRACKING_FIELDS[1:]),
                tuple(row[field] for field in TRACKING_FIELDS))
            return self._page_protection_status(conversation_id)

    def born_tracked(self, conversation_id):
        with self._transaction():
            return self._born_tracked(conversation_id)

    def _born_tracked(self, conversation_id):
        if self._db.execute('PRAGMA user_version').fetchone()[0] != PAGE_PROTECTION_VERSION:
            return False
        row = self._db.execute('SELECT ' + ','.join(TRACKING_FIELDS) +
            ' FROM conversation_page_tracking WHERE conversation_id=?', (conversation_id,)).fetchone()
        if row is None:
            return False
        row = _valid_tracking(row)
        return (row['state'] == 'ready' and row['resolved_activity_revision'] == 1
                and row['resolver_identity'] == json.dumps(list(BIRTH_IDENTITY))
                and row['resolution_digest'] == _digest((conversation_id, list(BIRTH_IDENTITY), 1, 'born-tracked')))

    def track_new_conversation(self, conversation_id, *, before_commit=None):
        """Record complete page tracking for a conversation created in this store.

        Refused for any conversation that already has messages, pages, activity
        or a tracking row: only a room with no history can be born tracked.
        """
        with self._transaction(write=True, before_commit=before_commit):
            return self._track_new_conversation(conversation_id)

    def _track_new_conversation(self, conversation_id):
        self._require_page_version()
        if self._born_tracked(conversation_id):
            return self._page_protection_status(conversation_id)
        status = self._retention_status(conversation_id, require_enabled=True)
        if (status['last_sequence'] != 0 or status['activity_revision'] != 0
                or self._db.execute('SELECT 1 FROM messages WHERE conversation_id=? LIMIT 1', (conversation_id,)).fetchone()
                or self._db.execute('SELECT 1 FROM conversation_pages WHERE conversation_id=? LIMIT 1', (conversation_id,)).fetchone()
                or self._db.execute('SELECT 1 FROM conversation_page_tracking WHERE conversation_id=?', (conversation_id,)).fetchone()):
            raise ValueError('only a new, unused conversation is born with complete page tracking')
        changed = self._record_activity(conversation_id)
        row = dict(conversation_id=conversation_id, state='ready', resolver_identity=json.dumps(list(BIRTH_IDENTITY)),
            resolved_at=changed['last_activity_at'], resolved_activity_revision=changed['activity_revision'],
            resolution_digest=_digest((conversation_id, list(BIRTH_IDENTITY), changed['activity_revision'], 'born-tracked')))
        _valid_tracking(row)
        self._db.execute('INSERT INTO conversation_page_tracking(' + ','.join(TRACKING_FIELDS) +
            ') VALUES(' + ','.join('?' for _ in TRACKING_FIELDS) + ')', tuple(row[field] for field in TRACKING_FIELDS))
        return self._page_protection_status(conversation_id)

    def _get_page(self, conversation_id, page_id):
        row = self._db.execute('SELECT ' + ','.join(PAGE_FIELDS) +
            ' FROM conversation_pages WHERE conversation_id=? AND page_id=?', (conversation_id, page_id)).fetchone()
        if row is None:
            raise ValueError('conversation page is not registered')
        return _valid_page(row)

    def read_conversation_page(self, conversation_id, page_id, *, identity):
        identity = _identity(identity)
        with self._transaction():
            self._require_page_version()
            page = self._get_page(conversation_id, page_id)
            if tuple(page[field] for field in IDENTITY_FIELDS) != identity:
                raise ValueError('conversation page belongs to another browser identity')
            return page

    def review_conversation_pages(self, conversation_id, *, limit=50, after_page_id=None):
        """Owner-admitted metadata inventory; never transfer an old page identity.

        The calling capability must admit founder inspection. Each response is
        bounded and each later resolution still requires the current page CAS.
        No draft content, pending save reference or internal digest is returned.
        """
        _integer(limit, 'review limit')
        if not 1 <= limit <= 50:
            raise ValueError('page review limit must be between 1 and 50')
        if after_page_id is not None:
            _text(after_page_id, 'review cursor')
        metadata = ('page_id', 'page_revision', 'state', 'draft_state',
            'resolution_kind', 'opened_at', 'changed_at', *IDENTITY_FIELDS)
        with self._transaction():
            self._require_page_version()
            self._head(conversation_id)
            sql = ('SELECT ' + ','.join(PAGE_FIELDS) + ' FROM conversation_pages '
                "WHERE conversation_id=? AND (state!='closed' OR draft_state!='clear')")
            parameters = [conversation_id]
            if after_page_id is not None:
                sql += ' AND page_id>?'
                parameters.append(after_page_id)
            sql += ' ORDER BY page_id LIMIT ?'
            parameters.append(limit + 1)
            pages = []
            for row in self._db.execute(sql, parameters):
                page = _valid_page(row)
                pages.append({field:page[field] for field in metadata})
            more = len(pages) > limit
            pages = pages[:limit]
            return {'pages':pages, 'next_page_id':pages[-1]['page_id'] if more else None}

    def _put_page(self, page):
        _valid_page(page)
        fields = PAGE_FIELDS
        self._db.execute('INSERT INTO conversation_pages(' + ','.join(fields) + ') VALUES(' +
            ','.join('?' for _ in fields) + ') ON CONFLICT(conversation_id,page_id) DO UPDATE SET ' +
            ','.join(field + '=excluded.' + field for field in fields[2:]), tuple(page[field] for field in fields))

    def open_conversation_page(self, conversation_id, *, identity, request_key, before_commit):
        identity = _identity(identity)
        _text(conversation_id, 'conversation')
        _text(request_key, 'open request', 128)
        digest = _digest((conversation_id, identity, request_key))
        with self._transaction(write=True, before_commit=before_commit):
            self._page_guard(before_commit)
            self._require_page_version()
            self._head(conversation_id)
            prior = self._db.execute('SELECT page_id FROM conversation_pages WHERE conversation_id=? AND open_digest=?',
                                     (conversation_id, digest)).fetchone()
            if prior is not None:
                page = self._get_page(conversation_id, prior[0])
                if tuple(page[field] for field in IDENTITY_FIELDS) != identity:
                    raise ValueError('page opening identity conflict')
                return page  # A retry must never reopen a closed page.
            now = self._retention_now()
            page = dict(conversation_id=conversation_id, page_id=uuid.uuid4().hex, open_digest=digest,
                **dict(zip(IDENTITY_FIELDS, identity)), page_revision=1, state='open', draft_state='unknown',
                opened_at=now, changed_at=now, last_request_digest=digest,
                resolution_kind='none', resolution_reference=None, resolver_identity='[]')
            self._put_page(page)
            self._record_activity(conversation_id)
            return page

    def change_conversation_page(self, conversation_id, page_id, *, identity, expected_page_revision,
                                 action, resolution_reference=None, before_commit):
        identity = _identity(identity)
        return self._change_page(conversation_id, page_id, identity=identity,
            expected_page_revision=expected_page_revision, action=action,
            resolution_reference=resolution_reference, resolver=None, before_commit=before_commit)

    def resolve_abandoned_page(self, conversation_id, page_id, *, resolver_identity,
                               expected_page_revision, before_commit):
        """Separate founder-admitted discard; never impersonates the old browser."""
        return self._change_page(conversation_id, page_id, identity=None,
            expected_page_revision=expected_page_revision, action='owner-discard',
            resolution_reference=None, resolver=_identity(resolver_identity), before_commit=before_commit)

    def _change_page(self, conversation_id, page_id, *, identity, expected_page_revision, action,
                     resolution_reference, resolver, before_commit):
        _integer(expected_page_revision, 'revision')
        if action not in ('dirty', 'unknown', 'close', 'initial-empty', 'saved', 'discard', 'owner-discard'):
            raise ValueError('invalid conversation page action')
        if (action == 'owner-discard') != (resolver is not None):
            raise ValueError('page owner resolution requires a separate admitted resolver')
        if action == 'saved' or action == 'dirty' and resolution_reference is not None:
            _text(resolution_reference, 'saved reference')
        elif resolution_reference is not None:
            raise ValueError('unexpected page resolution reference')
        digest = _digest((conversation_id, page_id, identity, expected_page_revision, action, resolution_reference, resolver))
        with self._transaction(write=True, before_commit=before_commit):
            self._page_guard(before_commit)
            self._require_page_version()
            page = self._get_page(conversation_id, page_id)
            if resolver is None and tuple(page[field] for field in IDENTITY_FIELDS) != identity:
                raise ValueError('conversation page belongs to another browser identity')
            if page['page_revision'] == expected_page_revision + 1 and page['last_request_digest'] == digest:
                return page
            if page['page_revision'] != expected_page_revision:
                raise ValueError('conversation page changed; refresh before resolving')
            if action == 'initial-empty' and not (page['page_revision'] == 1 and page['state'] == 'open'):
                raise ValueError('initial empty resolution is only valid on a new page')
            if page['state'] == 'closed' and action not in ('owner-discard', 'close'):
                raise ValueError('closed conversation pages cannot be reopened or changed')
            if action in ('dirty', 'unknown'):
                # Dirty carries the planned message idempotency key; saved
                # carries the accepted message ID. The owner checks that pair.
                page.update(draft_state=action, resolution_kind='none',
                    resolution_reference=resolution_reference, resolver_identity='[]')
            elif action == 'close':
                page['state'] = 'closed'
            else:
                page.update(draft_state='clear', resolution_kind=action, resolution_reference=resolution_reference,
                    resolver_identity=json.dumps(resolver) if resolver is not None else '[]')
                if resolver is not None:
                    page['state'] = 'closed'
            page.update(page_revision=page['page_revision'] + 1,
                changed_at=max(self._retention_now(), page['changed_at']), last_request_digest=digest)
            self._put_page(page)
            self._record_activity(conversation_id)
            return page
