# How DeckyCache works

## The data path

```text
Game / Steam
    ↓
Linux filesystem cache in RAM
    ↓ when storage I/O is needed
ext4 library on the Open CAS device
    ├─ cache hit → SSD / NVMe
    └─ cache miss → original HDD → eligible data cached on SSD / NVMe
```

Open CAS caches **64 KiB blocks**, not whole games. Writethrough sends writes to the original HDD
and maintains cache coherence. Steam keeps using the same library path.

Each selected partition gets a preallocated cache backing image on the SSD filesystem.
It is attached using direct I/O, so the backing image does not create a second Linux page-cache layer.
Approximately 10% of the SSD filesystem capacity stays outside these allocations.
The panel reports Open CAS occupancy, not the allocated image size.

## Persistent cache

During a clean shutdown, the service unmounts the library, stops Open CAS normally, syncs the image
and records a seal identifying the source, cache and ext4 filesystem state.
The next boot can load the existing cache only when that seal matches.

A forced shutdown or changed source state can invalidate reuse. Starting with empty cache in that case
prevents stale blocks from being treated as current game data.

A Decky UI reload leaves the independent cache service running.
The plugin manages automount ordering so the original partition is not also mounted independently.
On NVIDIA systems with selected libraries, it orders the shutdown splash after the user session
and cache service so cache shutdown can finish before the display handover.

## Game attribution

Steam manifests supply names and artwork. Open CAS directory classes track up to **32 distinct installation
folders per cached volume**. Rules classify regular files and exclude directory metadata.

Direct I/O cannot be attributed by these directory rules and may reclassify cached lines.
Unclassified data still uses ordinary cache. A class may retain blocks from replaced or deleted files
until eviction or reuse. Consequently, the game list is partial and is not an exact live file-residency map.

The main list uses a 16 MiB threshold. Smaller entries remain under **Small fragments**.
Shared installation folders appear once.

## Why there is no pinning or per-game clear

This release has no pinning or full-game preload. The shipped administration interface can clear
an entire cache, but cannot reliably purge all blocks of one game, including its unclassified data.
The panel therefore offers **Clear cache** for the selected active libraries.
