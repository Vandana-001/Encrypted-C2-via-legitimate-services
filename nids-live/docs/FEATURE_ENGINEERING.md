# Feature Engineering Reference

This document serves as the mathematical and implementation reference for all features engineered in the NIDS-Live pipeline.

---

## 1. Feature Lifecycle Overview

Each captured network flow goes through the following transformation pipeline:
1. **Numeric Coercion & Cleaning**: Coerces features to float64, drops rows containing missing values (`NaN`/`inf`).
2. **Behavioral Ratios**: Computes secondary flow dynamics.
3. **P99 Clipping**: Clips features using training bounds.
4. **Encoding**: Transforms categorical protocols and directions via label encoders, and groups ports into categories.
5. **Base Scaling**: Applies `PowerTransformer` normalization and clips to `[-4, 4]`.
6. **XGBoost Interaction Augmentation**: Appends 6 interaction terms for XGBoost.
7. **TCN Sequence Assembly**: Accumulates flows per source IP, computes 7 within-window statistical properties, scales them using `RobustScaler`, and pads short sequences.

---

## 2. Base Feature Preprocessing

The following base transformations are performed in `pipeline/feature_engineering.py` inside `engineer_features(df)`:

| Output Column | Input Column(s) | Transformation / Formula | Constraints / Clipping |
| :--- | :--- | :--- | :--- |
| `Dur` | `Dur` | Numeric coercion | Clipped to `clip_bounds["Dur"]` |
| `TotPkts` | `TotPkts` | Numeric coercion | Clipped to `clip_bounds["TotPkts"]` |
| `TotBytes` | `TotBytes` | Numeric coercion | Clipped to `clip_bounds["TotBytes"]` |
| `SrcBytes` | `SrcBytes` | Numeric coercion | Clipped to `clip_bounds["SrcBytes"]` |
| `BytesPerPkt` | `TotBytes`, `TotPkts` | `TotBytes / (TotPkts + 1e-9)` | Clipped to `clip_bounds["BytesPerPkt"]` |
| `PktRate` | `TotPkts`, `Dur` | `TotPkts / (Dur + 1e-9)` | Clipped to `clip_bounds["PktRate"]` |
| `ByteRate` | `TotBytes`, `Dur` | `TotBytes / (Dur + 1e-9)` | Clipped to `clip_bounds["ByteRate"]` |
| `SrcBytesRatio`| `SrcBytes`, `TotBytes` | `(SrcBytes / (TotBytes + 1e-9)).clip(0, 1)` | Clamped to `[0, 1]` |
| `Proto_enc` | `Proto` | Lowercased, stripped, encoded via `le_proto` | Fallback to `le_proto.classes_[0]` on unseen |
| `Dir_enc` | `Dir` | Stripped, encoded via `le_dir` | Fallback to `le_dir.classes_[0]` on unseen |
| `Sport_cat` | `Sport` | Categorized via `_categorize_port()` | Map boundaries: see Port Categorization below |
| `Dport_cat` | `Dport` | Categorized via `_categorize_port()` | Map boundaries: see Port Categorization below |

### Port Categorization (`_categorize_port`)
Ports are mapped into one of six categories:
* **Category 4**: HTTPS (443) and HTTP (80)
* **Category 5**: DNS (53)
* **Category 0**: Well-known ports (`p <= 1023` excluding 443, 80, 53)
* **Category 1**: Registered ports (`1024 <= p <= 49151`)
* **Category 2**: Ephemeral ports (`p >= 49152`)
* **Category 3**: Unparseable or non-numeric port strings

### Yeo-Johnson Base Scaling
After the 12 base features are assembled in the exact order (`Dur`, `TotPkts`, `TotBytes`, `SrcBytes`, `BytesPerPkt`, `PktRate`, `ByteRate`, `SrcBytesRatio`, `Proto_enc`, `Sport_cat`, `Dport_cat`, `Dir_enc`), the training PowerTransformer (`scaler.pkl` or `scaler_adapted.pkl`) is applied in `pipeline/scaling.py`:
$$\text{Scaled Value} = \text{clip}\left(\text{PowerTransformer}(X), -4, 4\right)$$

---

## 3. XGBoost Interaction Features

In `pipeline/xgb_inference.py` inside `add_xgb_interactions(X, feature_names)`, 6 interaction features are appended to create the final 18-dimensional matrix:

* **`byte_per_pkt_rate`**:
  $$\text{byte\_per\_pkt\_rate} = \text{clip}\left(\frac{\text{ByteRate}}{\text{PktRate} + 1e-9}, 0, 10000\right)$$
* **`src_dominance_dur`**:
  $$\text{src\_dominance\_dur} = \text{SrcBytesRatio} \times \log(1 + \text{Dur})$$
* **`port_symmetry`**:
  $$\text{port\_symmetry} = \begin{cases} 1.0 & \text{if Sport\_cat} == \text{Dport\_cat} \\ 0.0 & \text{otherwise} \end{cases}$$
* **`pkt_density`**:
  $$\text{pkt\_density} = \text{clip}\left(\frac{\text{TotPkts}}{\text{TotBytes} + 1e-9}, 0, 1000\right)$$
* **`proto_dport_cross`**:
  $$\text{proto\_dport\_cross} = \text{Proto\_enc} \times 10 + \text{Dport\_cat}$$
* **`byte_asym_mag`**:
  $$\text{byte\_asym\_mag} = \text{clip}\left(|2 \times \text{SrcBytesRatio} - 1|, 0, 1\right)$$

---

## 4. TCN Within-Window Features

In `pipeline/tcn_inference.py` inside `_within_window_features(...)`, 7 features are calculated across the sequence window (length $L \le 20$):

* **`w_iat_mean`**: Mean of raw Inter-Arrival Times (`IAT_raw`) in the window.
* **`w_iat_std`**: Standard deviation of raw Inter-Arrival Times (`IAT_raw`) in the window.
* **`w_beacon` (beacon regularity)**:
  $$\text{w\_beacon} = \text{clip}\left(\frac{\text{w\_iat\_std}}{\text{w\_iat\_mean} + 1e-9}, 0, 100\right)$$
* **`w_pay_cv` (payload coefficient of variation)**:
  $$\text{w\_pay\_cv} = \text{clip}\left(\frac{\text{w\_tb\_std}}{\text{w\_tb\_mean} + 1e-9}, 0, 100\right)$$
  *(Where `w_tb_mean` and `w_tb_std` are calculated on unscaled `TotBytes` values)*.
* **`w_fasym_mean`**: Mean of flow asymmetry values in the window.
* **`w_dst_fanout`**: Distinct destination IPs in the window, capped at sequence length:
  $$\text{w\_dst\_fanout} = \text{clip}\left(\text{count\_distinct}(\text{DstAddr}), 0, L\right)$$
* **`w_dport_ent` (destination port entropy)**:
  $$\text{w\_dport\_ent} = -\sum (p_i \log(p_i + 1e-12))$$
  *(Where $p_i$ represents the relative frequencies of unique integer-parsed destination ports in the window)*.

These 7 window features are broadcast across all 20 timesteps and concatenated with the 12 base scaled features. The resulting 19-dimensional sequence is scaled with the within-window `RobustScaler` (`win_scaler.pkl`) and clipped to `[-4, 4]`.

---

## 5. Streaming vs. Notebook Differences

To support real-time execution, the streaming pipeline deviates from batch notebook processing in two key areas:

### 1. Inter-Arrival Time (IAT) Calculation
* **Notebook**: Performs a full table sort and differences timestamps globally per IP:
  `df.groupby("SrcAddr")["StartTime_epoch"].diff().fillna(0)`
* **Streaming**: Maintains a thread-safe global lookup dictionary `_last_epoch_by_src`. As a new flow completes, its `StartTime_epoch` is subtracted from the last recorded value for that source IP:
  $$\text{IAT} = \text{StartTime\_epoch} - \text{last\_epoch\_by\_src}[\text{SrcAddr}]$$

### 2. Sequence Padding (Cyclic Tiling)
* **Notebook**: Windows are built using sliding step logic (`step=1`) over complete pre-grouped lists. Short sequences (e.g. source IP with fewer than 20 flows) are padded.
* **Streaming**: The rolling queue contains the latest history for a source IP. When the history count is between `MIN_SEQ` (5) and `SEQ_LEN` (20), cyclic padding is applied using `np.tile` to fill the window:
  ```python
  repeats = math.ceil(SEQ_LEN / n_rows)
  features_arr = np.tile(features_arr, (repeats, 1))[:SEQ_LEN]
  ```
  This ensures model execution can run before a full 20 flows have completed for that IP.
