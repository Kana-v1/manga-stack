# Expected configuration

`tools/doctor.ts` compares the live server with the `expected` block below: `server.*`
keys against `<data>/server.conf` (a `webUI_*` key would be checked against the global
metadata, but there are none since the WebUI was removed). `<project>`
stands for the project root, so the line survives moving the project. A `  #` comment
after a value is ignored.

```expected
server.ip = "0.0.0.0"                    # home network: the firewall admits 192.168.0.0/24 only (server-ops)
server.webUIFlavor = "CUSTOM"            # serve Tsumiru from <data>/webUI
server.webUIUpdateCheckInterval = 0.0    # must stay 0 on CUSTOM
server.excludeUnreadChapters = false     # true SKIPS titles with unread chapters on update
server.globalUpdateInterval = 6.0        # 6.0 is the floor
server.backupPath = "<project>/backups"
server.backupTTL = 60
server.extensionStores = ["https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.pb"]
server.systemTrayEnabled = false         # no tray on a Linux server; scripts/ manage it
server.initialOpenInBrowserEnabled = false  # scripts/start.ts opens the browser itself
```

Left at defaults on purpose: `webUIInterface = BROWSER`,
`authMode = NONE` (no login: the Windows firewall keeps the port to the home network), `autoDownloadNewChapters = false` (no
local files wanted. The cost is no page cache), `databaseType = H2`, `kcefEnabled = true`
(some extensions need a WebView), `flareSolverrEnabled = false` (turn on only if a source
gets Cloudflared).

`server.backupPath` is the one value tied to where the project lives. After moving the
project, set it again with `setSettings`.
