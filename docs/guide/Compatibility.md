# Compatibility and updates

## Current bundle

| Component | Supported or measured scope |
| --- | --- |
| **Supported SteamOS channel** | **Stable only**. Beta, Preview and Main are not supported. |
| **Tested SteamOS** | **3.8.28**, build **20260922.1** |
| Platform | SteamOS PC, x86-64 |
| Library filesystem | Mounted ext4 data partitions on separate, non-system drives |
| Cache drive | A dedicated SSD/NVMe identified by the plugin |
| Engine | Open CAS 26.09.0.1102.release, write-around, 64 KiB cache lines |
| **Required kernel (exact match)** | `6.18.50-valve2-1-neptune-618-gc7289a96b14d` |
| Hardware test environment | SteamOS 3.8.28, Decky Loader 3.2.10, NVIDIA PC |

Check the kernel in Desktop Mode:

```sh
uname -r
```

The string must match the bundled module version exactly. The plugin loads matching external modules;
it does not rebuild or replace the kernel.

Btrfs, NTFS, exFAT, system-drive libraries and multi-device filesystems are outside this release's supported scope.
Steam Deck hardware and other SteamOS kernels have not been qualified by the PC test.

## After a SteamOS kernel update

The panel and **Check for updates** remain available without a matching module bundle.
The updater offers a newer stable release only when it contains modules for exactly the running kernel.
Follow [Updating the plugin](Installation.md#updating-the-plugin).

Until a matching bundle is published and installed, caching is unavailable and the original HDD is used
when no active cache device owns it. Games stay on that drive. Do not force-load modules built for another kernel.

Compatible plugin updates through the built-in updater preserve active cache and library mounts.
The previous detaching updater and manual ZIP replacement do not provide this handoff.

Changing a selected drive, losing a valid saved cache state or using the HDD independently may cause
cache to rebuild. Game files remain on the original library drive.

## What was checked

On the tested PC, GRID and DiRT 3 launched and ran with Open CAS enabled.
The master OFF/ON switch was checked on this PC: passthrough kept GRID's attributed cached blocks
and the mounted library. That earlier switch check used writethrough; the current release uses write-around. Decky's native installer reloaded the development
build without restarting the PC, and its update check reached GitHub from Decky's embedded Python.

Normal restart restored cached data. A GRID launch after restart produced read hits attributed
to GRID, along with matching physical NVMe reads.

Disposable-image checks covered cached reads, stop/load persistence, writes, atomic replacement,
clear/refill and visibility of updated files on the original filesystem after detaching.
These checks do not replace an end-to-end Steam download/update test, which remains unverified for this release.

A native plugin update between development builds preserved the mounted cache and all 31 installed-game entries.
GRID reads after installation produced cache hits. After the update, disposable-file writes, overwrites and
atomic replacement matched direct reads from the original HDD as well as the cached filesystem.

Non-Steam shortcuts were detected on the selected volume, and Blood's existing custom Steam artwork loaded.
A controlled 1 MiB read of a Blood file was served entirely from NVMe and attributed to its game folder.
That is a diagnostic storage read, not a gameplay benchmark.

For 0.4.8, a native update to the development build kept occupied cache bytes, the active library mount
and all 31 Steam game entries. Folder selection applied without remounting or clearing cache.
An isolated ext4 check confirmed that writes and excluded reads do not allocate new cache lines,
while selected-folder reads populate cache and produce hits. Overwrites and atomic replacements
returned current content. This is not a real Steam download/update test.

After a normal PC restart, a 90-second MOUSE loading/gameplay observation measured **1.05 GiB from
cache and 69 MiB from HDD**, approximately **94% of the measured storage-read bytes from cache**.
Physical NVMe counters independently matched the cache reads. Cache errors remained zero.
The cache was retained across restart. These are storage I/O measurements, not a loading-time benchmark
or a count of reads served from RAM.

These observations do not establish performance gains for every game or compatibility with every PC.

## Automatic module compilation

This release ships prebuilt modules. Building a new bundle requires the exact kernel headers
and a matching build toolchain; their availability cannot be assumed on every SteamOS installation.
There is no compilation or compiler download during plugin installation.
A kernel change requires a new matching bundle, not necessarily changes to the plugin itself.

## Automatic shutdown ordering on NVIDIA

When caching is enabled for a library on an NVIDIA system, the plugin automatically installs
systemd ordering overrides for the Plymouth reboot, power-off and halt splash services.
The splash waits for the Steam user session and DeckyCache service to stop.
No manual system commands are needed for this setting.
Disabling all library partitions or successfully uninstalling removes the plugin's own overrides.
This behavior was verified on the test PC; it is not a universal fix for unrelated shutdown faults.
