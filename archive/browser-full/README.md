# The full-engine browser build (preserved)

This directory holds the previous browser deployment: the whole Epsilon
engine compiled into a wheel, installed into Pyodide with micropip, with
`bridge.py` answering the same REST surface the local server does and
`vfs.js` standing in for the workspace filesystem. It served the pane
workbench in `epsilon/server/static/`.

It is kept, not deleted. Nothing here is dead code to clean up: the
workbench it served is still the local build (`epsilon serve`), and this
shell is how that same workbench reaches a browser with no install. It
comes back when the light build has earned the weight.

**Why the deploy moved off it.** The wheel plus micropip plus the engine
import made a first visit slow, and every language-service call crossed
into Python on the page's only thread — which is where the typing lag
came from. The build now at `web/` runs Python and nothing else: no
wheel, no bridge, no micropip.

    boot.js     Pyodide + micropip + the wheel, then the fetch shim
    bridge.py   the engine's REST surface, in-browser
    vfs.js      the workspace as a localStorage map
    web.css     web-only overrides over the workbench stylesheet
    shell/      the boot overlay spliced into the shared markup
