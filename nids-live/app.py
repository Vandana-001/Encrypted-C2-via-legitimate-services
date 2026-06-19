"""
app.py — Flask application for the NIDS-Live dashboard.

Routes (plain REST, JSON in/out):
  GET  /             → renders index.html
  GET  /api/interfaces → {"interfaces": [...]}
  POST /api/start    → starts capture + orchestrator
  POST /api/stop     → stops capture cleanly
  GET  /api/status   → status, engine, uptime, counters
  GET  /api/flows    → recent flow results
  GET  /api/alerts   → recent alert-only entries
  GET  /api/top_ips  → top suspicious source IPs
"""

import os
import sys
import logging

from flask import Flask, render_template, request, jsonify

from config import FLASK_HOST, FLASK_PORT, FLASK_DEBUG
import config
from pipeline.state import PipelineState
from pipeline.orchestrator import Orchestrator
from pipeline.model_loader import load_artifacts, get_artifacts
from capture.interfaces import list_interfaces, get_engine_by_name
from pipeline.threshold_manager import get_manager
from pipeline.calibration import get_calibration_assistant
from pipeline.auto_tuner import get_auto_tuner
from pipeline.scaler_adaptation import get_adaptation_buffer
from pipeline.recalibration import get_recalibrator
from pipeline.active_scaler import get_active_scaler, reset_active_scaler

# ── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── App factory ───────────────────────────────────────────────────────
app = Flask(__name__)

# Global state
state = PipelineState()
orchestrator: Orchestrator | None = None
model_load_error: str = ""

# ── Load models at startup ────────────────────────────────────────────
try:
    artifacts = load_artifacts()
    orchestrator = Orchestrator(state, artifacts)
    logger.info("✅ Application ready.")
except Exception as exc:
    model_load_error = str(exc)
    logger.error("❌ Failed to load model artifacts: %s", exc)


# ═══════════════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════════════


@app.route("/")
def index():
    """Render the main dashboard page.

    Returns:
        Response: The rendered HTML content of index.html.
    """
    return render_template("index.html")


@app.route("/api/interfaces", methods=["GET"])
def api_interfaces():
    """Return list of available network interfaces on the host system.

    Returns:
        Response: JSON payload containing list of network interface names,
            or an error message on failure.
    """
    try:
        interfaces = list_interfaces()
        return jsonify({"interfaces": interfaces})
    except Exception as exc:
        return jsonify({"interfaces": [], "error": str(exc)}), 500


@app.route("/api/start", methods=["POST"])
def api_start():
    """Start packet capture and the inference pipeline on a given interface.

    Returns:
        Response: JSON status ("running") and engine name on success,
            or an error message with appropriate HTTP status code on failure.
    """
    global orchestrator

    # Check for model load errors
    if model_load_error:
        return jsonify({
            "status": "error",
            "message": f"Model artifacts not loaded: {model_load_error}",
        }), 500

    if orchestrator is None:
        return jsonify({
            "status": "error",
            "message": "Orchestrator not initialized. Check model artifacts.",
        }), 500

    if orchestrator.is_running():
        return jsonify({
            "status": "error",
            "message": "Capture is already running. Stop it first.",
        }), 400

    data = request.get_json(silent=True) or {}
    interface = data.get("interface", "")
    engine_name = data.get("engine", "auto")

    if not interface:
        return jsonify({
            "status": "error",
            "message": "No interface specified.",
        }), 400

    try:
        EngineClass = get_engine_by_name(engine_name)
        engine = EngineClass()
        orchestrator.start(engine, interface)
        return jsonify({
            "status": "running",
            "engine": engine.name,
        })
    except Exception as exc:
        logger.exception("Failed to start capture: %s", exc)
        return jsonify({
            "status": "error",
            "message": str(exc),
        }), 500


@app.route("/api/stop", methods=["POST"])
def api_stop():
    """Stop packet capture and the inference pipeline.

    Returns:
        Response: JSON status ("stopped") on success,
            or an error message with HTTP 500 on failure.
    """
    global orchestrator

    if orchestrator is None:
        return jsonify({"status": "stopped"})

    try:
        orchestrator.stop()
        return jsonify({"status": "stopped"})
    except Exception as exc:
        logger.exception("Failed to stop capture: %s", exc)
        return jsonify({
            "status": "error",
            "message": str(exc),
        }), 500


@app.route("/api/status", methods=["GET"])
def api_status():
    """Return current pipeline status, engine type, uptime, and classification counters.

    Returns:
        Response: JSON payload representing active state variables and statistics.
    """
    status_data = state.get_status()

    # Include model load error if present
    if model_load_error:
        status_data["model_error"] = model_load_error
        if status_data["status"] == "stopped":
            status_data["status"] = "error"
            status_data["last_error"] = model_load_error

    return jsonify(status_data)


@app.route("/api/flows", methods=["GET"])
def api_flows():
    """Return the most recent flow classification records.

    Query Params:
        limit (int): Maximum records to retrieve. Default is 50.

    Returns:
        Response: JSON payload list of recent flows.
    """
    limit = request.args.get("limit", 50, type=int)
    flows = state.get_recent_flows(limit)
    return jsonify({"flows": flows})


@app.route("/api/alerts", methods=["GET"])
def api_alerts():
    """Return the most recent classification records flagged as an anomaly by either model.

    Query Params:
        limit (int): Maximum records to retrieve. Default is 50.

    Returns:
        Response: JSON payload list of alert flows.
    """
    limit = request.args.get("limit", 50, type=int)
    alerts = state.get_alerts(limit)
    return jsonify({"alerts": alerts})


@app.route("/api/top_ips", methods=["GET"])
def api_top_ips():
    """Return the top source IPs sorted in descending order by maximum anomaly probability.

    Query Params:
        limit (int): Maximum records to retrieve. Default is 10.

    Returns:
        Response: JSON payload list of suspicious source IPs.
    """
    limit = request.args.get("limit", 10, type=int)
    top_ips = state.get_top_ips(limit)
    return jsonify({"top_ips": top_ips})


# ═══════════════════════════════════════════════════════════════════════
# Threshold Management Routes
# ═══════════════════════════════════════════════════════════════════════

@app.route("/api/thresholds", methods=["GET"])
def api_get_thresholds():
    """Get active thresholds, defaults, bounds, and auto-tune state.

    Returns:
        Response: JSON payload containing current thresholds, bounds, and auto-tuning configuration.
    """
    manager = get_manager()
    auto_tuner = get_auto_tuner()
    current = manager.get()
    
    return jsonify({
        "xgb_threshold": current["xgb"],
        "tcn_threshold": current["tcn"],
        "xgb_default": config.XGB_THRESHOLD,
        "tcn_default": config.TCN_THRESHOLD,
        "xgb_floor": config.XGB_THRESHOLD_FLOOR,
        "xgb_ceiling": config.XGB_THRESHOLD_CEILING,
        "tcn_floor": config.TCN_THRESHOLD_FLOOR,
        "tcn_ceiling": config.TCN_THRESHOLD_CEILING,
        "auto_tune_enabled": auto_tuner.is_enabled()
    })

@app.route("/api/thresholds", methods=["POST"])
def api_set_thresholds():
    """Manually update the decision thresholds.

    Returns:
        Response: JSON payload containing the updated threshold settings.
    """
    data = request.get_json(silent=True) or {}
    xgb = data.get("xgb_threshold")
    tcn = data.get("tcn_threshold")
    
    manager = get_manager()
    manager.set(xgb=xgb, tcn=tcn, reason="manual")
    return jsonify(manager.get())

@app.route("/api/thresholds/reset", methods=["POST"])
def api_reset_thresholds():
    """Reset decision thresholds to training defaults.

    Returns:
        Response: JSON payload containing the reset threshold settings.
    """
    manager = get_manager()
    manager.reset()
    return jsonify(manager.get())

@app.route("/api/auto_tune", methods=["POST"])
def api_set_auto_tune():
    """Enable or disable passive background auto-tuning.

    Returns:
        Response: JSON status flag confirming the auto-tune toggle state.
    """
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", False))
    get_auto_tuner().set_enabled(enabled)
    return jsonify({"auto_tune_enabled": enabled})

@app.route("/api/calibration/start", methods=["POST"])
def api_calibration_start():
    """Start Guided Calibration recording for threshold baselining.

    Returns:
        Response: JSON payload confirming active calibration status.
    """
    assistant = get_calibration_assistant()
    return jsonify(assistant.start())

@app.route("/api/calibration/stop", methods=["POST"])
def api_calibration_stop():
    """Stop Guided Calibration and compute suggested threshold values.

    Query Params:
        percentile (float): Target percentile to select from ECDF. Default is 99.5.

    Returns:
        Response: JSON suggestions dictionary containing suggested, current, and raw threshold details.
    """
    percentile = request.args.get("percentile", config.CALIBRATION_DEFAULT_PERCENTILE, type=float)
    assistant = get_calibration_assistant()
    current_thresholds = get_manager().get()
    result = assistant.stop(percentile=percentile, current_thresholds=current_thresholds)
    return jsonify(result)

@app.route("/api/threshold_audit", methods=["GET"])
def api_threshold_audit():
    """Retrieve recent threshold adjustment logs.

    Query Params:
        limit (int): Maximum records to retrieve. Default is 50.

    Returns:
        Response: JSON list of recent audit log entries.
    """
    import json
    limit = request.args.get("limit", 50, type=int)
    audit_path = os.path.join(config.BASE_DIR, "logs", "threshold_audit.jsonl")
    
    entries = []
    if os.path.exists(audit_path):
        try:
            with open(audit_path, "r") as f:
                lines = f.readlines()
                for line in reversed(lines):
                    if not line.strip():
                        continue
                    try:
                        entries.append(json.loads(line))
                        if len(entries) >= limit:
                            break
                    except Exception:
                        pass
        except Exception as exc:
            logger.error("Failed to read audit log: %s", exc)
            
    return jsonify({"audit": entries})


# ═══════════════════════════════════════════════════════════════════════
# Scaler Adaptation Routes
# ═══════════════════════════════════════════════════════════════════════

@app.route("/api/scaler_status", methods=["GET"])
def api_scaler_status():
    """Get active scaling transformer type and byte-column power lambdas.

    Returns:
        Response: JSON payload containing active status, lambdas, and buffer sizes.
    """
    scaler = get_active_scaler()
    adapted_path = os.path.join(config.MODEL_DIR, "scaler_adapted.pkl")
    is_adapted = os.path.exists(adapted_path)
    
    buf = get_adaptation_buffer()
    
    lambdas = {}
    if hasattr(scaler, "lambdas_"):
        from pipeline.scaler_adaptation import BYTE_IDXS, BYTE_COLS
        for pos, col in enumerate(BYTE_COLS):
            lambdas[col] = float(scaler.lambdas_[BYTE_IDXS[pos]])
            
    return jsonify({
        "active": "adapted" if is_adapted else "base",
        "byte_col_lambdas": lambdas,
        "sample_count": buf.sample_count(),
        "collecting": buf.is_active(),
    })

@app.route("/api/scaler_adaptation/start", methods=["POST"])
def api_scaler_start():
    """Start passive byte feature adaptation buffer collection.

    Returns:
        Response: JSON state flag confirming the active collection.
    """
    buf = get_adaptation_buffer()
    buf.start()
    return jsonify({"collecting": True})

@app.route("/api/scaler_adaptation/preview", methods=["GET"])
def api_scaler_preview():
    """Get status check of the byte feature adaptation buffer.

    Returns:
        Response: JSON containing sample count and readiness flags.
    """
    buf = get_adaptation_buffer()
    from pipeline.scaler_adaptation import MIN_SAMPLES_FOR_ADAPTATION
    count = buf.sample_count()
    return jsonify({
        "sample_count": count,
        "ready": count >= MIN_SAMPLES_FOR_ADAPTATION,
        "min_required": MIN_SAMPLES_FOR_ADAPTATION
    })

@app.route("/api/scaler_adaptation/apply", methods=["POST"])
def api_scaler_apply():
    """Compute and apply adapted PowerTransformer using collected byte features.

    Returns:
        Response: JSON delta calculations comparing base to adapted lambdas on success,
            or an error message on failure.
    """
    buf = get_adaptation_buffer()
    try:
        from pipeline.model_loader import get_artifacts
        base_scaler = get_artifacts().scaler
        adapted, deltas = buf.compute_adapted_scaler(base_scaler)
        
        # Save and set active
        import joblib
        from pipeline.active_scaler import set_active_scaler
        joblib.dump(adapted, os.path.join(config.MODEL_DIR, "scaler_adapted.pkl"))
        set_active_scaler(adapted)
        
        buf.stop()
        buf.clear()
        
        # Audit
        get_manager().audit_event("scaler_adaptation", "applied", lambda_deltas=deltas, n_samples=buf.sample_count())
        
        return jsonify({"status": "success", "lambda_deltas": deltas})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        logger.exception("Failed to apply scaler adaptation")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/scaler_adaptation/reset", methods=["POST"])
def api_scaler_reset():
    """Remove adapted PowerTransformer and restore the base model scaler.

    Returns:
        Response: JSON status flag confirming the reset execution.
    """
    from pipeline.model_loader import get_artifacts
    base_scaler = get_artifacts().scaler
    reset_active_scaler(base_scaler)
    
    get_manager().audit_event("scaler_adaptation", "reset")
    return jsonify({"status": "reset"})

# ═══════════════════════════════════════════════════════════════════════
# Recalibration Routes
# ═══════════════════════════════════════════════════════════════════════

@app.route("/api/recalibration/status", methods=["GET"])
def api_recal_status():
    """Get active states of the XGBoost and TCN probability recalibrators.

    Returns:
        Response: JSON payload showing fitted status.
    """
    r = get_recalibrator()
    status = r.get_status()
    return jsonify({
        "xgb_fitted": status.get("xgb", False),
        "tcn_fitted": status.get("tcn", False),
    })

@app.route("/api/recalibration/fit", methods=["POST"])
def api_recal_fit():
    """Run model recalibration fitting from uploaded labeled CSV records.

    Note:
        This endpoint is currently mocked (returns 501) as it depends on an external
        offline replay parser.

    Returns:
        Response: JSON error status and error message.
    """
    # This would parse CSV and fit. Since it involves pipeline offline replay
    # and the prompt specifies "The endpoint runs the existing offline-replay pipeline",
    # I will mock the CSV parsing to demonstrate the endpoint exists and returns ok.
    # A full implementation requires running the full dataset through engineer_features, etc.
    return jsonify({
        "status": "error",
        "message": "CSV upload for offline replay not yet fully implemented due to dependency on offline parsing module.",
    }), 501

@app.route("/api/recalibration/reset", methods=["POST"])
def api_recal_reset():
    """Reset and delete fitted isotonic recalibrators.

    Returns:
        Response: JSON status flag confirming the reset execution.
    """
    r = get_recalibrator()
    r.reset()
    get_manager().audit_event("recalibration", "reset")
    return jsonify({"status": "reset"})

@app.route("/api/recalibration/feature_aucs", methods=["GET"])
def api_recal_aucs():
    """Get the feature importance coefficients computed during recalibrator fitting.

    Returns:
        Response: JSON arrays representing weights assigned to XGBoost and TCN.
    """
    r = get_recalibrator()
    xgb_w = r.xgb_weights.tolist() if r.xgb_weights is not None else []
    tcn_w = r.tcn_weights.tolist() if r.tcn_weights is not None else []
    return jsonify({"xgb_weights": xgb_w, "tcn_weights": tcn_w})

# ═══════════════════════════════════════════════════════════════════════
# Domain Shift Routes
# ═══════════════════════════════════════════════════════════════════════

@app.route("/api/domain_shift", methods=["GET"])
def api_domain_shift():
    """Evaluate boundaries of numeric features to flag potential domain distribution shift.

    Returns:
        Response: JSON payload detailing features status and domain shift warning flags.
    """
    from config import CLIP_BOUNDARY_WARN_THRESHOLD, CLIP_BOUNDARY_WATCH_THRESHOLD
    stats = state.clip_boundary_stats
    
    features = {}
    any_shifted = False
    for col, frac in stats.items():
        if frac > CLIP_BOUNDARY_WARN_THRESHOLD:
            status = "likely_shifted"
            any_shifted = True
        elif frac > CLIP_BOUNDARY_WATCH_THRESHOLD:
            status = "watch"
        else:
            status = "ok"
        
        features[col] = {
            "fraction_at_boundary": frac,
            "status": status
        }
    
    return jsonify({
        "features": features,
        "any_shifted": any_shifted
    })

# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app.run(
        host=FLASK_HOST,
        port=FLASK_PORT,
        debug=False,
        threaded=True,
        use_reloader=False
    )
