"""Restore transport and the retained owner before existing Work admission.

This has no Work permission, claim, receipt, or execution implementation. Those
remain in _SelectedWork.effect and the authoritative per-operation routes.
"""
import threading

from .native_session_resume import resume_existing_links


class NativeResumeGuard:
    def __init__(self, owner, *, transport_resume=resume_existing_links):
        self.owner=owner
        self.transport_resume=transport_resume
        self.lock=threading.RLock()
        self.last={'status':'recovery_required','reason':'first_resume_not_run'}

    def recover(self):
        with self.lock:
            self.last={'status':'recovery_required','reason':'transport_resume_required'}
            resumed=self.transport_resume(self.owner._environment)
            if resumed.get('status')!='observed':
                self.last['reason']=resumed.get('reason') or resumed.get('status')
                return dict(self.last)
            status=self.owner.owner_status()
            current=status.get('current')
            if not current or status.get('current_error'):
                self.last['reason']='verified_current_owner_unavailable'
                return dict(self.last)
            if status.get('state')=='unbound':
                actor=self.owner._expected_agent_session
                if not actor:
                    self.last['reason']='original_actor_binding_required'
                    return dict(self.last)
                # Same existing product protocol as the reviewed continuation
                # operator. Inspection does not itself grant continuation.
                self.owner.inspect_enrollment(expected_owner=current['fingerprint'])
                self.owner.connect(expected_owner=current['fingerprint'])
                status=self.owner.owner_status()
                if status.get('agent_session')!=actor or not self.owner._continued:
                    self.last['reason']='original_actor_continuation_unconfirmed'
                    return dict(self.last)
            actor=status.get('agent_session')
            if not actor or status.get('state')!='bound' or status.get('rebind_pending'):
                self.last['reason']='retained_owner_requires_exact_reconciliation'
                return dict(self.last)
            pinned,current=status.get('pinned'),status.get('current')
            if not pinned or not current or pinned.get('instance_digest')!=current.get('instance_digest'):
                self.last['reason']='original_instance_not_verified'
                return dict(self.last)
            if status.get('recovery_required'):
                self.owner.rebind_owner(expected_old_owner=pinned['fingerprint'],
                    expected_new_owner=current['fingerprint'])
            self.last={'status':'owner_restored','actor':actor,'owner':current['fingerprint'],
                'work_admission_required':True,'work_completion':False}
            return dict(self.last)