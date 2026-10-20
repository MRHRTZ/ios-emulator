# Windows desktop GUI

From the repository root, with the already prepared iOS root and matching local
kernel (0084+ for input, 0085+ for live serial, 0087+ for multicore/RTC):

```powershell
python -m pip install -r requirements.txt
python emulator.py gui
```

`gui --no-start` opens the controls first. This is a Python/Qt desktop window;
the single-application distribution/installer is a later milestone.

The English interface uses native Qt Windows controls, menus, settings and file
dialogs, with a dark icon sidebar. Sidebar labels appear on hover; the touch
display never shows a tooltip. Click for touch, drag to swipe, and type using
the iOS on-screen keyboard. Kernel 0091 adds PC keyboard capture: click the
iOS display to focus it, and toggle the keyboard sidebar button. Focus loss,
Pause and Stop release held keys. Current mapping covers a US physical layout;
Windows printable ASCII text packets are converted to US-layout HID strokes.
Ctrl+V pastes up to 4096 printable ASCII characters from the host clipboard;
non-ASCII or oversized pastes show a status message without partial insertion.
IME/composed non-ASCII text is not implemented.

| Control | Shortcut |
| --- | --- |
| Home / unlock | F1 |
| Recent apps | Sidebar Apps button |
| Power / lock | F2 |
| Hardware Home compatibility key | F6 |
| Volume down / up | F3 / F4 |
| Pause / Resume | Ctrl+P |
| Save screenshot | Ctrl+S |
| Rotate display | Ctrl+R |
| Fullscreen | F11 |
| Restart | F5 |

Stop the emulator before changing CPU, RAM, or refresh target. Resource limits
follow host capacity (80% budget) and the guest cap: 4 GiB RAM / 4 CPUs.
The current kernel PC topology check rejects more than four CPUs; refresh targets are limited by the host display. ARM64 runs through TCG on x64; actual speed and FPS depend on host
load. Selecting more cores does not guarantee proportional speed increases.
The CPU, device tree and boot arguments are configured together.

Guest changes persist in `data/gui/ios-session.qcow2`; the base
`data/root/ios-root.img` stays clean. A disk lock prevents a second GUI writer.
Pause releases held input and waits for guest acknowledgment. Stop/Restart
flush QEMU's disk backend but currently cut guest power: they are not an
orderly iOS shutdown. The HFS journal is replayed on the next boot.

Logs and diagnostic metadata live in `data/gui/runs/<timestamp>/`; logs are
available through the Logs sidebar toggle. The current session is described by
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
IPv6 DNS and remote TLS data are verified; kernel0090 DHCP also assigns
10.0.2.15 and the default route. Safari webpage drawing remains unresolved. All three multicore spinlock policies use a finite
five-second timeout to accommodate TCG/frame-export scheduling.

For local network diagnosis only, set `IOS_EMULATOR_CAPTURE_NETWORK=1` before
starting the GUI to save guest packets to its run directory as `network.pcap`.
Captures are disabled by default and stay in ignored local runtime data.


## Window appearance

Emulator > Start / Pause / Stop / Restart owns the lifecycle controls; there
is no top control toolbar. Disabled commands and sidebar buttons are dimmed.
Logs is a checked icon immediately above Settings. View > Theme offers Auto,
Light and Dark, including the console. View > Show Status Bar defaults on and
persists. The compact status bar uses a spinner while loading and shows actual
frame-export FPS in the foreground theme color.

Stop immediately blanks the display and rejects queued frames while QEMU exits.
Automatic Home uses an edge swipe after a white/colored lock/home frame is detected,
avoiding an input during the initial black/Apple boot frame.

The loading spinner sits left of the status text with padding; the FPS field
has no separator. See [Safari rendering investigation](SAFARI_RENDERING.md).


## Display transport and pause

Kernel0092 publishes completed frame counters and copy timing in reserved input
protocol words. The host skips unchanged or in-flight frames. Older kernels
retain periodic framebuffer export. The FPS label counts host exports, not
guest animation updates or GPU performance; a static screen may show 0 FPS.
Paused sessions do not export frames and show 0 FPS.

Kernel0093 adds a capability-gated resume event that refreshes the guest calendar
from QEMU's host RTC. `live.json` includes guest UTC seconds, calendar lag and
any acknowledgment warning. Runtime validation is recorded in NOTES.md; the
presence of this capability alone is not proof of a successful clock test.

Hover over the FPS value for the capture target, newly captured frames, guest
presentation rate (kernel0092+), and last frame-export time. Diagnostics also
include exported frame totals, skipped unchanged frames, held-input count and
ring backlog. A presentation is a completed guest framebuffer copy, not a GPU
benchmark or proof of unique animated content.

Kernel0094 introduces **Emulator > Shut Down iOS**, enabled only when the guest
advertises support. XNU stops processes, syncs and unmounts filesystems before
QEMU's PSCI power off. The GUI waits for a successful exit and platform-halt log;
implementation availability does not replace runtime/filesystem verification.
**Force Stop** remains a power cut. If orderly shutdown takes more than two
minutes, the GUI leaves the session available for diagnostics or Force Stop.
