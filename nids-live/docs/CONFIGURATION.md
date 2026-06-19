# Configuration Reference Manual

All parameters governing the real-time inference pipeline and background tuning tasks are configured in `config.py`. 

> [!WARNING]
> Do not modify constants in the **Paths**, **Sequence/Batch**, **Feature Lists**, or **Clipping Columns** categories. These values are tied directly to the structural dimensions of the pre-trained neural networks and XGBoost models. Modifying them will cause matrix dimension mismatches and crash the inference pipeline.

---

## Configuration Parameter Table

| Parameter Name | Default Value | Type | Description |
| :--- | :--- | :--- | :--- |
| `BASE_DIR` | *Calculated* | `str` | Absolute path to the directory containing `config.py`. |
| `MODEL_DIR` | `BASE_DIR/models` | `str` | Absolute path to the directory containing model artifacts. |
| `SEQ_LEN` | `20` | `int` | Sequence length (window size) required by the TCN model. |
| `BATCH_SIZE` | `512` | `int` | Max batch size processed by the pipeline orchestrator loop. |
| `NUMERIC_FEATURES` | `["Dur", ...]` | `list[str]` | The 8 raw continuous features engineered from traffic flows. |
| `ENCODED_FEATURES` | `["Proto_enc", ...]` | `list[str]` | The 4 categorical features label-encoded or categorized. |
| `ALL_FEATURES` | `NUMERIC + ENCODED` | `list[str]` | Ordered list of 12 base features passed into the scaler. |
| `INTERACTION_NAMES` | `["byte_per_pkt...", ...]` | `list[str]` | The 6 interaction terms generated for XGBoost input. |
| `N_WITHIN` | `7` | `int` | Number of sequential features calculated for the TCN window. |
| `EPSILON` | `1e-9` | `float` | Floating-point safety epsilon to avoid division-by-zero errors. |
| `MIN_SEQ` | `5` | `int` | Minimum captured flows for an IP before TCN triggers. |
| `XGB_THRESHOLD` | `0.2` | `float` | Startup default decision threshold for XGBoost anomaly score. |
| `TCN_THRESHOLD` | `0.022` | `float` | Startup default decision threshold for TCN anomaly score. |
| `AUTO_TUNE_ENABLED_DEFAULT` | `False` | `bool` | Safe-by-default switch for passive background auto-tuning. |
| `AUTO_TUNE_INTERVAL_SEC` | `300` | `int` | Evaluation interval for the auto-tune background thread. |
| `AUTO_TUNE_WINDOW_SEC` | `1800` | `int` | Duration of trailing score window evaluated by the tuner. |
| `AUTO_TUNE_PERCENTILE` | `99.0` | `float` | Target percentile of non-alerted scores to suggest. |
| `AUTO_TUNE_MAX_STEP_FRACTION` | `0.10` | `float` | Max adjustment (10%) allowed per auto-tune cycle. |
| `AUTO_TUNE_MIN_SAMPLES` | `200` | `int` | Minimum valid samples required to run an auto-tune cycle. |
| `XGB_THRESHOLD_FLOOR` | `0.10` | `float` | Minimum allowable value for XGBoost decision threshold. |
| `XGB_THRESHOLD_CEILING` | `0.60` | `float` | Maximum allowable value for XGBoost decision threshold. |
| `TCN_THRESHOLD_FLOOR` | `0.010` | `float` | Minimum allowable value for TCN decision threshold. |
| `TCN_THRESHOLD_CEILING` | `0.100` | `float` | Maximum allowable value for TCN decision threshold. |
| `CALIBRATION_DEFAULT_PERCENTILE` | `99.5` | `float` | Percentile used by the guided calibration assistant. |
| `CALIBRATION_MAX_BUFFER` | `50000` | `int` | Maximum scores recorded in memory during calibration. |
| `TUNE_INTERVAL_SEC` | `300` | `int` | Alternate interval pointer (retained for backward compatibility). |
| `TUNE_WINDOW_SEC` | `1800` | `int` | Alternate window pointer (retained for backward compatibility). |
| `TUNE_MIN_SAMPLES` | `200` | `int` | Alternate minimum samples pointer. |
| `DOMAIN_SHIFT_DIAGNOSTIC_INTERVAL_SEC` | `60` | `int` | Frequency at which the passive domain shift analyzer runs. |
| `DOMAIN_SHIFT_WINDOW_ROWS` | `10000` | `int` | Trailing flow buffer size monitored for boundary clipping. |
| `CLIP_BOUNDARY_WARN_THRESHOLD` | `0.10` | `float` | Ratio of clipped features indicating a high domain shift ("likely shifted"). |
| `CLIP_BOUNDARY_WATCH_THRESHOLD` | `0.02` | `float` | Ratio of clipped features indicating a mild domain shift ("watch"). |
| `CLIP_COLS` | `["Dur", ...]` | `list[str]` | The 7 base columns subjected to clipping via `clip_bounds.pkl`. |
| `IDLE_TIMEOUT_SEC` | `120` | `int` | Flow idle duration limit (Scapy engine flow-expiry). |
| `ACTIVE_TIMEOUT_SEC` | `1800` | `int` | Flow total duration limit (Scapy engine flow-expiry). |
| `FLASK_HOST` | `"0.0.0.0"` | `str` | Host network interface to bind the Flask web application to. |
| `FLASK_PORT` | `5000` | `int` | Network port for the Flask web application. |
| `FLASK_DEBUG` | `False` | `bool` | Flask debug/reloader mode flag (keep False in production). |
