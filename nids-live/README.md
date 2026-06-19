# NIDS-Live: Real-Time Network Intrusion Detection System

NIDS-Live is a production-grade, cross-platform network intrusion detection system designed to analyze live network traffic and perform low-latency anomaly detection. The system integrates machine learning inference using XGBoost and Temporal Convolutional Networks (TCN) with a robust background packet capture pipeline and a premium web-based dashboard.

---

## 1. System Overview

NIDS-Live bridges the gap between offline model training and real-time operations by providing:
* **Dual-Engine Packet Capture**: Automatic OS-specific selection of C-based `nfstream` (for high-throughput Linux/macOS capture) or `scapy` (as a fallback or for Windows).
* **Parity Inference**: Complete mathematical alignment with training notebook logic, including Yeo-Johnson transforms, feature clipping, and categorical category encodings.
* **TCN Sequence Windowing**: An IP-based rolling queue that tracks sequence history and applies cyclic padding to enable early sequential inference before a full history is captured.
* **Domain Adaptation Pipeline**: Diagnostic metrics that alert operators to distribution shifts, with built-in mechanisms to adapt scalers (Yeo-Johnson lambdas) and recalibrate prediction probabilities.
* **Interactive Control Room**: A single-page dashboard containing live flow tables, security alert feeds, manual sensitivity controls, calibration tools, and threshold audit logs.

---

## 2. Directory Structure

Below is the layout of the NIDS-Live repository:

```text
nids-live/
├── app.py                     # Flask web server, REST API endpoints, and background thread controllers
├── config.py                  # Global parameters (features, thresholds, timer intervals)
├── requirements.txt           # Python dependency specifications
├── README.md                  # This file
├── CHANGELOG.md               # Version release records
│
├── capture/                   # Packet capture and flow reconstruction engines
│   ├── __init__.py
│   ├── base.py                # Base CaptureEngine class definition
│   ├── interfaces.py          # Auto-engine selection function
│   ├── nfstream_engine.py     # NFStream implementation (Linux/macOS)
│   └── scapy_engine.py        # Scapy implementation with custom flow-table
│
├── pipeline/                  # Inference, scaling, and thresholding modules
│   ├── __init__.py
│   ├── active_scaler.py       # Wrapper for managing base vs. adapted scalers
│   ├── auto_tuner.py          # Background thread for threshold auto-tuning
│   ├── calibration.py         # Baseline calibration routine
│   ├── feature_engineering.py  # Port categorization and ratio calculations
│   ├── model_loader.py        # Singleton loaders for pickled/keras models
│   ├── orchestrator.py        # Orchestrates capture queue consumption & inference
│   ├── recalibration.py       # Fits Isotonic regression to raw probabilities
│   ├── scaler_adaptation.py   # Refits Yeo-Johnson lambdas on byte columns
│   ├── scaling.py             # Applies PowerTransformer and feature clipping
│   ├── state.py               # Shared thread-safe runtime state
│   ├── tcn_inference.py       # Rolling sequences and TCN inference
│   ├── threshold_manager.py   # Persists and audits classification thresholds
│   └── xgb_inference.py       # Augments interactions and runs XGBoost inference
│
├── models/                    # Model binaries (Operator must supply these)
│   ├── clip_bounds.pkl
│   ├── le_dir.pkl
│   ├── le_proto.pkl
│   ├── runtime_thresholds.json
│   ├── scaler.pkl
│   ├── tcn_best.keras
│   ├── win_scaler.pkl
│   └── xgb_model.pkl
│
├── logs/                      # Log files
│   └── threshold_audit.jsonl  # JSON Lines log of threshold changes
│
├── templates/
│   └── index.html             # Dashboard template
└── static/
    ├── css/
    │   └── style.css          # Dashboard styling
    └── js/
        └── app.js             # API polling and dashboard interaction
```

---

## 3. Installation and Setup

### Prerequisites
* Python 3.8 to 3.11.
* OS-specific packet capture privileges.
* Pre-trained model files placed in `models/` (refer to [MODELS.md](file:///home/gokul-p/Project/Vandana_E2/pipeline/nids-live/docs/MODELS.md) for details).

### Installation Steps
1. **Clone the Repository**:
   Navigate to the repository directory.
2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   *Note: On Linux/macOS, if you plan to use `nfstream`, ensure compile tools are available (`sudo apt install build-essential python3-dev` on Ubuntu).*

---

## 4. Running the Application

### 1. Elevated Privileges (Required for Capture)
Because opening raw network sockets requires specific permissions, configure your environment accordingly:

#### Linux / macOS (Capabilities or Sudo)
* **Option A: Sudo** (Quickest):
  ```bash
  sudo $(which python3) app.py
  ```
* **Option B: Capabilities** (Recommended, Linux only):
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
Select the network interface, choose the capture engine (`auto`, `nfstream`, or `scapy`), and click **Start Capture** to begin real-time analysis.

---

## 5. Detailed Technical Documentation

For deeper configuration and architecture details, refer to the following documents in the `docs/` directory:

1. [Architecture Design Guide](file:///home/gokul-p/Project/Vandana_E2/pipeline/nids-live/docs/ARCHITECTURE.md) — Threading model, parallel inference path, and Mermaid flow diagrams.
2. [Feature Engineering Guide](file:///home/gokul-p/Project/Vandana_E2/pipeline/nids-live/docs/FEATURE_ENGINEERING.md) — Detailed feature calculations, port categorization, scaling, and XGBoost/TCN features.
3. [Model Artifacts Directory](file:///home/gokul-p/Project/Vandana_E2/pipeline/nids-live/docs/MODELS.md) — Specification of the 7 model files, expected input shapes, and load routines.
4. [Capture Engines Reference](file:///home/gokul-p/Project/Vandana_E2/pipeline/nids-live/docs/CAPTURE_ENGINES.md) — Inner workings of Scapy and NFStream capture modules, common schemas, and timeouts.
5. [API Reference Manual](file:///home/gokul-p/Project/Vandana_E2/pipeline/nids-live/docs/API_REFERENCE.md) — Routes, query parameters, JSON payload structures, and curl commands.
6. [Threshold Management Guide](file:///home/gokul-p/Project/Vandana_E2/pipeline/nids-live/docs/THRESHOLDS.md) — Sliding controls, guided baseline calibration, auto-tuning, and audit logs.
7. [Configuration Reference Manual](file:///home/gokul-p/Project/Vandana_E2/pipeline/nids-live/docs/CONFIGURATION.md) — Parameters defined in `config.py`.
8. [Troubleshooting Guide](file:///home/gokul-p/Project/Vandana_E2/pipeline/nids-live/docs/TROUBLESHOOTING.md) — Symptom-cause-fix guides for common runtime errors.
9. [Known Issues & Gaps](file:///home/gokul-p/Project/Vandana_E2/pipeline/nids-live/docs/KNOWN_ISSUES.md) — Documented gaps, stubs, and mathematical constraints.
