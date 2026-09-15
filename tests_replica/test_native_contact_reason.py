from nodelang.application_server import NativeRecipientRelay
from nodelang.session_link_transport import public_delivery_reason


def test_reason_is_bounded_and_private_transport_values_are_omitted():
    assert public_delivery_reason('Exact\nreason')=='Exact reason'
    assert len(public_delivery_reason('x'*600))==512
    assert 'secret-value' not in public_delivery_reason('token=secret-value')
    assert 'secret-value' not in public_delivery_reason(r'\\.\pipe\secret-value')


def test_existing_workshop_outcome_includes_reported_reason_without_invented_approval():
    relay=object.__new__(NativeRecipientRelay)
    rows=[];relay._append=lambda **kwargs:rows.append(kwargs)
    relay._settle({'recipient_label':'Claude','space':'existing-workshop','message_id':'original',
        'sender':'user','recipient':'contact','digest':'one'},
        {'status':'held','delivery_status':'held','delivery_reason':'Exact fixture reason','token':'secret-value'})
    assert 'Exact fixture reason' in rows[0]['content']
    assert 'secret-value' not in str(rows)
    assert rows[0]['space_root']=='existing-workshop' and rows[0]['reply_to']=='original'
    assert 'permission gate' not in rows[0]['content']
