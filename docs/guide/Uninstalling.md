# Remove DeckyCache

1. Close games and wait for Steam downloads or updates to finish.
2. Open DeckyCache and switch off every entry under **Library drives**.
3. Wait for the operation to finish. The original HDD libraries should remain available.
4. Open **Decky Loader settings → Plugins** and uninstall **DeckyCache**.

The master **Enable DeckyCache** switch alone only bypasses caching; it does not detach the drive.
Use the individual **Library drives** switches for removal.

If disabling a library reports that the drive is busy, resolve that message before removing the plugin.
Do not delete plugin files manually while its cache device is active.

The uninstall handler stops and removes its service and managed automount/shutdown-ordering rules
when detachment succeeds. It does not delete games from the HDD.
The prepared SSD filesystem remains; repurposing or formatting it is a separate operation.

The plugin does not replace the kernel or install a global Open CAS service.
