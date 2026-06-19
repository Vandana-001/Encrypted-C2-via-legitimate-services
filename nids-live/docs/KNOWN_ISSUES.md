# Known Issues and Gaps

This document identifies known bugs, gaps, and unimplemented functions in the current release of the NIDS-Live system.

---

## 1. Unimplemented Recalibration Fit Endpoint (`/api/recalibration/fit`)

* **Component**: `app.py` (line 370–380) / `pipeline/recalibration.py`
* **Severity**: Medium
* **Symptom**: Triggering a fit via POST `/api/recalibration/fit` returns a `501 Not Implemented` status code:
  ```json
  {
    "status": "error",
    "message": "CSV upload for offline replay not yet fully implemented due to dependency on offline parsing module."
  }
  ```
* **Root Cause**: The offline CSV parsing and replay modules required to feed raw PCAP-like logs through feature extraction and target matching are not integrated into the Flask microservice.
* **Workaround**: Isotonic recalibration layers (`recal_xgb.pkl`, `recal_tcn.pkl`) must be pre-fitted offline and manually placed in the `models/` directory.

---

## 2. StratifiedShuffleSplit Single-Class Fitting Crash

* **Component**: `pipeline/recalibration.py` (inside `ModelRecalibrator._fit_pipeline(...)`)
* **Severity**: Low
* **Symptom**: Calling `fit_xgb` or `fit_tcn` triggers a `ValueError: The least populated class in y has only 1 member...` crash.
* **Root Cause**: The internal validation split utilizes `StratifiedShuffleSplit(n_splits=1, test_size=0.7)` to partition raw scores into training and evaluation sets for the logistic and isotonic layers:
  ```python
  sss = StratifiedShuffleSplit(n_splits=1, test_size=0.7, random_state=42)
  train_idx, eval_idx = next(sss.split(X, y))
  ```
  If the training target vector `y_true` (or the labels array) is homogeneous (i.e. contains only benign `0` labels or only malicious `1` labels), the stratification logic fails since it cannot split a class with zero or single members across both partitions.
* **Workaround**: Ensure the dataset used to fit the isotonic calibration contains a mixture of both benign flows and attack flows (at least two representatives of each class).
