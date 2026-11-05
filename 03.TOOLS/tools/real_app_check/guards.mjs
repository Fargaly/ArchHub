// Rules the real-app harness applies to every scenario. Kept apart from the CDP driver so courts
// can load them without a window.

// The controls that sign with the Windows user's protected Workspaces key. Pressing one creates that
// key (a Windows prompt on the founder's desktop, outside any isolation) or uses it. The harness never
// presses them; real_app_check.py also reads the key's state before and after a run.
export const SIGNING_CONTROLS = Object.freeze(['Add', 'Remove', 'Republish', 'Stop governing']);

export function refuseSigning(text) {
  const label = String(text ?? '').trim();
  if (SIGNING_CONTROLS.includes(label)) {
    throw new Error('refused: "' + label + '" signs with the protected Workspaces key');
  }
}

// A step passes only when its function returned {pass: true}, gave no failure reason, and every HTTP
// error seen during the step is one it named in expected_http (an expected refusal, by prefix such as
// "400 /api/universal/workshop"). Anything else, including undefined, null or {}, fails.
//
// A step the run cannot honestly exercise (for example, a flow that needs a service this isolated run
// does not have) returns {not_exercised: '<why>'} and is reported as NOT EXERCISED: never PASS.
export function stepVerdict(returned, httpErrors = []) {
  if (returned && typeof returned === 'object' && 'not_exercised' in returned) {
    const reason = typeof returned.not_exercised === 'string' ? returned.not_exercised.trim() : '';
    if (!reason || 'pass' in returned) {
      return { result: 'FAIL', did: 'not_exercised needs a reason and no pass value' };
    }
    return { result: 'NOT EXERCISED', did: reason };
  }
  if (!returned || typeof returned !== 'object' || returned.pass !== true) {
    return { result: 'FAIL', did: (returned && returned.why) || 'the step did not report pass: true' };
  }
  if (returned.why) return { result: 'FAIL', did: 'pass: true with a failure reason: ' + returned.why };
  const expected = Array.isArray(returned.expected_http) ? returned.expected_http.map(String) : [];
  const unexpected = httpErrors.filter(error => !expected.some(prefix => String(error).startsWith(prefix)));
  if (unexpected.length) return { result: 'FAIL', did: 'unexpected HTTP errors: ' + unexpected.join(', ') };
  return { result: 'PASS', did: 'as asked' };
}
