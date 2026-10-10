# Troubleshooting

## No cache SSD/NVMe is listed

The cache must be a separate non-rotational drive. Detected system drives, selected library drives
and drives used by another storage layer are excluded. A drive without a usable serial number
cannot be selected. Check the physical connection and reopen the panel.

## A library partition is missing

It must be an ext4 data partition on a separate, non-system drive and already mounted under
`/run/media/`, `/media/` or `/mnt/`. Mount it in Desktop Mode and check that Steam sees its existing
library, then reopen DeckyCache.

The current version selects partitions, not folders.

## Format or selection is refused

Read the error in the panel. Close games, file managers and applications using that drive,
and let Steam updates finish. Reopen the drive selector if the device list changed.
Do not format the library HDD to resolve a cache-drive error.

## Open CAS is unavailable / Waiting for cache

Check the selected SSD connection and compare `uname -r` with
[Compatibility](Compatibility.md). A kernel update requires a matching module bundle.
Do not force-load an older module or format the SSD just to clear this message.

## Cache space grows but there are few hits

The first read of uncached data normally comes from HDD.
Repeated reads may be served from RAM before reaching Open CAS.
Writes can also populate cache. Occupancy alone does not prove a game read came from NVMe.

For a controlled check, close the game, restart normally, record Open CAS counters before launch,
then load the same content and compare read hits and physical NVMe reads.
Do not clear the SSD cache before that test.

## A game appears even though I did not launch it

Steam or another process may have read its files in the background.
Small entries are collapsed under **Small fragments**.
See [Everyday use](Daily-Use.md) for the attribution limits.

## Cache is empty after a forced shutdown

A valid clean-shutdown seal is required for reuse. If it is missing or no longer matches,
the cache starts cold. The original game files remain on HDD.

## Steam temporarily shows no installed games

Do not format a drive or reinstall games. Close the game and check that the library drive
is mounted and listed in Steam Storage. Restart Steam after a storage-path change.
If the issue persists, leave the disks intact and collect the service log.

## Getting useful logs

In Desktop Mode:

```sh
uname -r
systemctl status deckycache.service
journalctl -b -u deckycache.service --no-pager
```

Include the plugin version and the exact error when reporting a problem.
Redact personal paths and drive serial numbers before sharing logs or screenshots.
