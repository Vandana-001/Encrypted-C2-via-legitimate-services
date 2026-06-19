# Threshold Management Guide

Decision thresholds determine whether XGBoost and TCN anomaly scores trigger alerts. To accommodate diverse network baselines, NIDS-Live implements three layers of threshold control.

---

## 1. Default Threshold Settings

Default values and clipping bounds are configured in `config.py` and verified during startup:

| Model | Default Threshold | Lower Bound (Floor) | Upper Bound (Ceiling) | Step Size |
| :--- | :--- | :--- | :--- | :--- |
| **XGBoost** | `0.2` | `0.1` | `0.6` | `0.005` |
| **TCN** | `0.022` | `0.010` | `0.100` | `0.001` |

---

## 2. Three-Layer Threshold Control

### Layer 1: Manual Controls
* **Mechanism**: Operators adjust thresholds in real time using dashboard sliders or via the POST `/api/thresholds` endpoint.
* **Persistence**: Updated thresholds are written immediately to `models/runtime_thresholds.json`. If the application restarts, these values are loaded to maintain continuity.
* **Audit Trail**: Every manual adjustment is logged to the audit log with the reason `"manual"`.

### Layer 2: Calibration Assistant
* **Mechanism**: The operator records a baseline window of clean, non-attack network traffic (e.g. 5 minutes). The assistant builds an empirical cumulative distribution function (ECDF) of raw scores.
* **Suggested Thresholds**: Upon stopping calibration, the assistant suggests a new threshold at a configurable percentile of the baseline distribution (default: `99.5%` or `0.995` percentile).
  $$\text{Suggested Threshold} = \text{Percentile}(P_{\text{raw}}, 99.5)$$
* **Operator Action**: Suggestions are displayed on the UI and must be manually applied by the operator. Upon application, they are persisted and logged with the reason `"calibration"`.
* **Important Constraint**: Calibration assumes the recorded baseline contains only benign traffic. Recording during an ongoing attack will skew the distribution and lead to elevated false negative rates.

### Layer 3: Auto-Tuning Engine
* **Mechanism**: A background thread (`pipeline/auto_tuner.py`) monitors traffic passively and adapts thresholds to long-term drift.
* **Tuning Logic**:
  * **Interval**: Runs every `300` seconds (5 minutes).
  * **Trailing Window**: Analyzes raw model scores over a trailing `1800` second (30 minutes) window.
  * **Alert Exclusion**: To prevent the auto-tuner from raising thresholds to accommodate attacks, any flow segment containing high anomaly scores or flagged alerts is excluded from the window.
  * **Target Percentile**: Calculates the `99.5%` percentile of benign scores.
  * **Maximum Adjustment Constraint**: To prevent runaway threshold drift, the adjustment per cycle is capped at a maximum of `10%` of the current threshold value:
    $$\Delta_{\text{max}} = 0.1 \times T_{\text{current}}$$
    $$T_{\text{new}} = \text{clip}\left(T_{\text{suggested}}, T_{\text{current}} - \Delta_{\text{max}}, T_{\text{current}} + \Delta_{\text{max}}\right)$$
  * **Bounding**: The resulting threshold is clipped to the Floor and Ceiling bounds before application.
  * **Audit Trail**: Auto-tune updates are persisted and logged with the reason `"auto-tune"`.

---

## 3. Threshold Audit Logging

All threshold adjustments are appended to `logs/threshold_audit.jsonl` in JSON Lines format.

### Schema of Audit Log Entry
Each JSON line contains the following keys:
* `ts` (string): RFC 3339 formatted ISO timestamp.
* `component` (string): Set to `"threshold"`.
* `model` (string): Either `"xgb"` or `"tcn"`.
* `old` (float): The threshold value before the update.
* `new` (float): The newly applied threshold value.
* `reason` (string): One of `"manual"`, `"calibration"`, or `"auto-tune"`.

### Example Log Lines
```json
{"ts": "2026-06-19T05:36:38.990865+00:00", "component": "threshold", "model": "xgb", "old": 0.2, "new": 0.2079, "reason": "auto-tune"}
{"ts": "2026-06-19T05:41:38.991366+00:00", "component": "threshold", "model": "tcn", "old": 0.022, "new": 0.025, "reason": "manual"}
```
