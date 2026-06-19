# Troubleshooting Guide

This guide describes how to identify, diagnose, and resolve common runtime errors and deployment issues in the NIDS-Live application.

---

## Symptom-Cause-Fix Reference Table

| Symptom | Probable Cause | Diagnostic / Verification Steps | Resolution / Fix |
| :--- | :--- | :--- | :--- |
| **"Permission denied opening interface"** on starting capture | The Python process lacks administrative rights to open raw packet capture sockets. | Check the error message in the status bar or the console log on `POST /api/start`. | **Linux**: Run with `sudo` or grant capabilities:<br>`sudo setcap cap_net_raw,cap_net_admin=eip $(readlink -f $(which python3))`<br>**Windows**: Run command prompt as Administrator.<br>**macOS**: Grant read/write permissions to `/dev/bpf*`. |
| **"Missing model artifacts in models/"** error on startup | One or more of the seven required model binaries (`.pkl`, `.keras`) are missing from the `models/` directory. | Check `model_status-grid` at the bottom of the diagnostics panel or check console logs. | Ensure all 7 files are located in `models/` (refer to [MODELS.md](file:///home/gokul-p/Project/Vandana_E2/pipeline/nids-live/docs/MODELS.md)). Keep the original names exactly as trained. |
| **Flask fails to start**: `"Address already in use"` | Another application or an orphaned Flask server is listening on port `5000`. | Run `sudo lsof -i :5000` or `netstat -ano \| findstr 5000`. | Terminate the occupying process: `kill -9 <PID>`, or change the port in `config.py` (`FLASK_PORT = 5001`). |
| **Dashboard fails to list interfaces** or capture fails immediately | Invalid or down network interface name passed to the start call. | Execute `ip link show` (Linux/macOS) or `ipconfig` (Windows) to verify if the NIC is active. | Select a valid, active interface from the dashboard dropdown. Ensure the interface has a status of `UP`. |
| **Dashboard sluggish or browser freezing** over time | DOM overload due to displaying too many live flow rows or alert cards. | Open browser developer tools and check the DOM node count in the live flow table. | The frontend limits displays to `30` rows/cards. If custom adjustments increased `MAX_FLOW_ROWS` or `MAX_ALERT_CARDS` in `static/js/app.js`, restore them to default levels. |
| **"No module named 'nfstream'"** or compilation failures during install | `nfstream` compilation requires a C compiler and development headers, or the platform is Windows (unsupported). | Verify if `gcc` or `make` are installed. Check if the host OS is Windows. | **Linux/macOS**: Install compilation dependencies:<br>`sudo apt install build-essential python3-dev` (Debian/Ubuntu)<br>Or run with the automatic fallback to `ScapyEngine` which does not require compilation.<br>**Windows**: `ScapyEngine` is selected automatically. |
| **Auto-tuner does not update thresholds** | The active network traffic is below the minimum flow sample count (`200` flows per 30 minutes). | Check `logs/threshold_audit.jsonl`. Verify if `AUTO_TUNE_MIN_SAMPLES` is set to `200` in `config.py`. | No action needed. The auto-tuner safely skips adjustment cycles if there is insufficient traffic to prevent skewing the decision threshold. |
| **Recalibration fitting returns error** | The `/api/recalibration/fit` endpoint returns `501 Not Implemented`. | Attempting to fit recalibrator layers by uploading a CSV. | This endpoint is currently a stub since it depends on the offline-replay CSV parsing module (see [KNOWN_ISSUES.md](file:///home/gokul-p/Project/Vandana_E2/pipeline/nids-live/docs/KNOWN_ISSUES.md)). |
