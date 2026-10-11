# <img src="images/deckycache-icon.svg" width="34" height="34" alt=""> DeckyCache

![DeckyCache: SSD / NVMe cache for SteamOS](images/deckycache-cover.png)

## Check compatibility before installing

| Requirement | Current bundle |
| --- | --- |
| **Supported SteamOS channel** | **Stable only**. Beta, Preview and Main are not supported. |
| **Tested SteamOS** | **3.8.28**, build **20260922.1**, on an NVIDIA x86-64 PC |
| **Required kernel** | `6.18.50-valve2-1-neptune-618-gc7289a96b14d` |
| **Library drives** | Separate **ext4 data partitions** |
| **Tested Decky Loader** | **3.2.10** |

**Check `uname -r` in Desktop Mode before installing. The kernel must match exactly.**
The SteamOS version alone is not enough: an update may change the kernel.
This plugin does not rebuild or replace it; another kernel needs a matching module bundle.

[Full compatibility and update information](docs/guide/Compatibility.md)

**Keep your games on the HDD. Cache the data you use on an SSD or NVMe.**

DeckyCache is a Decky Loader plugin for SteamOS PC. Choose a dedicated cache drive,
switch on the library drives you want to cache, and play. Open CAS stores accessed
blocks on the faster drive while the original games and Steam updates stay on the HDD.

[Install](docs/guide/Installation.md) · [First setup](docs/guide/Setup.md) · [User guide](docs/guide/Home.md) · [Compatibility](docs/guide/Compatibility.md)

## What you get

- **Choose an SSD or NVMe:** format a dedicated drive or reuse one prepared by DeckyCache.
- **Choose library drives:** enable one or several supported game-drive partitions.
- **Choose cache scope:** cache reads across those drives or restrict new cached data to selected Steam, DRM-free or ROM folders.
- **Master switch:** temporarily bypass cache while keeping your drive selections and valid cached blocks.
- **Compatible updates:** check GitHub for a release matching the running kernel, then install through Decky with an automatic plugin reload. The built-in updater keeps compatible cache and library mounts connected.
- **Persistent cache:** cached blocks survive a clean shutdown and restart.
- **Original games stay on the HDD:** writes, including game updates, go to the original drive. New cache blocks come from reads within the selected drives or folders; writes do not allocate new cache blocks.
- **Cached games:** Steam games and direct non-Steam shortcuts, with existing Steam artwork and attributed cache sizes. Tiny entries appear under **Small fragments**.
- **Other cached data:** the final tile accounts for occupied cache outside the displayed game entries.
- **Clear cache:** remove cached copies without formatting the NVMe or deleting games.
- **A compact controller-friendly panel:** short labels, section dividers and details behind information buttons.

![DeckyCache with the master switch, update button and cached games](docs/images/cached-games.jpg)

## Download and install

**Download the DeckyCache plugin ZIP from this repository's Releases.**
Choose the attached plugin ZIP, not the automatically generated source-code archive.

1. Open **Decky Loader settings → General** and enable **Developer mode**.
2. Open **Developer → Install Plugin from ZIP File → Browse** and choose the downloaded ZIP.
3. Alternatively, copy the plugin ZIP's direct download link from the release and paste it into
   **Install Plugin from URL**, then select **Install**.
4. Open **DeckyCache** from the Decky menu.

See the [illustrated installation guide](docs/guide/Installation.md) for screenshots.
A download that requires signing in should be installed from the local ZIP.

For later updates, use **Check for updates** in DeckyCache, select the offered version and
confirm Decky's installer. The plugin reloads automatically. See [Updating the plugin](docs/guide/Installation.md#updating-the-plugin).

## First setup

1. Close games and let Steam downloads or updates finish.
2. In **Cache drive**, select your dedicated SSD/NVMe.
3. Choose **Format and use** for a new cache drive, or **Reuse existing cache** for a drive already prepared by DeckyCache.
4. Enable the desired partitions under **Library drives**.
5. Under **Cache scope**, keep **Entire selected drives** or choose **Selected folders** and add the folders you want.
6. Start a game. Eligible reads fill cache; installation and update writes do not allocate new cache blocks.

**Format and use erases the entire selected cache drive.** Check its model, size and
serial number before confirming. The library HDD is not formatted or moved.
See [First setup](docs/guide/Setup.md).

## What gets cached

Choose **Entire selected drives** for all eligible reads on the enabled partitions, or
**Selected folders** for specific libraries. Add several folders across enabled drives as needed.
Writes from copying, installation and Steam updates go to the HDD without allocating new cache blocks.
Reads for copying, unpacking or verification can still fill cache within the selected scope.
This is a folder filter, not a detector of whether a game is running.

![Selected cache folders with separated controls and the Other cached data tile](docs/images/cache-folders.png)

Changing scope keeps existing cached data. **Other cached data** accounts for cached blocks outside
the current game list, including data retained from earlier versions. Use **Clear cache** if you want
to discard those copies; games on the HDD stay intact.

There is no pinning, full-game preloading or per-game eviction. Game sizes are partial attribution,
not proof that every byte of a game is cached. Directory rules cannot identify every direct or
asynchronous read; unidentified reads bypass cache in folder mode.

[Compatibility and updates](docs/guide/Compatibility.md) · [How it works](docs/guide/How-It-Works.md) · [Troubleshooting](docs/guide/Troubleshooting.md)

## Build from source

```sh
cd plugin
npm ci
npm run typecheck
npm run build
cd ..
python3 scripts/package.py
```

Before packaging, prepare the matching Open CAS binaries as described in
[the bundle build guide](scripts/README-opencas-build.md). Packaging produces
`build/DeckyCache-<version>.zip` with the runtime, required licenses and offline user guide.

## License

The plugin uses the [BSD 3-Clause license](LICENSE). The release includes Open CAS,
OCF and safeclib license notices and an upstream source reference in `bin/opencas`.
