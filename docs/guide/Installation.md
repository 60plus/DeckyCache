# Install DeckyCache

## Before you start

| Requirement | Current bundle |
| --- | --- |
| **Tested SteamOS** | **3.8.28**, build **20260922.1**, on an NVIDIA x86-64 PC |
| **Required kernel** | `6.18.50-valve2-1-neptune-618-gc7289a96b14d` |
| **Library drives** | Separate **ext4 data partitions** |
| **Tested Decky Loader** | **3.2.10** |

**Check `uname -r` in Desktop Mode before installing. The kernel must match exactly.**
The SteamOS version alone is not enough: an update may change the kernel.
This plugin does not rebuild or replace it; another kernel needs a matching module bundle.

[Full compatibility and update information](Compatibility.md)

You need SteamOS PC, a working [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)
installation and a supported kernel. Read [Compatibility](Compatibility.md) before preparing a drive.
Installing the plugin alone does not format a disk or enable caching.

## 1. Download the plugin ZIP

**Download the plugin ZIP from this repository's Releases.**

Choose the attached **DeckyCache plugin ZIP**. Its filename starts with `DeckyCache-`.
Do not choose **Source code (zip)** or **Source code (tar.gz)**; those are not installable Decky packages.
Save the ZIP somewhere accessible on the SteamOS PC, such as Downloads. Do not extract it.

If you download on another computer, copy the ZIP to the SteamOS PC first.

## 2. Enable Decky's Developer mode

Open the Steam quick-access menu, select **Decky**, then open its **settings**.

In **General**, scroll to **Other** and switch **Developer mode** on.
This is Decky Loader's setting.

![Enable Developer mode in Decky Loader settings](../images/decky-developer-mode.jpg)

## 3. Install from a file or a link

Open **Developer** in Decky's settings sidebar.

![Decky Developer settings with ZIP and URL installation](../images/decky-install-options.jpg)

### Option A: downloaded ZIP

1. Under **Install Plugin from ZIP File**, select **Browse**.
2. Find and select the downloaded DeckyCache ZIP.
3. Accept Decky's installation prompt and wait for installation to finish.

### Option B: direct ZIP download link

1. In this repository's release, copy the download link for the attached **plugin ZIP**.
2. Paste it into **Install Plugin from URL**.
3. Select **Install** and accept the installation prompt.

Use the direct file link, not the release page or repository address.
If the download requires a browser login, use **Option A**; Decky does not inherit that browser session.

## 4. Open the plugin

Return to the Decky menu and open **DeckyCache**.
Continue with [First setup](Setup.md) to select the cache drive and library partitions.

To install a later plugin release, close games and finish Steam updates, then use the
new release's plugin ZIP through the same Developer screen.
Check its supported kernel before installing.
