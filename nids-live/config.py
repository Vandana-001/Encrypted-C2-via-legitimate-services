"""
config.py — Global configuration for the NIDS-Live system.

All constants here must match the training notebook exactly.
Do NOT change thresholds, epsilon, SEQ_LEN, or feature lists
without retraining the models.
"""

import os

# ── Paths ─────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "models")

# ── Sequence / batch knobs (must match training) ──────────────────────
SEQ_LEN = 20
BATCH_SIZE = 512

# ── Feature lists (must match training Cell 3 exactly) ────────────────
NUMERIC_FEATURES = [
    "Dur", "TotPkts", "TotBytes", "SrcBytes",
    "BytesPerPkt", "PktRate", "ByteRate", "SrcBytesRatio",
]
ENCODED_FEATURES = ["Proto_enc", "Sport_cat", "Dport_cat", "Dir_enc"]
ALL_FEATURES = NUMERIC_FEATURES + ENCODED_FEATURES   # 12 dims, this exact order

INTERACTION_NAMES = [
    "byte_per_pkt_rate", "src_dominance_dur", "port_symmetry",
    "pkt_density", "proto_dport_cross", "byte_asym_mag",
]

N_WITHIN = 7          # within-window TCN features appended per sequence
EPSILON = 1e-9
MIN_SEQ = 5           # minimum flows per source IP before a TCN window is produced

# ── Decision thresholds (Startup defaults) ────────────────────────────
XGB_THRESHOLD = 0.2
TCN_THRESHOLD = 0.022

# ── Adaptive threshold management ─────────────────────────────────────
AUTO_TUNE_ENABLED_DEFAULT   = False     # always opt-in, never on by default
AUTO_TUNE_INTERVAL_SEC      = 300       # recompute candidate threshold every 5 min
AUTO_TUNE_WINDOW_SEC        = 1800      # trailing 30-min score window considered
AUTO_TUNE_PERCENTILE        = 99.0      # candidate = this percentile of trailing non-alerted scores
AUTO_TUNE_MAX_STEP_FRACTION = 0.10      # threshold may move at most 10% per adjustment cycle
AUTO_TUNE_MIN_SAMPLES       = 200       # skip the cycle if fewer qualifying scores than this

XGB_THRESHOLD_FLOOR, XGB_THRESHOLD_CEILING = 0.10, 0.60
TCN_THRESHOLD_FLOOR, TCN_THRESHOLD_CEILING = 0.010, 0.10

CALIBRATION_DEFAULT_PERCENTILE = 99.5   # used by the guided calibration assistant
CALIBRATION_MAX_BUFFER         = 50_000 # cap per-model score buffer during a calibration window

# ── Auto-Tuning Configuration ─────────────────────────────────────────
TUNE_INTERVAL_SEC = 300
TUNE_WINDOW_SEC = 1800
TUNE_MIN_SAMPLES = 200

# ── Domain-Shift Diagnostic Configuration ─────────────────────────────
DOMAIN_SHIFT_DIAGNOSTIC_INTERVAL_SEC = 60
DOMAIN_SHIFT_WINDOW_ROWS              = 10_000
CLIP_BOUNDARY_WARN_THRESHOLD          = 0.10   # 10% → "likely shifted"
CLIP_BOUNDARY_WATCH_THRESHOLD         = 0.02   # 2% → "watch"

# ── Clipping columns ─────────────────────────────────────────────────
CLIP_COLS = [
    "Dur", "TotPkts", "TotBytes", "SrcBytes",
    "BytesPerPkt", "PktRate", "ByteRate",
]

# ── Flow-completion timing ────────────────────────────────────────────
# Mirrors nfstream's flow-expiry semantics used at training/offline-inference time
IDLE_TIMEOUT_SEC = 120       # flow considered finished if idle this long
ACTIVE_TIMEOUT_SEC = 1800    # flow force-finished if it runs this long

# ── Flask ─────────────────────────────────────────────────────────────
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
FLASK_DEBUG = False
