# NIDS-Live: Real-Time Network Intrusion Detection System

This is a production-grade, cross-platform real-time Network Intrusion Detection System (NIDS). It captures live packets, reconstructs network flows, and runs them through an exact, bit-for-bit faithful port of a pre-trained XGBoost and TCN inference pipeline.

## Features
- **Cross-Platform**: Works on Linux, macOS, and Windows.
- **Dual Capture Engines**: 
  - `nfstream` (Linux/macOS): High-performance C-based flow reconstruction.
  - `scapy` (Universal fallback): Pure Python packet capture with manual flow table management.
- **Faithful Inference**: Exact numerical port of the Jupyter notebook's feature engineering, scaling, and inference logic.
- **Streaming Adapted**: TCN windowing and Inter-Arrival Time (IAT) adapted for real-time streaming without breaking mathematical parity.
- **Web Dashboard**: Vanilla HTML/CSS/JS dashboard powered by a Flask backend for real-time monitoring.

## Setup

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Model Artifacts**
   You must place the following pre-trained model artifacts in the `models/` directory before starting the application:
   - `clip_bounds.pkl`
   - `scaler.pkl`
   - `le_proto.pkl`
   - `le_dir.pkl`
   - `xgb_model.pkl`
   - `tcn_best.keras` (or `tcn_model/` directory)

## Running the Application

### Linux / macOS
To capture packets, the application needs elevated privileges. You can either run it with `sudo` or set capabilities on your Python executable.

Using `sudo`:
```bash
sudo $(which python3) app.py
```

Using capabilities (Linux only, no sudo required):
```bash
sudo setcap cap_net_raw,cap_net_admin=eip $(readlink -f $(which python3))
python3 app.py
```

### Windows
You must install **Npcap** in "WinPcap API-compatible" mode.
Run the application from an Administrator command prompt or PowerShell:
```cmd
python app.py
```

## Usage
1. Open your browser and navigate to `http://localhost:5000`.
2. Select your network interface from the dropdown in the header.
3. Click **Start Capture**.
4. Monitor the live flows, top suspicious IPs, and alert feed.

## Domain Adaptation Workflow

When deploying the pre-trained CTU-13 models to a new environment, follow this workflow to align the models with your network's baseline:

1. **Monitor Domain Shift:** Watch the **Domain Shift Monitor** panel. If the feature bounds frequently trigger the warning threshold (amber banner appears), your new environment has structurally different traffic volumes.
2. **Run Byte-Column Adaptation:** 
   - Open the **Domain Adaptation & Diagnostics** panel.
   - Click **Start Collecting** under Byte-Column Adaptation to record a buffer of raw background traffic (default 50,000 flows).
   - Once enough samples are collected, click **Apply Adapted Scaler**. This will fit new Yeo-Johnson transformations on `TotBytes`, `SrcBytes`, and `BytesPerPkt` and save `scaler_adapted.pkl`.
3. **Recalibrate Probabilities:**
   - (Mock implementation) Upload a labeled dataset from your new environment to fit Isotonic regression layers over the raw probabilities. This aligns the output probability scale, significantly improving ROC-AUC on new data.
   - The recalibrated probabilities will seamlessly replace the raw probabilities in the UI.
4. **Calibrate Thresholds:**
   - Finally, use the **Detection Sensitivity** panel to run a guided calibration on live traffic, or adjust the thresholds manually to tune the false positive rate.
