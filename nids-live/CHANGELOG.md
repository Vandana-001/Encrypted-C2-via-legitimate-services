# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-06-19

### Added
- **Dual Packet Capture Engines**:
  - C-based high-performance `nfstream` engine for Linux and macOS environments.
  - Custom `scapy` sniffer engine utilizing a callback-driven packet sniffer and a hash-based flow table with active and idle timeouts.
  - Automatic fallback selection logic in `capture/interfaces.py`.
- **Parallel Classification Path**:
  - Per-flow XGBoost classifier scoring individual flows augmented with 6 interaction features.
  - Per-IP TCN sequence model scoring windows of 20 flows augmented with 7 statistical within-window attributes.
  - Cyclic sequence padding (tiling) enabling early TCN sequence predictions for flows between lengths 5 and 20.
- **Three-Layer Threshold Management**:
  - Interactive manual threshold sliders on the frontend dashboard.
  - Guided calibration assistant computing suggestions at designated baseline percentiles (default: 99.5%).
  - Background auto-tune thread evaluating trailing scores and stepping thresholds (max 10% per cycle) under volume constraints.
  - Persisted threshold changes in JSON format and audit logging in JSON Lines (`logs/threshold_audit.jsonl`).
- **Domain Adaptation Modules**:
  - Passive domain-shift monitor checking boundary clipping ratios on numeric features.
  - Live Yeo-Johnson PowerTransformer lambda adaptation for byte features (`TotBytes`, `SrcBytes`, `BytesPerPkt`).
  - Isotonic probability recalibration layers for aligning anomaly scores.
- **Flask REST API & Web Dashboard**:
  - REST endpoints for start/stop control, real-time status query, flow/alert listing, top suspicious IPs, and calibration.
  - Vanilla HTML/CSS/JS single-page web dashboard with interactive styling, status widgets, and collapsible adjustment panels.
- **Comprehensive Documentation Suite**:
  - Top-level `README.md` and `CHANGELOG.md`.
  - Core guides under `docs/` detailing Architecture, Feature Engineering, Model configurations, Capture Engines, REST API schemas, Threshold rules, Configuration keys, and Troubleshooting steps.
