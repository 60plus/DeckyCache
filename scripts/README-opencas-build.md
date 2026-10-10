# Exact-kernel Open CAS bundle

The release uses upstream Open CAS 26.09.0.1102.release, unmodified engine code.
Source: https://github.com/Open-CAS/open-cas-linux/releases/download/v26.09/open-cas-linux-26.09.0.1102.release.tar.gz
Archive SHA256: fd487876dab5272e0c219e0ea849668b0811965f02f03079fc98380a59a27529.

The current tested kernel is 6.18.50-valve2-1-neptune-618-gc7289a96b14d.
Valve header package linux-neptune-618-headers-6.18.50.valve2-1-x86_64.pkg.tar.zst
has SHA256 67761632fc6b583b73f4dc912933fac758e660b1502d9b4d822ff92501300a30.
Headers came from the configured jupiter-3.8 repository; GCC 15.1.1 and its development dependencies
were extracted to a private directory, not installed into SteamOS.

Build with the matching headers and compiler:
    ./configure --kernel-dir /path/to/extracted/kernel/build
    make -C modules -j2 KERNEL_DIR=/path/to/extracted/kernel/build
    make -C casadm -j2

The configure script's /usr/include/libelf.h existence check must point at the private libelf.h when using an isolated toolchain.
Set PATH, C_INCLUDE_PATH, LIBRARY_PATH and LD_LIBRARY_PATH to the private toolchain as needed.
Do not run make install or replace the kernel.

Package layout:
    plugin/bin/opencas/casadm
    plugin/bin/opencas/<uname-r>/cas_bd.ko
    plugin/bin/opencas/<uname-r>/cas_cache.ko
    plugin/bin/opencas/<uname-r>/manifest.json
    plugin/bin/opencas/LICENSE.OpenCAS
    plugin/bin/opencas/LICENSE.OCF
    plugin/bin/opencas/LICENSE.safeclib
    plugin/bin/opencas/SOURCE.txt

manifest.json contains kernel, version and sha256 (casadm, cas_bd.ko, cas_cache.ko).
Binary files are ignored in Git but included by scripts/package.py, which requires a bundle.
A future kernel needs a separately built matching bundle; there is no automatic compiler download or kernel rebuild.

The adapter smoke check must be run as root in the host mount namespace with the staged plugin directory on PYTHONPATH.
It creates only private disposable images. Never substitute the user's devices for its loop-backed origin.


## Release metadata for the in-plugin updater

The packaging script also writes `SHA256SUMS` and `deckycache-update.json`.
For releases that include the updater, attach all three files to the same
GitHub release: the plugin ZIP, `SHA256SUMS` and `deckycache-update.json`.

The update manifest lists the exact supported kernels and the ZIP SHA256.
Only SteamOS Stable is supported. A stable release must use a numeric
`major.minor.patch` version and a matching `v` tag, and must not be a GitHub
prerelease. Development builds are not offered by the updater.
Never edit a published ZIP in place; publish a newer version when adding a
kernel bundle. Keep the prior bundles if the new plugin still supports them.

The initial 0.4.4 release does not have an in-plugin updater. Install a
release containing that feature through Decky's ZIP installer once.
