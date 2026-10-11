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

Open CAS caches **64 KiB blocks**, not whole games. Write-around sends writes to the original HDD without allocating new cache lines.
Overlapping cached data is updated or invalidated, so subsequent reads see the current game files. Steam keeps using the same library path.

Each selected partition gets a preallocated cache backing image on the SSD filesystem.
It is attached using direct I/O, so the backing image does not create a second Linux page-cache layer.
Approximately 10% of the SSD filesystem capacity stays outside these allocations.
The panel reports Open CAS occupancy, not the allocated image size.

## Master switch

ON uses write-around with the selected drive or folder scope. OFF switches the same mounted cache device to passthrough:
reads use the HDD, valid cached blocks remain on the SSD, and writes invalidate overlapping cached lines.
Turning caching back on can reuse the unaffected data. This also keeps Steam updates coherent while OFF.

The built-in updater keeps the same mounted Open CAS devices across a compatible plugin update.
Storage code and its binaries have an independent runtime outside Decky's replaceable plugin directory.
The worker adopts the new runtime between operations without stopping the systemd unit or unmounting a library.
Writes continue through Open CAS throughout installation, including Steam updates.

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

Steam manifests and non-Steam shortcuts supply game names and installation paths.
Shortcuts with a direct executable inside a selected library volume are detected automatically.
External launchers that hide the game path are not attributed to a game. The panel uses custom artwork
already set in Steam, including artwork supplied by other plugins, with standard Steam covers as a fallback.

## Cache scope

**Entire selected drives** admits reads anywhere on the enabled partitions.
**Selected folders** admits only reads associated with the chosen folders. Add a Steam library
with its shortcut button or use **Add folder...** for DRM-free games and other libraries.
Folders must be on an enabled library drive. Selection changes apply online without remounting
libraries or clearing existing cache.

Both modes use write-around: writes from copying, installation and Steam updates do not allocate
new cache lines. Data is written to the HDD; cached overlaps are updated or invalidated.
Reading files for copying, unpacking or verification can populate cache if the source is inside
the chosen scope. Folder mode is an I/O location filter, not a game-running detector.

Open CAS directory rules cannot identify some direct or asynchronous reads. In folder mode those
requests bypass cache rather than admitting data from elsewhere on the partition.
The engine has 32 tracking slots per volume, shared by game paths and selected folder roots.
If no slot remains for a new folder, the selection is refused without widening the scope.
Game classes keep their old IDs and occupancy across updates.

The main list uses a 16 MiB threshold. Smaller entries remain under **Small fragments**.
Shared installation folders appear once. **Other cached data** is always the last tile and includes
unclassified occupancy and classes whose former game paths are no longer in the catalogue.
It excludes all listed games, including collapsed small fragments. Its total and the game cards come
from the same per-class snapshot. Cached data saved by earlier versions is retained; this update does
not silently clear it. These counters are attribution, not a precise inventory of current game files.

## Why there is no pinning or per-game clear

This release has no pinning or full-game preload. The shipped administration interface can clear
an entire cache, but cannot reliably purge all blocks of one game, including its unclassified data.
The panel therefore offers **Clear cache** for the selected active libraries.
