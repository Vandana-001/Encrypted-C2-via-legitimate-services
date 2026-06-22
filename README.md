# Encrypted C2 via Legitimate Services Detection

**Independent XGBoost + TCN Botnet Detection, from Offline Training to Live Deployment**

NIDS-Live is a production-grade, cross-platform network intrusion detection system that analyzes live network traffic and performs low-latency, flow-based anomaly detection. It is the deployment layer for a dual-model detection pipeline trained on the CTU-13 botnet dataset: an **XGBoost** classifier for per-flow statistical detection and a **Temporal Convolutional Network (TCN)** for sequence-based detection of beaconing and other temporal patterns.

The two models are **not ensembled**. They run, score, and report independently end-to-end — from offline training and evaluation through to live inference and dashboard alerting — so each model's behavior and detection profile can be inspected on its own rather than masked behind a fused score.

---

## 1. System Overview

NIDS-Live bridges the gap between offline model training and real-time operations by providing:

* **Dual-Engine Packet Capture** — automatic OS-specific selection of C-based `nfstream` (for high-throughput Linux/macOS capture) or `scapy` (as a fallback or for Windows).
* **Parity Inference** — complete mathematical alignment with training-notebook logic, including Yeo-Johnson transforms, feature clipping, and categorical encodings, so live scores match offline evaluation.
* **TCN Sequence Windowing** — an IP-based rolling queue that tracks sequence history and applies cyclic padding to enable early sequential inference before a full window of history has been captured.
* **Domain Adaptation Pipeline** — diagnostic metrics that alert operators to distribution shift, with built-in mechanisms to adapt scalers (Yeo-Johnson lambdas) and recalibrate prediction probabilities for new network environments.
* **Independent Model Reporting** — XGBoost and TCN predictions, thresholds, and alerts are tracked and surfaced separately throughout the pipeline; no ensembling, stacking, or score fusion is performed at any stage.
* **Interactive Control Room** — a single-page dashboard containing live flow tables, security alert feeds, manual sensitivity controls, calibration tools, and threshold audit logs.

---

## 2. Project Components

| Component | Description |
|---|---|
| **Offline training pipeline** (notebooks) | CTU-13 chunked loading, feature engineering, source-IP-disjoint splitting, independent XGBoost and TCN training with HDF5-streamed sequences. |
| **Cross-dataset inference pipeline** (notebooks) | Applies both trained models to CICIDS-2017 with domain recalibration (logistic + isotonic), reporting XGBoost and TCN results separately. |
| **NIDS-Live** (this repository) | Live packet capture, real-time feature parity inference, and dashboard for both models in production. |

---

## 3. Directory Structure

```text
nids-live/
├── app.py                      # Flask web server, REST API endpoints, and background thread controllers
├── config.py                   # Global parameters (features, thresholds, timer intervals)
├── requirements.txt            # Python dependency specifications
├── README.md                   # This file
├── CHANGELOG.md                # Version release records
│
├── capture/                    # Packet capture and flow reconstruction engines
│   ├── __init__.py
│   ├── base.py                 # Base CaptureEngine class definition
│   ├── interfaces.py           # Auto-engine selection function
│   ├── nfstream_engine.py      # NFStream implementation (Linux/macOS)
│   └── scapy_engine.py         # Scapy implementation with custom flow-table
│
├── pipeline/                   # Inference, scaling, and thresholding modules
│   ├── __init__.py
│   ├── active_scaler.py        # Wrapper for managing base vs. adapted scalers
│   ├── auto_tuner.py           # Background thread for threshold auto-tuning
│   ├── calibration.py          # Baseline calibration routine
│   ├── feature_engineering.py  # Port categorization and ratio calculations
│   ├── model_loader.py         # Singleton loaders for pickled/keras models
│   ├── orchestrator.py         # Orchestrates capture queue consumption & inference
│   ├── recalibration.py        # Fits isotonic regression to raw probabilities
│   ├── scaler_adaptation.py    # Refits Yeo-Johnson lambdas on byte columns
│   ├── scaling.py               # Applies PowerTransformer and feature clipping
│   ├── state.py                # Shared thread-safe runtime state
│   ├── tcn_inference.py        # Rolling sequences and TCN inference
│   ├── threshold_manager.py    # Persists and audits classification thresholds
│   └── xgb_inference.py        # Augments interactions and runs XGBoost inference
│
├── models/                     # Model binaries (operator must supply these)
│   ├── clip_bounds.pkl
│   ├── le_dir.pkl
│   ├── le_proto.pkl
│   ├── runtime_thresholds.json
│   ├── scaler.pkl
│   ├── tcn_best.keras
│   ├── win_scaler.pkl
│   └── xgb_model.pkl
│
├── logs/                       # Log files
│   └── threshold_audit.jsonl   # JSON Lines log of threshold changes
│
├── templates/
│   └── index.html              # Dashboard template
└── static/
    ├── css/
    │   └── style.css           # Dashboard styling
    └── js/
        └── app.js              # API polling and dashboard interaction
```

---

## 4. Why Two Independent Models, Not an Ensemble

During offline development, a stacked ensemble (logistic regression meta-learner over XGBoost and TCN probability outputs) was evaluated and produced substantially **worse** results than either model alone — the two models score structurally different, only partially overlapping populations (per-flow vs. per-sequence), and a meta-learner trained on the small aligned intersection failed to generalize. NIDS-Live carries this finding through to production: the live pipeline runs both models in parallel, applies independent thresholds and calibration to each, and surfaces both detection streams separately on the dashboard rather than fusing them into a single score.

---

## 5. Installation and Setup

### Prerequisites
* Python 3.8 – 3.11
* OS-specific packet capture privileges
* Pre-trained model files placed in `models/` (see [MODELS.md](docs/MODELS.md))

### Installation Steps

1. **Clone the repository**

   ```bash
   git clone <repository-url>
   cd nids-live
   ```

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

   > **Note:** On Linux/macOS, if you plan to use `nfstream`, ensure compile tools are available (`sudo apt install build-essential python3-dev` on Ubuntu).

---

## 6. Running the Application

### 1. Elevated Privileges (Required for Capture)

Opening raw network sockets requires specific permissions:

#### Linux / macOS (Capabilities or Sudo)

* **Option A — Sudo** (quickest):

  ```bash
  sudo $(which python3) app.py
  ```

* **Option B — Capabilities** (recommended, Linux only):

  ```bash
  sudo setcap cap_net_raw,cap_net_admin=eip $(readlink -f $(which python3))
  python3 app.py
  ```

#### Windows

1. Install **Npcap** in "WinPcap API-compatible" mode.
2. Open an **Administrator** command prompt or PowerShell window.
3. Run the application:

   ```cmd
   python app.py
   ```

### 2. Accessing the Dashboard

Once the console prints `✅ Application ready.`, navigate to:

```text
http://localhost:5000
```

Select the network interface, choose the capture engine (`auto`, `nfstream`, or `scapy`), and click **Start Capture** to begin real-time analysis. XGBoost and TCN alerts appear as separate, independently labeled streams.

---

## 7. Detailed Technical Documentation

For deeper configuration and architecture details, refer to the following documents in the `docs/` directory:

1. [Architecture Design Guide](docs/ARCHITECTURE.md) — Threading model, parallel inference path, and Mermaid flow diagrams.
2. [Feature Engineering Guide](docs/FEATURE_ENGINEERING.md) — Detailed feature calculations, port categorization, scaling, and XGBoost/TCN features.
3. [Model Artifacts Directory](docs/MODELS.md) — Specification of the 7 model files, expected input shapes, and load routines.
4. [Capture Engines Reference](docs/CAPTURE_ENGINES.md) — Inner workings of Scapy and NFStream capture modules, common schemas, and timeouts.
5. [API Reference Manual](docs/API_REFERENCE.md) — Routes, query parameters, JSON payload structures, and curl commands.
6. [Threshold Management Guide](docs/THRESHOLDS.md) — Sliding controls, guided baseline calibration, auto-tuning, and audit logs.
7. [Configuration Reference Manual](docs/CONFIGURATION.md) — Parameters defined in `config.py`.
8. [Troubleshooting Guide](docs/TROUBLESHOOTING.md) — Symptom-cause-fix guides for common runtime errors.
9. [Known Issues & Gaps](docs/KNOWN_ISSUES.md) — Documented gaps, stubs, and mathematical constraints.

---

## 8. Related Work / Offline Pipeline

The model artifacts consumed by NIDS-Live (`xgb_model.pkl`, `tcn_best.keras`, `scaler.pkl`, `win_scaler.pkl`, etc.) are produced by a separate offline training pipeline trained on the CTU-13 dataset, with cross-dataset validation on CICIDS-2017. See the accompanying project report for full methodology, architecture details, and evaluation results for both models.
