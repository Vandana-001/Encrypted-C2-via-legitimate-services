# API Reference Manual

This document details all REST API endpoints registered in the NIDS-Live Flask application (`app.py`). All API payloads and responses are formatted as JSON.

---

## 1. General Routes

### GET `/`
Renders the primary web dashboard.
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X GET http://localhost:5000/
  ```

---

## 2. Capture Engine & Status Control

### GET `/api/interfaces`
Lists all available network interfaces on the host system.
* **Response JSON**:
  ```json
  {
    "interfaces": ["eth0", "wlan0", "lo"]
  }
  ```
* **Status Codes**: `200 OK`, `500 Internal Server Error` (if enumeration fails)
* **Curl Example**:
  ```bash
  curl -X GET http://localhost:5000/api/interfaces
  ```

---

### POST `/api/start`
Starts packet capture and the background pipeline.
* **Request JSON Body**:
  * `interface` (string, required): The NIC name.
  * `engine` (string, optional): Engine to use (`auto`, `nfstream`, or `scapy`). Defaults to `auto`.
* **Response JSON**:
  ```json
  {
    "status": "running",
    "engine": "nfstream"
  }
  ```
* **Status Codes**:
  * `200 OK`: Capture started successfully.
  * `400 Bad Request`: Missing interface or capture is already running.
  * `500 Internal Server Error`: Models not loaded, permission error, or engine startup failed.
* **Curl Example**:
  ```bash
  curl -X POST http://localhost:5000/api/start \
    -H "Content-Type: application/json" \
    -d '{"interface": "eth0", "engine": "auto"}'
  ```

---

### POST `/api/stop`
Stops the capture loop and background processing threads.
* **Response JSON**:
  ```json
  {
    "status": "stopped"
  }
  ```
* **Status Codes**: `200 OK`, `500 Internal Server Error` (if joining thread fails)
* **Curl Example**:
  ```bash
  curl -X POST http://localhost:5000/api/stop
  ```

---

### GET `/api/status`
Returns live state variables, engine type, uptime, and classification statistics.
* **Response JSON**:
  ```json
  {
    "status": "running",
    "engine": "nfstream",
    "uptime_sec": 42.5,
    "total_flows": 1250,
    "total_packets": 48200,
    "xgb_alerts": 5,
    "tcn_alerts": 2,
    "last_error": "",
    "model_error": ""
  }
  ```
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X GET http://localhost:5000/api/status
  ```

---

## 3. Data Query Routes

### GET `/api/flows`
Returns a list of the most recent classification flow records.
* **Query Parameters**:
  * `limit` (integer, optional): Maximum records to return. Defaults to `50`.
* **Response JSON**:
  ```json
  {
    "flows": [
      {
        "timestamp": "2026-06-19T12:00:00.000Z",
        "SrcAddr": "192.168.1.10",
        "DstAddr": "8.8.8.8",
        "Proto": "tcp",
        "xgb_prob": 0.0125,
        "xgb_prob_recal": 0.0125,
        "xgb_alert": 0,
        "xgb_threshold": 0.2,
        "tcn_prob": 0.0051,
        "tcn_prob_recal": 0.0051,
        "tcn_alert": 0,
        "tcn_threshold": 0.022
      }
    ]
  }
  ```
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X GET http://localhost:5000/api/flows?limit=10
  ```

---

### GET `/api/alerts`
Returns classification records where `xgb_alert == 1` or `tcn_alert == 1`.
* **Query Parameters**:
  * `limit` (integer, optional): Maximum records to return. Defaults to `50`.
* **Response JSON**: shape matches `/api/flows`.
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X GET http://localhost:5000/api/alerts?limit=5
  ```

---

### GET `/api/top_ips`
Returns the source IPs sorted in descending order by maximum model score.
* **Query Parameters**:
  * `limit` (integer, optional): Maximum rows to return. Defaults to `10`.
* **Response JSON**:
  ```json
  {
    "top_ips": [
      {
        "SrcAddr": "192.168.1.155",
        "xgb_max_prob": 0.7891,
        "tcn_max_prob": 0.0452,
        "xgb_alert_count": 8,
        "tcn_alert_count": 1,
        "total_flows": 120
      }
    ]
  }
  ```
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X GET http://localhost:5000/api/top_ips?limit=3
  ```

---

## 4. Threshold & Tuning Routes

### GET `/api/thresholds`
Returns active thresholds, bounds, and auto-tuner state.
* **Response JSON**:
  ```json
  {
    "xgb_threshold": 0.2079,
    "tcn_threshold": 0.1,
    "xgb_default": 0.2,
    "tcn_default": 0.022,
    "xgb_floor": 0.1,
    "xgb_ceiling": 0.6,
    "tcn_floor": 0.01,
    "tcn_ceiling": 0.1,
    "auto_tune_enabled": false
  }
  ```
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X GET http://localhost:5000/api/thresholds
  ```

---

### POST `/api/thresholds`
Manually updates the active classification thresholds.
* **Request JSON Body**:
  * `xgb_threshold` (float, optional): New threshold for XGBoost.
  * `tcn_threshold` (float, optional): New threshold for TCN.
* **Response JSON**: returns the updated JSON object containing both thresholds (matches GET `/api/thresholds` structure).
* **Status Codes**: `200 OK` (threshold values are internally clipped to their respective bounds)
* **Curl Example**:
  ```bash
  curl -X POST http://localhost:5000/api/thresholds \
    -H "Content-Type: application/json" \
    -d '{"xgb_threshold": 0.25, "tcn_threshold": 0.05}'
  ```

---

### POST `/api/thresholds/reset`
Resets classification thresholds to their default values (`xgb=0.2`, `tcn=0.022`).
* **Response JSON**: shape matches `/api/thresholds`.
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X POST http://localhost:5000/api/thresholds/reset
  ```

---

### POST `/api/auto_tune`
Enables or disables continuous auto-tuning.
* **Request JSON Body**:
  * `enabled` (boolean, required): Auto-tuner status.
* **Response JSON**:
  ```json
  {
    "auto_tune_enabled": true
  }
  ```
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X POST http://localhost:5000/api/auto_tune \
    -H "Content-Type: application/json" \
    -d '{"enabled": true}'
  ```

---

### POST `/api/calibration/start`
Starts a guided calibration recording window to baseline the current network.
* **Response JSON**:
  ```json
  {
    "calibrating": true,
    "started_at": "2026-06-19T12:05:00.000Z"
  }
  ```
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X POST http://localhost:5000/api/calibration/start
  ```

---

### POST `/api/calibration/stop`
Stops the calibration assistant and computes suggested threshold percentiles.
* **Query Parameters**:
  * `percentile` (float, optional): The target percentile. Defaults to `99.5`.
* **Response JSON**:
  ```json
  {
    "n_samples": 450,
    "percentile": 99.5,
    "suggestions": {
      "xgb": {
        "suggested": 0.285,
        "raw": 0.2845,
        "current": 0.2,
        "histogram": {
          "bins": [0.01, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5],
          "counts": [100, 200, 80, 40, 20, 5, 3, 2, 0, 0]
        }
      },
      "tcn": { ... }
    }
  }
  ```
* **Status Codes**: `200 OK`, `400 Bad Request` (if not currently calibrating or if no samples were recorded)
* **Curl Example**:
  ```bash
  curl -X POST http://localhost:5000/api/calibration/stop?percentile=99.0
  ```

---

### GET `/api/threshold_audit`
Retrieves events logged in the threshold audit log.
* **Query Parameters**:
  * `limit` (integer, optional): Maximum log lines to return. Defaults to `50`.
* **Response JSON**:
  ```json
  {
    "audit": [
      {
        "ts": "2026-06-19T12:00:00.000Z",
        "component": "threshold",
        "model": "xgb",
        "old": 0.2,
        "new": 0.25,
        "reason": "manual"
      }
    ]
  }
  ```
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X GET http://localhost:5000/api/threshold_audit?limit=10
  ```

---

## 5. Domain Adaptation & recalibration

### GET `/api/scaler_status`
Returns active scaler status, fitted byte-column lambdas, and collecting buffers.
* **Response JSON**:
  ```json
  {
    "active": "base",
    "byte_col_lambdas": {
      "TotBytes": -0.125,
      "SrcBytes": 0.045,
      "BytesPerPkt": 0.85
    },
    "sample_count": 420,
    "collecting": false
  }
  ```
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X GET http://localhost:5000/api/scaler_status
  ```

---

### POST `/api/scaler_adaptation/start`
Starts collecting raw flow bytes for fitting adapted lambdas.
* **Response JSON**:
  ```json
  {
    "collecting": true
  }
  ```
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X POST http://localhost:5000/api/scaler_adaptation/start
  ```

---

### GET `/api/scaler_adaptation/preview`
Checks collecting buffer statistics.
* **Response JSON**:
  ```json
  {
    "sample_count": 52100,
    "ready": true,
    "min_required": 50000
  }
  ```
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X GET http://localhost:5000/api/scaler_adaptation/preview
  ```

---

### POST `/api/scaler_adaptation/apply`
Fits Yeo-Johnson PowerTransformer to collected data and saves it to `models/scaler_adapted.pkl`.
* **Response JSON**:
  ```json
  {
    "status": "success",
    "lambda_deltas": {
      "TotBytes": { "original": -0.12, "adapted": -0.15 }
    }
  }
  ```
* **Status Codes**:
  * `200 OK`: Adaptation successfully computed and applied.
  * `400 Bad Request`: Insufficient samples (under 50,000).
  * `500 Internal Server Error`: Processing failure during fit.
* **Curl Example**:
  ```bash
  curl -X POST http://localhost:5000/api/scaler_adaptation/apply
  ```

---

### POST `/api/scaler_adaptation/reset`
Removes `models/scaler_adapted.pkl` and restores the base scaler.
* **Response JSON**:
  ```json
  {
    "status": "reset"
  }
  ```
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X POST http://localhost:5000/api/scaler_adaptation/reset
  ```

---

### GET `/api/recalibration/status`
Returns fitted states of XGBoost and TCN isotonic recalibration layers.
* **Response JSON**:
  ```json
  {
    "xgb_fitted": true,
    "tcn_fitted": false
  }
  ```
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X GET http://localhost:5000/api/recalibration/status
  ```

---

### POST `/api/recalibration/fit`
**Unimplemented Endpoint**: Triggers CSV upload offline-replay pipeline.
* **Status Codes**: `501 Not Implemented`
* **Response JSON**:
  ```json
  {
    "status": "error",
    "message": "CSV upload for offline replay not yet fully implemented due to dependency on offline parsing module."
  }
  ```
* **Curl Example**:
  ```bash
  curl -X POST http://localhost:5000/api/recalibration/fit
  ```

---

### POST `/api/recalibration/reset`
Deletes fitted recalibrators (`recal_xgb.pkl` and `recal_tcn.pkl`) and resets state.
* **Response JSON**:
  ```json
  {
    "status": "reset"
  }
  ```
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X POST http://localhost:5000/api/recalibration/reset
  ```

---

### GET `/api/recalibration/feature_aucs`
Returns the weights assigned to each base feature in recalibration.
* **Response JSON**:
  ```json
  {
    "xgb_weights": [0.05, 0.1, 0.0, 0.25, 0.1, 0.1, 0.3, 0.1],
    "tcn_weights": []
  }
  ```
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X GET http://localhost:5000/api/recalibration/feature_aucs
  ```

---

### GET `/api/domain_shift`
Returns passive diagnostics monitoring boundary clipping percentage on base features.
* **Response JSON**:
  ```json
  {
    "features": {
      "TotBytes": {
        "fraction_at_boundary": 0.051,
        "status": "watch"
      },
      "Dur": {
        "fraction_at_boundary": 0.125,
        "status": "likely_shifted"
      }
    },
    "any_shifted": true
  }
  ```
* **Status Codes**: `200 OK`
* **Curl Example**:
  ```bash
  curl -X GET http://localhost:5000/api/domain_shift
  ```
