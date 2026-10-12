import json
import time
import re
import urllib.parse
from typing import List, Dict, Any, Optional, Tuple
from bridge.opera_cdp import OperaCDPClient

class BrowserClient(OperaCDPClient):
    """
    Enhanced CDP Client supporting both Microsoft Edge and Opera GX,
    with public IP detection, bulk inventory synchronization, and robust error recovery.
    """

    def __init__(self, port: int, concurrency: int = 12, query_interval_ms: int = 300, proxy: Optional[str] = None):
        super().__init__(port=port, concurrency=concurrency, query_interval_ms=query_interval_ms)
        self.proxy = proxy
        self.public_ip: Optional[str] = None

    def inject_bridge(self):
        """Injects persistent iframe pool, stream pipeline, and bulk sync helpers."""
        super().inject_bridge()
        
        # Inject bulk synchronization function for ultra-fast multi-item sync
        bulk_sync_js = """
        (() => {
            window.__IC_sync_items_bulk = function(itemsList) {
                if (!itemsList || !Array.isArray(itemsList) || itemsList.length === 0) return 0;
                let vueInst = document.querySelector('.container')?.__vue__;
                if (!vueInst || !vueInst.items) return -1;

                let existingMap = new Set();
                for (let i = 0; i < vueInst.items.length; i++) {
                    existingMap.add(vueInst.items[i].text.toLowerCase());
                }

                let addedCount = 0;
                for (let i = 0; i < itemsList.length; i++) {
                    let itm = itemsList[i];
                    let name = itm.text || itm.name;
                    if (!name) continue;
                    let lower = name.toLowerCase();
                    if (!existingMap.has(lower)) {
                        existingMap.add(lower);
                        vueInst.items.push({
                            id: vueInst.items.length,
                            saveId: vueInst.currSave,
                            text: name,
                            emoji: itm.emoji || '✨',
                            discovered: !!itm.discovered,
                            recipes: itm.recipes || []
                        });
                        addedCount++;
                    }
                }

                if (addedCount > 0) {
                    if (vueInst.currSaveData) {
                        vueInst.currSaveData.numItems += addedCount;
                    }
                    try { window.dispatchEvent(new Event('storage')); } catch(e) {}
                }
                return addedCount;
            };
            return true;
        })()
        """
        try:
            self.eval_js(bulk_sync_js)
        except Exception:
            pass

    def detect_public_ip(self, timeout: float = 8.0) -> str:
        """
        Detects the public IP address used by this browser session by executing
        a fetch from within the browser page context. If it times out or fails,
        falls back to extracting the IP from the configured proxy.
        """
        proxy_ip = None
        if self.proxy and isinstance(self.proxy, str) and self.proxy.strip():
            try:
                parsed = urllib.parse.urlparse(self.proxy.strip())
                proxy_ip = parsed.hostname
            except Exception:
                pass

        detect_js = """
        (async () => {
            const endpoints = [
                'https://api.ipify.org?format=json',
                'https://icanhazip.com',
                'https://api.my-ip.io/v2/ip.txt'
            ];
            for (let ep of endpoints) {
                try {
                    let res = await fetch(ep, { signal: AbortSignal.timeout(4000) });
                    let text = await res.text();
                    let match = text.match(/\\b\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\b/);
                    if (match) return match[0];
                } catch(e) {}
            }
            return null;
        })()
        """
        try:
            ip = self.eval_js(detect_js, await_promise=True, timeout=timeout)
            if ip and isinstance(ip, str) and re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip.strip()):
                self.public_ip = ip.strip()
                return self.public_ip
        except Exception:
            pass

        if proxy_ip:
            self.public_ip = proxy_ip
        else:
            self.public_ip = "Direct (Home ISP)"
        return self.public_ip

    def sync_inventory_bulk(self, items: List[Dict[str, Any]]) -> int:
        """Synchronizes an array of items into the browser's save state in one quick operation."""
        if not items:
            return 0
        items_json = json.dumps(items)
        call_js = f"window.__IC_sync_items_bulk({items_json})"
        try:
            added = self.eval_js(call_js, timeout=10.0)
            return int(added) if added is not None and added >= 0 else 0
        except Exception:
            return 0
