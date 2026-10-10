# <img src="../../images/deckycache-icon.svg" width="34" height="34" alt=""> DeckyCache user guide

![DeckyCache](../../images/deckycache-cover.png)

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

[Full compatibility and update information](Compatibility.md)

DeckyCache puts an SSD or NVMe cache in front of selected game-drive partitions.
Original games stay on the HDD. The panel handles drive preparation, library selection
and clearing cached copies.

| Start here | What it covers |
| --- | --- |
| [Installation](Installation.md) | Download the plugin ZIP and install it through Decky Developer settings. |
| [First setup](Setup.md) | Select, format or reuse the cache drive; enable library drives. |
| [Everyday use](Daily-Use.md) | Cached games, small fragments, clearing cache and Steam updates. |
| [Compatibility](Compatibility.md) | Supported filesystem, exact kernel bundle and update requirements. |
| [Troubleshooting](Troubleshooting.md) | Missing drives, game list entries and cache readings. |
| [Uninstalling](Uninstalling.md) | Return to direct HDD access and remove the plugin. |
| [How it works](How-It-Works.md) | Open CAS, persistent blocks and the limits of game attribution. |

**Current build:** Open CAS writethrough caching. No pinning, folder filters or full-game copies.
