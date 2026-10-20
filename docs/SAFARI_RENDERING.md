# Safari white-page investigation

Snapshot: 2026-10-20. This is an experimental iOS16.7.16 guest, not a stock
Apple-supported device or simulator. Webpage rendering is not fixed yet.

## Observations

Safari chrome, address entry and search suggestions draw. On-page search can
find text while the webpage area remains white. Earlier captures confirmed
example.com HTTP200 and decoded HTML; receipt alone does not prove painting.
Settings can display normally after waiting for its initial launch.

## Relevant upstream evidence

- [WebKit bug247483](https://bugs.webkit.org/show_bug.cgi?id=247483): an iOS16
  reporter saw a white canvas and reported that disabling GPU Process: DOM
  Rendering helped. The issue is unresolved; this does not establish that our
  entire-page problem has the same cause.
- [WebKit bug236508](https://bugs.webkit.org/show_bug.cgi?id=236508): GPU
  Process DOM rendering was enabled for iOS in March2022.
- [WebKit contributor meeting2022](https://docs.webkit.org/Other/Contributor%20Meetings/ContributorMeeting2022.html):
  DOM rendering, graphics contexts and IOSurface exchange cross process boundaries.

A working framebuffer does not imply complete IOSurface or GPU support.
The current SweetSurface implementation still accepts several property,
ownership and notification operations as no-ops. Vulkan/OpenGL host display
selection alone cannot complete these guest interfaces.

## Controlled preference tests

1. WebKitDebugAcceleratedDrawingEnabled=false: tried; white pages persisted.
   Backups are stored beside each guest Safari preferences file with the suffix
   .before-software-render.plist.
2. WebKitExperimentalUseGPUProcessForDOMRenderingEnabled=false: applied offline
   to mobile and Safari-container preferences on2026-10-20. Original value was
   absent in both. SafariShared's guest binary exposes the WebKitExperimental%@
   preference-name pattern. Backup suffix: .before-dom-render.plist, including
   prior file existence and preferences. After restart, example.com remained white while Safari showed Reader Available.
   Effective runtime feature value is still unverified; this experiment has not
   fixed the problem. The local data-HTML test was not submitted because host
   text-packet input had no visible effect.

Only the second named feature was changed in the new experiment. It is not a
confirmed fix or a supported application default. Preserve backups for reversal.
The writable guest overlay was locked and QEMU stopped before editing. The
immutable base and Apple firmware were not changed or uploaded.

## Next checks

Compare a simple local/data HTML page and public example.com after the new
boot; verify the flag actually took effect. If still blank, inspect WebKit GPU
process health, shared surfaces, property exchange and drawing/compositing.
Avoid broad cache deletion or unrelated security/privacy changes.
