# Windows desktop GUI

From the repository root, with the already prepared iOS root and matching local
kernel (0084+ for input, 0085+ for live serial, 0087+ for multicore/RTC):

```powershell
python -m pip install PySide6
python emulator.py gui
```

`gui --no-start` opens the controls first. This is a Python/Qt desktop window;
the single-application distribution/installer is a later milestone.

The English interface uses native Qt Windows controls, menus, settings and file
dialogs, with a dark icon sidebar. Sidebar labels appear on hover; the touch
display never shows a tooltip. Click for touch, drag to swipe, and type using
the iOS on-screen keyboard. Host text typing is not bridged yet.

| Control | Shortcut |
| --- | --- |
| Home / unlock | F1 or Esc |
| Recent apps | Sidebar Apps button |
| Power / lock | F2 |
| Hardware Home compatibility key | F6 |
| Volume down / up | F3 / F4 |
| Pause / Resume | Ctrl+P |
| Save screenshot | Ctrl+S |
| Rotate display | Ctrl+R |
| Fullscreen | F11 |
| Restart | F5 |

Stop the emulator before changing CPU (1/2/4), RAM (1–4 GiB), or refresh target
(5–30 fps). ARM64 runs through TCG on x64; actual speed and FPS depend on host
load. Selecting more cores does not guarantee proportional speed increases.
The CPU, device tree and boot arguments are configured together.

Guest changes persist in `data/gui/ios-session.qcow2`; the base
`data/root/ios-root.img` stays clean. A disk lock prevents a second GUI writer.
Pause releases held input and waits for guest acknowledgment. Stop/Restart
flush QEMU's disk backend but currently cut guest power: they are not an
orderly iOS shutdown. The HFS journal is replayed on the next boot.

Logs and diagnostic metadata live in `data/gui/runs/<timestamp>/`; logs are
available in the toolbar. The current session is described by
`data/gui/active.json` (check the PID before assuming it is still active).

RTC uses QEMU's host UTC clock. Guest timezone settings can change the displayed
hour. Kernels with 0088 automatically receive an outbound virtio Ethernet/NAT
adapter in the GUI. Adapter creation alone does not prove internet access;
DHCP/configd, default route, DNS and Safari must be validated separately.
No inbound forwarding or TAP adapter is configured.

Real home/search/on-screen keyboard/Home input were visually verified with
one CPU. Kernel smoke tests pass with 2/4 CPUs; real Apple launchd and
SpringBoard execution were observed with four CPUs and current-day timestamps.
A four-core home screen and hardware Home/unlock were subsequently verified.
IPv6 DNS and remote TLS data are verified; Safari rendering and IPv4 DHCP
remain under validation. All three multicore spinlock policies use a finite
five-second timeout to accommodate TCG/frame-export scheduling.

For local network diagnosis only, set `IOS_EMULATOR_CAPTURE_NETWORK=1` before
starting the GUI to save guest packets to its run directory as `network.pcap`.
Captures are disabled by default and stay in ignored local runtime data.
