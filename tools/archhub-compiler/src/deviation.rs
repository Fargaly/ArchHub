//! Robust per-author changes. No notification budget can make admission green.
use crate::Diagnostic;
use serde_json::{json, Value};
pub const METRICS: &[&str] = &[
    "files",
    "lines",
    "ratchet_deltas",
    "tests_removed",
    "languages",
    "scope_spread",
    "rule_hits",
];
fn median(values: &[f64]) -> f64 {
    let mut a = values.to_vec();
    a.sort_by(f64::total_cmp);
    if a.is_empty() {
        0.0
    } else if a.len() % 2 == 0 {
        (a[a.len() / 2 - 1] + a[a.len() / 2]) / 2.0
    } else {
        a[a.len() / 2]
    }
}
fn number(v: &Value) -> Option<f64> {
    v.as_f64().filter(|n| n.is_finite() && *n >= 0.0)
}
fn parameter(context: &Value, rules: &Value, name: &str) -> f64 {
    context
        .get("deviation_parameters")
        .and_then(|p| p.get(name))
        .and_then(number)
        .filter(|v| *v > 0.0)
        .or_else(|| rules.get(name).and_then(number))
        .unwrap_or(1.0)
}
pub fn observe(context: &Value) -> Value {
    let rules = crate::intent::authority()["deviation"].clone();
    let author = context["author"].as_str().unwrap_or("");
    let history: Vec<&Value> = context["history"]
        .as_array()
        .map(|rows| {
            rows.iter()
                .filter(|row| row["author"].as_str() == Some(author))
                .collect()
        })
        .unwrap_or_default();
    let minimum = parameter(context, &rules, "minimum_history") as usize;
    let shift_min = parameter(context, &rules, "minimum_shift_samples") as usize;
    let band = parameter(context, &rules, "mad_multiplier");
    let drift = parameter(context, &rules, "cusum_drift");
    let threshold = parameter(context, &rules, "cusum_threshold");
    let mut metrics = serde_json::Map::new();
    let mut changed = vec![];
    let mut outliers = vec![];
    for key in METRICS {
        let Some(current) = number(&context["metrics"][key]) else {
            continue;
        };
        let samples: Vec<f64> = history
            .iter()
            .filter_map(|row| number(&row["metrics"][key]))
            .collect();
        let state = &context["deviation_state"];
        let absent_state = Value::Null;
        let old = if state["author"].as_str() == Some(author) {
            &state["metrics"][key]
        } else if state["authors"][author]["author"].as_str() == Some(author) {
            &state["authors"][author]["metrics"][key]
        } else {
            &absent_state
        };
        // Bootstrap from measured samples; a mature stored baseline changes
        // only through the sustained-shift branch.
        let mut bootstrap = samples.clone();
        bootstrap.push(current);
        let centre = if samples.len() < minimum {
            median(&bootstrap)
        } else {
            old["median"]
                .as_f64()
                .filter(|v| v.is_finite())
                .unwrap_or_else(|| median(&samples))
        };
        let mad = if samples.len() < minimum {
            median(
                &bootstrap
                    .iter()
                    .map(|n| (n - centre).abs())
                    .collect::<Vec<_>>(),
            )
        } else {
            number(&old["mad"]).unwrap_or_else(|| {
                median(
                    &samples
                        .iter()
                        .map(|n| (n - centre).abs())
                        .collect::<Vec<_>>(),
                )
            })
        };
        let scale = (1.4826 * mad).max(1.0);
        let z = (current - centre) / scale;
        let outlier = samples.len() >= minimum && z.abs() > band;
        let prior_up = number(&old["cusum_up"]).unwrap_or(0.0);
        let prior_down = number(&old["cusum_down"]).unwrap_or(0.0);
        let up = (prior_up + z - drift).max(0.0);
        let down = (prior_down - z - drift).max(0.0);
        let direction = if z > 0.0 { 1.0 } else { -1.0 };
        let trailing = samples
            .iter()
            .rev()
            .take_while(|v| ((**v - centre) / scale) * direction > band)
            .count()
            + 1;
        let shift = outlier && trailing >= shift_min && up.max(down) >= threshold;
        if shift {
            let mut new_samples: Vec<f64> = samples
                .iter()
                .rev()
                .take(shift_min.saturating_sub(1))
                .copied()
                .collect();
            new_samples.push(current);
            let next = median(&new_samples);
            let next_mad = median(
                &new_samples
                    .iter()
                    .map(|v| (v - next).abs())
                    .collect::<Vec<_>>(),
            );
            metrics.insert((*key).into(),json!({"median":next,"mad":next_mad,"cusum_up":0.0,"cusum_down":0.0,"status":"method_shift","samples":samples.len()+1}));
            changed.push(json!({"metric":key,"previous_median":centre,"median":next,"reason":"sustained change point","author":author}));
        } else {
            metrics.insert((*key).into(),json!({"median":centre,"mad":mad,"cusum_up":up,"cusum_down":down,"status":if samples.len()<minimum{"bootstrap"}else if outlier{"outlier"}else{"held"},"samples":samples.len()+1}));
            if outlier {
                outliers.push(
                    json!({"metric":key,"value":current,"median":centre,"mad":mad,"robust_z":z}),
                );
            }
        }
    }
    json!({"schema_version":1,"author":author,"metrics":metrics,"method_changes":changed,"outliers":outliers,
        "daily_alert_budget":context["daily_alert_budget"].as_u64().unwrap_or_else(||rules["daily_alert_budget"].as_u64().unwrap_or(5)),
        "notification_only_budget":true,"history_samples":history.len()})
}
pub fn check(context: &Value) -> Vec<Diagnostic> {
    let observation = observe(context);
    let anchor = context["files"]
        .as_array()
        .and_then(|a| a.first())
        .and_then(Value::as_str)
        .unwrap_or("COMMIT_EDITMSG");
    let missing: Vec<_> = METRICS
        .iter()
        .filter(|key| number(&context["metrics"][key]).is_none())
        .copied()
        .collect();
    if !missing.is_empty() && context["files"].as_array().is_some_and(|a| !a.is_empty()) {
        return vec![Diagnostic{code:"E0200".into(),language:crate::language_name(anchor).into(),file:anchor.into(),line:1,column:1,
            message:format!("change has no measured deviation metrics: {}",missing.join(", ")),
            help:"derive every current metric from the pending change and compiler report; unknown history stays absent rather than invented".into()}];
    }
    if context["why"]
        .as_str()
        .is_some_and(|s| !s.trim().is_empty())
    {
        return vec![];
    }
    let anchor = context["files"]
        .as_array()
        .and_then(|a| a.first())
        .and_then(Value::as_str)
        .unwrap_or("COMMIT_EDITMSG");
    observation["outliers"].as_array().map(|rows|rows.iter().map(|row|Diagnostic{
        code:"E0200".into(),language:crate::language_name(anchor).into(),file:anchor.into(),line:1,column:1,
        message:format!("author change metric `{}` is outside its median/MAD band ({} versus median {})",row["metric"].as_str().unwrap_or(""),row["value"],row["median"]),
        help:"provide a Why: explanation; persistent measured shifts are recorded as a new author method, never excused by an alert budget".into()
    }).collect()).unwrap_or_default()
}
