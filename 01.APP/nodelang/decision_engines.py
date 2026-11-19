"""Decision nodes (Makkook-style): Optimize and Schedule, both on the HiGHS solver (MIT).

Both are pure: they read only their wired rows and parameters, change nothing outside the document,
and stop at their time limit. Writing a result into a host program is a separate effect node.
"""
import math
from contextlib import suppress
import os
import threading
import time

MAX_SOLVE_CAP = 30.0
# Schedule bounds: the days of work it lays out and the start choices the solver may weigh (memory stays small).
HORIZON_MAX = 3650
STARTS_MAX = 200_000
TASKS_MAX = 1000
SENSES = ('Minimize', 'Maximize')
OPS = ('<=', '>=', '=')


_LOADED = threading.Lock()
_HIGHSPY = None


def _highs(node):
    """highspy, with its one-time licence banner (printed by the first solver object) kept off the app's output."""
    global _HIGHSPY
    with _LOADED:
        if _HIGHSPY is None:
            saved = null = None
            try:
                saved, null = os.dup(1), os.open(os.devnull, os.O_WRONLY)
                os.dup2(null, 1)
            except OSError:
                saved = null = None
            try:
                import highspy
                highspy.Highs()
                import ctypes
                with suppress(OSError):  # This optional flush is only for the native solver banner.
                    ctypes.CDLL('ucrtbase').fflush(None)
            except ImportError:
                raise ValueError('%s needs the HiGHS solver (highspy), which is not in this ArchHub. Update ArchHub to get it.' % node)
            finally:
                if saved is not None:
                    os.dup2(saved, 1)
                    os.close(saved)
                if null is not None:
                    os.close(null)
            _HIGHSPY = highspy
    h = _HIGHSPY.Highs()
    h.setOptionValue('output_flag', False)
    h.setOptionValue('threads', 1)
    return _HIGHSPY, h


def _rows(feeds):
    rows = feeds.get('in')
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list) or not rows:
        raise ValueError('Wire a list of rows into in')
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError('Every wired row must be a record of named fields')
    return rows


def _seconds(params):
    value = params.get('time_limit')
    if value is None or value == '':
        return 2.0
    try:
        value = float(value) if not isinstance(value, bool) else math.nan
    except (TypeError, ValueError):
        value = math.nan
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Time limit must be a positive number of seconds')
    return min(value, MAX_SOLVE_CAP)


def _whole(value, default, what, low):
    """A whole number; only a missing value takes the default (an explicit 0 stays 0 and is checked)."""
    if value is None or value == '':
        return default
    if isinstance(value, bool):
        raise ValueError('%s must be a whole number, not yes/no' % what)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError('%s must be a whole number' % what) from None
    if not math.isfinite(number) or number != int(number):
        raise ValueError('%s must be a whole number' % what)
    if number < low:
        raise ValueError('%s must be at least %d' % (what, low))
    return int(number)


def _number(row, field, what):
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('%s: every row needs a finite number in %s' % (what, field))
    return float(value)


def _list(value, name):
    if isinstance(value, str):
        import json
        value = json.loads(value or '[]')
    if not isinstance(value, list):
        raise ValueError(name + ' must be a list')
    return value


def optimize(params, feeds):
    """Choose an amount of each wired row: minimize or maximize sum(field x amount) under linear limits."""
    highspy, h = _highs('Optimize')
    rows = _rows(feeds)
    config = {**(params or {}), **{k: v for k, v in (feeds or {}).items() if v is not None and k != 'in'}}
    objective, sense = str(config.get('objective') or '').strip(), str(config.get('sense') or 'Minimize')
    if not objective:
        raise ValueError('Name the field to optimize in objective')
    if sense not in SENSES:
        raise ValueError('Choose one of: ' + ', '.join(SENSES))
    limits = _list(config.get('constraints', []), 'Constraints')
    for limit in limits:
        if (not isinstance(limit, dict) or set(limit) != {'field', 'op', 'value'} or limit['op'] not in OPS
                or isinstance(limit['value'], bool) or not isinstance(limit['value'], (int, float))
                or not math.isfinite(limit['value'])):
            raise ValueError('Each constraint needs field, op (<=, >= or =) and a finite number value')
    most = config.get('max_each')
    if most is None or most == '':
        most = highspy.kHighsInf
    else:
        try:
            most = float(most) if not isinstance(most, bool) else math.nan
        except (TypeError, ValueError):
            most = math.nan
        if math.isnan(most) or most < 0:
            raise ValueError('Max each must be a number of 0 or more (empty for no limit)')
        most = min(most, highspy.kHighsInf)
    whole = config.get('whole_amounts') in (True, 'true', 'True')
    h.setOptionValue('time_limit', _seconds(config))
    sign = 1.0 if sense == 'Minimize' else -1.0
    kind = highspy.HighsVarType.kInteger if whole else highspy.HighsVarType.kContinuous
    amounts = [h.addVariable(lb=0, ub=most, obj=sign * _number(row, objective, 'Objective'), type=kind) for row in rows]
    for limit in limits:
        expression = sum(_number(row, limit['field'], 'Constraint') * x for row, x in zip(rows, amounts))
        bound = float(limit['value'])
        h.addConstr(expression <= bound if limit['op'] == '<=' else expression >= bound if limit['op'] == '>=' else expression == bound)
    h.run()
    status = h.modelStatusToString(h.getModelStatus())
    solved = h.getModelStatus() in (highspy.HighsModelStatus.kOptimal, highspy.HighsModelStatus.kTimeLimit) and h.getInfo().primal_solution_status == 2
    if not solved:
        return {'out': [], 'objective': None, 'status': status}, 'No answer: ' + status
    values = h.getSolution().col_value
    out = [{**row, 'amount': round(value, 9)} for row, value in zip(rows, values)]
    total = sign * h.getInfo().objective_function_value
    return {'out': out, 'objective': total, 'status': status}, '%s %s = %g (%s)' % (sense, objective, total, status)


def schedule(params, feeds):
    """Start and end of each wired task: durations, 'after' links and a crew limit; the earliest finish.

    A list schedule (serial generation, longest tail first) gives a valid answer and the horizon; a
    time-indexed MIP on HiGHS then improves it within the time limit. Its answer is never worse."""
    highspy, h = _highs('Schedule')
    config = {**(params or {}), **{k: v for k, v in (feeds or {}).items() if v is not None and k != 'in'}}
    began, limit = time.perf_counter(), _seconds(config)
    rows = _rows(feeds)
    crews = _whole(config.get('crews'), 1, 'Crews', 1)
    names = [str(row.get('name') or '').strip() for row in rows]
    if not all(names) or len(set(names)) != len(names):
        raise ValueError('Every task needs a unique name')
    index = {name: i for i, name in enumerate(names)}
    n, dur, need, before = len(rows), [], [], []
    for row in rows:
        value = _number(row, 'duration', 'Schedule')
        if value < 0 or value != int(value):
            raise ValueError('Durations are whole, nonnegative days')
        dur.append(int(value))
        crew = _whole(row.get('crew'), 1, '%s crew' % names[len(need)], 1)
        if crew > crews:
            raise ValueError('%s needs %d crews; only %d are available' % (row.get('name'), crew, crews))
        need.append(crew)
        after = row.get('after') or []
        after = [a.strip() for a in after.split(',')] if isinstance(after, str) else [str(a).strip() for a in after]
        for name in filter(None, after):
            if name not in index:
                raise ValueError('%s comes after %s, which is not a wired task' % (row['name'], name))
        before.append(sorted({index[name] for name in after if name}))
    if n > TASKS_MAX:
        raise ValueError('Schedule takes at most %d tasks; %d are wired' % (TASKS_MAX, n))
    if sum(dur) > HORIZON_MAX:
        raise ValueError('Schedule lays out at most %d days of work; these tasks add up to %d' % (HORIZON_MAX, sum(dur)))
    # Topological order; a loop in the after links has no schedule.
    order, placed, pending = [], set(), list(range(n))
    while pending:
        ready = [i for i in pending if all(p in placed for p in before[i])]
        if not ready:
            return {'out': [], 'finish': None, 'status': 'Infeasible: the after links make a loop'}, 'No schedule: the after links make a loop'
        for i in ready:
            order.append(i)
            placed.add(i)
        pending = [i for i in pending if i not in placed]
    early = [0] * n
    for i in order:
        early[i] = max([early[p] + dur[p] for p in before[i]] or [0])
    tail = [0] * n
    for i in reversed(order):
        tail[i] = dur[i] + max([tail[j] for j in range(n) if i in before[j]] or [0])
    # Serial list schedule: earliest start that fits the crews, longest remaining chain first.
    use, start = [0] * (sum(dur) + 1), [0] * n
    for i in sorted(order, key=lambda i: (early[i], -tail[i])):
        t = max([start[p] + dur[p] for p in before[i]] or [0])
        clash = next((u for u in range(t, t + dur[i]) if use[u] + need[i] > crews), None)
        while clash is not None:   # jump past the busy day instead of trying each day again
            t = clash + 1
            clash = next((u for u in range(t, t + dur[i]) if use[u] + need[i] > crews), None)
        start[i] = t
        for u in range(t, t + dur[i]):
            use[u] += need[i]
    upper = max([start[i] + dur[i] for i in range(n)] or [0])
    lower = max(max([early[i] + dur[i] for i in range(n)] or [0]), -(-sum(d * c for d, c in zip(dur, need)) // crews))
    status = 'Optimal'
    late = [upper - tail[i] for i in range(n)]
    choices = sum(late[i] - early[i] + 1 for i in range(n))
    over = lambda: time.perf_counter() - began > limit
    if upper > lower and (choices > STARTS_MAX or over()):
        status = 'Time limit reached'   # too big to improve within the limits: the list schedule stands
    elif upper > lower:
        try:
            x = _starts_model(highspy, h, n, dur, need, before, early, late, lower, upper, crews, start, over)
        except TimeoutError:
            x = None
            status = 'Time limit reached'
    if upper > lower and status == 'Optimal':
        h.setOptionValue('time_limit', max(0.05, limit - (time.perf_counter() - began)))
        h.run()
        found = h.getInfo().primal_solution_status == 2
        if found and h.getInfo().objective_function_value < upper - 0.5:
            values = h.getSolution().col_value
            start = [next(t for t in range(early[i], late[i] + 1) if values[x[i, t]] > 0.5) for i in range(n)]
        status = 'Optimal' if h.getModelStatus() == highspy.HighsModelStatus.kOptimal else 'Time limit reached'
    out = [{**row_, 'start': start[i], 'end': start[i] + dur[i]} for i, row_ in enumerate(rows)]
    out.sort(key=lambda r: (r['start'], r['end']))
    total = max([r['end'] for r in out] or [0])
    return {'out': out, 'finish': total, 'status': status}, 'Finishes on day %d (%s)' % (total, status)


def _starts_model(highspy, h, n, dur, need, before, early, late, lower, upper, crews, start, over):
    """The time-indexed model, built under the same clock: TimeoutError when building alone runs past the limit."""
    x = {}   # x[i, t] = 1 when task i starts on day t, inside its early..late window
    for i in range(n):
        if over():
            raise TimeoutError
        for t in range(early[i], late[i] + 1):
            x[i, t] = h.addVariable(lb=0, ub=1, obj=0.0, type=highspy.HighsVarType.kInteger).index
    finish = h.addVariable(lb=lower, ub=upper, obj=1.0).index

    def row(lo, hi, terms):
        h.addRow(lo, hi, len(terms), [k for k, _ in terms], [v for _, v in terms])
    for i in range(n):
        if over():
            raise TimeoutError
        row(1, 1, [(x[i, t], 1.0) for t in range(early[i], late[i] + 1)])
        row(dur[i], highspy.kHighsInf, [(finish, 1.0)] + [(x[i, t], -float(t)) for t in range(early[i], late[i] + 1)])
        for p in before[i]:
            row(dur[p], highspy.kHighsInf, [(x[i, t], float(t)) for t in range(early[i], late[i] + 1)]
                + [(x[p, t], -float(t)) for t in range(early[p], late[p] + 1)])
    for u in range(upper):
        if over():
            raise TimeoutError
        terms = [(x[i, t], float(need[i])) for i in range(n) if dur[i] for t in range(max(early[i], u - dur[i] + 1), min(late[i], u) + 1)]
        if terms:
            row(-highspy.kHighsInf, crews, terms)
    # The list schedule is the starting answer, so a time limit still returns at least it.
    guess = [0.0] * h.getNumCol()
    for i in range(n):
        guess[x[i, start[i]]] = 1.0
    guess[finish] = float(upper)
    try:
        h.setSolution(_solution(highspy, guess))
    except (AttributeError, TypeError):
        guess = None
    return x


def _solution(highspy, values):
    solution = highspy.HighsSolution()
    solution.col_value = values
    solution.value_valid = True
    return solution
