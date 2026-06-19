# Capture Engines Reference

The NIDS-Live system abstracts network interface card (NIC) capture behind the common `CaptureEngine` interface, providing cross-platform compatibility.

---

## 1. Engine Selection Logic

The selection of the capture engine occurs in `capture/interfaces.py` inside `select_capture_engine()`:

```python
def select_capture_engine():
    if platform.system() in ("Linux", "Darwin"):
        try:
            import nfstream
            return NFStreamEngine
        except ImportError:
            pass
    return ScapyEngine
```

* **Linux / macOS**: Uses the high-performance C-based `NFStreamEngine` if the `nfstream` library is installed. Otherwise, falls back to `ScapyEngine`.
* **Windows**: Always falls back to `ScapyEngine` (since `nfstream` does not support Windows).
* **Manual Override**: Operators can manually choose engines via the dashboard dropdown or by specifying the `engine` parameter in POST `/api/start` (`nfstream`, `scapy`, or `auto`).

---

## 2. Capture Engines Comparison

### 1. `NFStreamEngine`
* **Implementation**: Runs `NFStreamer` in a daemon thread.
* **Flow Reconstruction**: Offloaded to `nfstream`'s native bidirectional flow assembler.
* **Constructor**: Takes no arguments.
* **Permission Error**: If permission is denied, it posts a message to the queue:
  ```
  Permission denied opening interface — run with sudo, or grant capabilities once: sudo setcap cap_net_raw,cap_net_admin=eip $(readlink -f $(which python3))
  ```

### 2. `ScapyEngine`
* **Implementation**: Uses Scapy's `AsyncSniffer(store=False)` to process packets on the fly.
* **Flow Reconstruction**: Manages an internal, thread-safe flow dictionary (`_flow_table`) keyed by the 5-tuple:
  $$\text{Key} = \left(\text{src\_ip}, \text{dst\_ip}, \text{sport}, \text{dport}, \text{proto}\right)$$
* **Constructor**: Takes no arguments.
* **Flow Expiry Timer**: A background timer runs `_expire_flows()` every `1.0` seconds to check the flow table.
* **Flow Expiry Logic**:
  * **Idle Timeout**: If a flow sees no packet for more than `IDLE_TIMEOUT_SEC` (default: 120s), it is expired.
  * **Active Timeout**: If a flow runs continuously for more than `ACTIVE_TIMEOUT_SEC` (default: 1800s), it is force-expired.
* **Permission Error**: If starting the sniffer raises `PermissionError`:
  ```
  Permission denied opening interface — run as Administrator (Windows) or with sudo/setcap (Linux/macOS).
  ```

---

## 3. Schema Mapping

Both capture engines transform raw captured traffic into a common dictionary schema before appending it to the queue consumed by the pipeline orchestrator.

| Output Key | Type | Description | NFStream Source Field | Scapy Source Field |
| :--- | :--- | :--- | :--- | :--- |
| `StartTime` | `Timestamp` / `datetime` | Start time of flow (UTC) | `bidirectional_first_seen_ms` | Timestamp of first packet |
| `Dur` | `float` | Duration of flow in seconds | `bidirectional_duration_ms / 1000` | `last_ts - first_ts` (min 1e-9) |
| `Proto` | `str` | Lowercase protocol name | `protocol_name` or `protocol` | IP layer protocol name/code |
| `SrcAddr` | `str` | Source IPv4/IPv6 Address | `src_ip` | IP src field |
| `Sport` | `str` | Source Port | `src_port` | TCP/UDP sport (else `"0"`) |
| `Dir` | `str` | Direction arrow (`->`) | Hardcoded `"->"` | Hardcoded `"->"` |
| `DstAddr` | `str` | Destination IPv4/IPv6 Address | `dst_ip` | IP dst field |
| `Dport` | `str` | Destination Port | `dst_port` | TCP/UDP dport (else `"0"`) |
| `TotPkts` | `int` | Total packets in flow | `bidirectional_packets` | Accumulated packets |
| `TotBytes` | `int` | Total bytes in flow | `bidirectional_bytes` | Accumulated byte length |
| `SrcBytes` | `int` | Bytes sent from source | `src2dst_bytes` | Accumulated byte length |
| `Label` | `str` | Classification label | Hardcoded `"Unknown"` | Hardcoded `"Unknown"` |

---

## 4. OS-Specific Capture Prerequisites

To capture raw network interfaces, the host system requires specific low-level library hooks and administrative privileges:

> [!IMPORTANT]
> **Windows Setup**
> * Requires **Npcap** or **WinPcap** installed. Ensure the "Support raw 802.11 traffic" and "Install Npcap in WinPcap API-compatible mode" options are enabled during Npcap installation.
> * Run python/dashboard with **Administrator** command prompt.
>
> **Linux Setup**
> * Run as `root` (sudo), or grant raw network access capabilities to the Python binary:
>   ```bash
>   sudo setcap cap_net_raw,cap_net_admin=eip $(readlink -f $(which python3))
>   ```
>
> **macOS Setup**
> * Ensure you have read/write access to `/dev/bpf*` character devices. This can be achieved by running the ChmodBPF script installed with Wireshark, or by executing the dashboard as `root`.
