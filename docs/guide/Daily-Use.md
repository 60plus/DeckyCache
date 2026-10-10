# Everyday use

## The main panel

![Cache usage, library switch and cached game tiles](../images/cached-games.jpg)

- **Cache drive:** selected SSD/NVMe, active partition count and occupied cache space.
- **Library drives:** one on/off switch per eligible partition.
- **Cached games:** Steam artwork, names and attributed cache sizes.
- **Information buttons:** details without filling the main panel with text.

You normally leave the selected library drives enabled and launch games as usual.

## Cached games and Small fragments

The main list shows installation folders with at least **16 MiB** of attributed cache data.
Smaller nonzero entries are grouped under **Small fragments**. Expand it to see them.
This is a display threshold; it does not delete or disable small cached entries.

Select a game tile for details. Games that share one installation folder are grouped together.

A background Steam read can add a game that you have not launched. The size is **partial attribution**,
not the installation size, a full-game copy or an exact inventory of current game files.
Unclassified reads still use cache and are included in the drive's total.
[How it works](How-It-Works.md) explains the limits.

## Clear cache

Choose **Clear cache**, then confirm.

This removes cached copies for all selected active library partitions. It keeps the games on the HDD,
the prepared NVMe filesystem and your drive selection. It does not format the SSD or unmount libraries.
New reads and writes may refill the cache immediately, so it may not stay at zero.

There is no per-game clear operation in this release.

## Steam updates

Update games normally in Steam. DeckyCache uses **writethrough**:
writes go to the original HDD through Open CAS, which keeps cached data coherent.
There is one original installation, not an independently updated SSD copy.

Wait for downloads and updates to finish before changing cache drives, changing library selection
or uninstalling the plugin.

## Restart and shutdown

Use the normal Steam restart or shutdown controls. A clean shutdown saves the state needed to
reuse cached blocks at the next start. A forced power-off, incompatible saved state or writes to the
HDD outside the cache can cause a cold cache rebuild.

Cache may serve few reads when Linux already has those files in RAM. That is expected.
