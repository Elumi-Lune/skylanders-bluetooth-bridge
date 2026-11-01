# Skylanders Bluetooth Bridge (English overview)

Unofficial Windows bridge for the **Skylanders Trap Team tablet Bluetooth portal** and its small BLE controller, using a compatible **VirtPort-modified Cemu** build. The bridge reads physical NFC tags, exports local `.sky` data, and triggers real-time in-game summoning through VirtPort's localhost API. Virtual gamepad support uses an **optional** external driver.

**Status:** Community beta. Physical portal, controller, fullscreen and live swaps have been demonstrated on one Windows setup with an earlier V4 branch. This 4.3 SafeSync publication has offline regression tests; it still needs wider hardware testing.

**No game files, third-party emulators, drivers, firmware or user NFC dumps are included.** The bridge never writes to a physical NFC tag; only the BLE command used to *request reads* is sent to the portal. Player progression is saved into local virtual `.sky` files, not back to original toys.

For the complete setup, see [README (French)](README.md) and [Installation (French)](docs/INSTALLATION_FR.md). Dependencies: Windows 10/11, Python 3.10+, BLE adapter, VirtPort-modified Cemu, optional `vgamepad` and its legacy driver.

This is an independent fan project, not associated with Activision, Toys for Bob, Cemu or VirtPort.
