# Compatibility and updates

## Current bundle

| Component | Supported or measured scope |
| --- | --- |
| **Supported SteamOS channel** | **Stable only**. Beta, Preview and Main are not supported. |
| **Tested SteamOS** | **3.8.28**, build **20260922.1** |
| Platform | SteamOS PC, x86-64 |
| Library filesystem | Mounted ext4 data partitions on separate, non-system drives |
| Cache drive | A dedicated SSD/NVMe identified by the plugin |
| Engine | Open CAS 26.09.0.1102.release, writethrough, 64 KiB cache lines |
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

Install a plugin release containing modules for the new kernel.
Without a matching bundle, the plugin reports that Open CAS is unavailable and uses the original HDD
when no active cache device owns it. Do not force-load modules built for another kernel.

Changing a selected drive, losing a valid saved cache state or using the HDD independently may cause
cache to rebuild. Game files remain on the original library drive.

## What was checked

On the tested PC, GRID and DiRT 3 launched and ran with Open CAS enabled.
Normal restart restored cached data. A GRID launch after restart produced read hits attributed
to GRID, along with matching physical NVMe reads.

Disposable-image checks covered cached reads, stop/load persistence, writes, atomic replacement,
clear/refill and visibility of updated files on the original filesystem after detaching.
These checks do not replace an end-to-end Steam download/update test, which remains unverified for this release.

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
