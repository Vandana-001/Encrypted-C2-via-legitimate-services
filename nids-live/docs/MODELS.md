# Model Artifacts Directory

This document details the configuration and shapes of the pre-trained machine learning artifacts stored under `models/`.

---

## 1. Summary of Required Artifacts

On startup, the system loads seven artifacts using a singleton pattern implemented in `pipeline/model_loader.py`.

| Filename | Type / Class | Input Dimension | Role / Description |
| :--- | :--- | :--- | :--- |
| `clip_bounds.pkl` | Pickled `dict` | N/A | Maps base columns to upper clipping boundaries. |
| `scaler.pkl` | Pickled `PowerTransformer` | `(n_flows, 12)` | Normalizes 12 base features to standard scale. |
| `le_proto.pkl` | Pickled `LabelEncoder` | N/A | Protocol category encoder. |
| `le_dir.pkl` | Pickled `LabelEncoder` | N/A | Direction string category encoder. |
| `xgb_model.pkl` | Pickled `XGBClassifier` | `(n_flows, 18)` | Scores flows individually. |
| `tcn_best.keras` | Keras Model (or directory) | `(n_seq, 20, 19)` | Sequential detection model. |
| `win_scaler.pkl` | Pickled `RobustScaler` | `(n_seq * 20, 7)` | Standardizes the 7 window features. |
| `runtime_thresholds.json` | JSON Config file | N/A | Persists the live model decision thresholds. |

---

## 2. Loader implementation and shapes

### 1. `clip_bounds.pkl`
* **Loaded By**: `pipeline/model_loader.py`
* **Load Call**:
  ```python
  _artifacts.clip_bounds = joblib.load(os.path.join(MODEL_DIR, "clip_bounds.pkl"))
  ```
* **Expected Keys**: `Dur`, `TotPkts`, `TotBytes`, `SrcBytes`, `BytesPerPkt`, `PktRate`, `ByteRate`

### 2. `scaler.pkl` / `scaler_adapted.pkl`
* **Loaded By**: `pipeline/model_loader.py`
* **Load Call**:
  ```python
  _artifacts.scaler = joblib.load(os.path.join(MODEL_DIR, "scaler.pkl"))
  ```
  *(If `scaler_adapted.pkl` exists, it is loaded instead to apply byte-column adaptation).*
* **Expected Input**: `(N, 12)` base features in order.

### 3. `xgb_model.pkl`
* **Loaded By**: `pipeline/model_loader.py`
* **Load Call**:
  ```python
  _artifacts.xgb_model = joblib.load(os.path.join(MODEL_DIR, "xgb_model.pkl"))
  ```
* **Input Dimensionality**: `(N, 18)` representing:
  * 12 base scaled features.
  * 6 interaction features: `byte_per_pkt_rate`, `src_dominance_dur`, `port_symmetry`, `pkt_density`, `proto_dport_cross`, `byte_asym_mag`.

### 4. `tcn_best.keras` (or `tcn_model_savedmodel`/`tcn_model` directory)
* **Loaded By**: `pipeline/model_loader.py`
* **Load Call**:
  ```python
  _artifacts.tcn_model = tf.keras.models.load_model(tcn_path, compile=False)
  ```
* **Input Dimensionality**: `(N, 20, 19)` representing:
  * Sequence length: 20 timesteps.
  * 19 features per timestep: 12 base scaled features + 7 scaled within-window statistics broadcasted across all timesteps.

### 5. `win_scaler.pkl`
* **Loaded By**: `pipeline/model_loader.py`
* **Load Call**:
  ```python
  _artifacts.win_scaler = joblib.load(os.path.join(MODEL_DIR, "win_scaler.pkl"))
  ```
* **Input Dimensionality**: `(N * 20, 7)` representing:
  * 7 sequence-level statistics scaled along the time dimension: `w_iat_mean`, `w_iat_std`, `w_beacon`, `w_pay_cv`, `w_fasym_mean`, `w_dst_fanout`, `w_dport_ent`.

---

## 3. Startup Error Handling

If any of the required model files are missing on startup:
1. `pipeline/model_loader.py` raises a `RuntimeError` during the `load_artifacts()` routine:
   ```python
   raise RuntimeError(
       f"Missing model artifacts in {MODEL_DIR}: {', '.join(missing)}. "
       f"Please place all required model files in the models/ directory."
   )
   ```
2. In `app.py`, this error is caught in a global `try...except` block:
   ```python
   try:
       artifacts = load_artifacts()
       orchestrator = Orchestrator(state, artifacts)
   except Exception as exc:
       model_load_error = str(exc)
   ```
3. The server starts up normally (allowing operators to see the UI), but:
   * The status indicator transitions to **Error**.
   * Any call to POST `/api/start` returns a `500 Internal Server Error` with JSON indicating the missing files:
     ```json
     {
       "status": "error",
       "message": "Model artifacts not loaded: Missing model artifacts in ..."
     }
     ```
