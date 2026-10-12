import json
import time
import urllib.request
import urllib.parse
from typing import List, Dict, Any, Optional, Tuple
import websocket

class OperaCDPClient:
    def __init__(self, port: int = 9223, concurrency: int = 25, query_interval_ms: int = 300):
        self.port = port
        self.concurrency = concurrency
        self.query_interval_ms = query_interval_ms
        self.base_http = f"http://127.0.0.1:{self.port}"
        self.ws: Optional[websocket.WebSocket] = None
        self.tab_id: Optional[str] = None
        self.ws_url: Optional[str] = None
        self._msg_id = 0

    def set_pacing(self, interval_ms: int):
        """Dynamically adjusts inter-query spacing."""
        self.query_interval_ms = max(50, interval_ms)
        try:
            self.eval_js(f"if (window.__IC_set_interval) window.__IC_set_interval({self.query_interval_ms});")
        except Exception:
            pass

    def reset_worker_pool(self):
        """Flushes all queued tasks and resets iframe workers to about:blank."""
        reset_js = """
        (() => {
            if (window.__IC_workers) {
                for (let i = 0; i < window.__IC_workers.length; i++) {
                    let w = window.__IC_workers[i];
                    if (w.timer) clearTimeout(w.timer);
                    w.busy = false;
                    w.task = null;
                    try { w.iframe.src = 'about:blank'; } catch(e) {}
                }
            }
            window.__IC_queue = [];
            window.__IC_stream_results = [];
            return true;
        })()
        """
        try:
            self.eval_js(reset_js, timeout=5.0)
        except Exception:
            pass

    def reload_page(self, wait_sec: float = 3.0) -> bool:
        """Reloads the Infinite Craft tab, waits for load, and re-injects bridge."""
        try:
            self.reset_worker_pool()
            self.send_cmd("Page.reload", {"ignoreCache": True}, timeout=10.0)
            time.sleep(wait_sec)
            self.handle_cloudflare_if_needed()
            self.inject_bridge()
            return True
        except Exception as e:
            try:
                self.send_cmd("Page.navigate", {"url": "https://neal.fun/infinite-craft/"}, timeout=10.0)
                time.sleep(wait_sec)
                self.handle_cloudflare_if_needed()
                self.inject_bridge()
                return True
            except Exception as e2:
                print(f"⚠️ Page reload error: {e2}")
                return False

    def probe_query(self, first: str, second: str, timeout: float = 12.0) -> Dict[str, Any]:
        """Sends a single probe query to test server connectivity without batch flooding."""
        self.handle_cloudflare_if_needed()
        res = self.batch_query_pairs([(first, second)], timeout=timeout)
        if res and len(res) > 0:
            return res[0]
        return {"error": "no_response"}

    def connect(self) -> bool:
        """Connects to Opera and attaches to the Infinite Craft tab."""
        self.tab_id, self.ws_url = self._find_or_open_tab()
        if not self.ws_url:
            raise RuntimeError("Could not find or open Infinite Craft tab in Opera.")

        self.ws = websocket.create_connection(self.ws_url, suppress_origin=True, timeout=12)
        self.handle_cloudflare_if_needed()
        self.inject_bridge()
        return True

    def _find_or_open_tab(self) -> Tuple[str, str]:
        """Finds an existing Infinite Craft tab or opens a new one."""
        req = urllib.request.Request(f"{self.base_http}/json")
        try:
            with urllib.request.urlopen(req) as resp:
                tabs = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Opera on port {self.port}: {e}")

        # Search for infinite-craft tab
        for tab in tabs:
            url = tab.get('url', '')
            if 'neal.fun/infinite-craft' in url and tab.get('type') == 'page':
                return tab['id'], tab['webSocketDebuggerUrl']

        # Not found, open new tab
        target_url = "https://neal.fun/infinite-craft/"
        req_new = urllib.request.Request(f"{self.base_http}/json/new?{target_url}", method='PUT')
        with urllib.request.urlopen(req_new) as resp:
            new_tab = json.loads(resp.read().decode('utf-8'))
            time.sleep(2.5)
            return new_tab['id'], new_tab['webSocketDebuggerUrl']

    def send_cmd(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 15.0) -> Dict[str, Any]:
        """Sends a CDP command and waits synchronously for its specific response."""
        if not self.ws:
            raise ConnectionError("WebSocket is not connected.")

        self._msg_id += 1
        req_id = self._msg_id
        payload = {"id": req_id, "method": method}
        if params is not None:
            payload["params"] = params

        self.ws.send(json.dumps(payload))
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                self.ws.settimeout(timeout - (time.time() - start_time))
                raw = self.ws.recv()
                msg = json.loads(raw)
                if msg.get("id") == req_id:
                    if "error" in msg:
                        raise RuntimeError(f"CDP command {method} failed: {msg['error']}")
                    return msg.get("result", {})
            except websocket.WebSocketTimeoutException:
                break
        
        raise TimeoutError(f"CDP command {method} timed out after {timeout}s")

    def eval_js(self, expression: str, await_promise: bool = False, timeout: float = 25.0) -> Any:
        """Evaluates JavaScript expression in page context."""
        res = self.send_cmd("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": await_promise,
            "returnByValue": True
        }, timeout=timeout)
        val_obj = res.get("result", {})
        if val_obj.get("subtype") == "error":
            raise RuntimeError(f"JS evaluation error: {val_obj.get('description')}")
        return val_obj.get("value")

    def bring_to_front(self):
        try:
            self.send_cmd("Page.bringToFront")
        except Exception:
            pass

    def handle_cloudflare_if_needed(self) -> bool:
        """Detects Cloudflare Turnstile challenge, recovers if navigated away, and solves challenge."""
        try:
            # 1. Recover if tab navigated away to cloudflare.com or error page
            cur_url = self.eval_js("window.location.href")
            if cur_url and "neal.fun/infinite-craft" not in cur_url:
                try:
                    self.send_cmd("Page.navigate", {"url": "https://neal.fun/infinite-craft/"}, timeout=10.0)
                    time.sleep(3.0)
                except Exception:
                    pass

            title = self.eval_js("document.title")
            # 2. Check if currently on Cloudflare challenge page
            if title in ("Just a moment...", "neal.fun", "Attention Required! | Cloudflare"):
                # Search for Turnstile checkbox container/iframe
                find_checkbox_js = """
                (() => {
                    let iframe = document.querySelector('iframe[src*="challenges.cloudflare.com"]') || document.querySelector('iframe');
                    if (iframe) {
                        let r = iframe.getBoundingClientRect();
                        return { x: Math.round(r.left + 30), y: Math.round(r.top + (r.height / 2)), found: true };
                    }
                    let stage = document.querySelector('#challenge-stage') || document.querySelector('#turnstile-wrapper');
                    if (stage) {
                        let r = stage.getBoundingClientRect();
                        return { x: Math.round(r.left + 30), y: Math.round(r.top + (r.height / 2)), found: true };
                    }
                    return { found: false };
                })()
                """
                cb_info = self.eval_js(find_checkbox_js)
                if cb_info and cb_info.get("found"):
                    x = cb_info["x"]
                    y = cb_info["y"]
                    # Click precisely inside the checkbox, never in footer branding links
                    self.send_cmd("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "none", "buttons": 0})
                    time.sleep(0.05)
                    self.send_cmd("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1})
                    time.sleep(0.05)
                    self.send_cmd("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "buttons": 0, "clickCount": 1})

                # Wait for challenge to resolve (up to 12s)
                start = time.time()
                while time.time() - start < 12.0:
                    time.sleep(1.0)
                    cur_title = self.eval_js("document.title")
                    cur_url = self.eval_js("window.location.href")
                    # If redirected to cloudflare.com branding link, steer back immediately!
                    if cur_url and "cloudflare.com" in cur_url and "neal.fun" not in cur_url:
                        self.send_cmd("Page.navigate", {"url": "https://neal.fun/infinite-craft/"})
                        time.sleep(2.5)
                    if cur_title == "Infinite Craft":
                        time.sleep(1.5)
                        self.inject_bridge()
                        return True
                return False
            return True
        except Exception:
            return False

    def inject_bridge(self):
        """Injects high-speed persistent iframe pool and continuous sliding queue pipeline."""
        # Cap pool size to prevent Chromium tab crashes
        safe_workers = min(max(self.concurrency, 4), 50)
        bridge_template = """
        (() => {
            // 1. Static Iframe Worker Pool Container (Hidden, zero DOM reflows)
            let poolContainer = document.getElementById('__ic_worker_pool');
            if (poolContainer) {
                poolContainer.innerHTML = '';
            } else {
                poolContainer = document.createElement('div');
                poolContainer.id = '__ic_worker_pool';
                poolContainer.style.cssText = 'display:none !important; position:absolute !important; width:0 !important; height:0 !important; pointer-events:none !important;';
                document.body.appendChild(poolContainer);
            }

            window.__IC_workers = [];
            window.__IC_queue = [];
            window.__IC_stream_results = [];

            // Rate governor: minimum spacing between queries across all workers
            let MIN_INTERVAL_MS = __QUERY_INTERVAL_MS__;
            let nextAllowedTime = 0;
            window.__IC_set_interval = function(ms) {
                MIN_INTERVAL_MS = ms;
            };

            function assignTask(worker, task) {
                worker.busy = true;
                worker.task = task;

                worker.timer = setTimeout(() => {
                    if (worker.busy && worker.task === task) {
                        worker.busy = false;
                        worker.task = null;
                        try { worker.iframe.src = 'about:blank'; } catch(e) {}
                        task.resolve({ first: task.first, second: task.second, error: 'timeout' });
                        window.__IC_dispatch();
                    }
                }, task.timeoutMs || 6000);

                let url = `https://neal.fun/api/infinite-craft/pair?first=${encodeURIComponent(task.first)}&second=${encodeURIComponent(task.second)}`;
                worker.iframe.src = url;
            }

            window.__IC_dispatch = function() {
                if (!window.__IC_queue || window.__IC_queue.length === 0) return;
                for (let i = 0; i < window.__IC_workers.length; i++) {
                    let worker = window.__IC_workers[i];
                    if (!worker.busy && window.__IC_queue.length > 0) {
                        let nextTask = window.__IC_queue.shift();
                        worker.busy = true;
                        worker.task = nextTask;

                        let now = Date.now();
                        let targetTime = Math.max(now, nextAllowedTime);
                        nextAllowedTime = targetTime + MIN_INTERVAL_MS;
                        let delay = targetTime - now;

                        if (delay <= 0) {
                            assignTask(worker, nextTask);
                        } else {
                            setTimeout(() => {
                                assignTask(worker, nextTask);
                            }, delay);
                        }
                    }
                    if (window.__IC_queue.length === 0) break;
                }
            };

            // Ensure static iframe pool has target worker count
            const targetWorkers = __SAFE_WORKERS__;
            while (window.__IC_workers.length < targetWorkers) {
                let workerId = window.__IC_workers.length;
                let iframe = document.createElement('iframe');
                iframe.id = `__ic_worker_${workerId}`;
                iframe.style.display = 'none';
                poolContainer.appendChild(iframe);

                let worker = {
                    id: workerId,
                    iframe: iframe,
                    busy: false,
                    task: null,
                    timer: null
                };

                iframe.onload = () => {
                    if (!worker.busy || !worker.task) return;
                    clearTimeout(worker.timer);
                    let task = worker.task;
                    worker.busy = false;
                    worker.task = null;
                    try {
                        let doc = iframe.contentDocument || iframe.contentWindow.document;
                        let text = doc.body ? doc.body.innerText : '';
                        
                        // Cloudflare rate-limit and challenge detection
                        if (text.includes("Error 1015") || text.includes("rate limited") || text.includes("Too Many Requests")) {
                            try { worker.iframe.src = 'about:blank'; } catch(e) {}
                            task.resolve({ first: task.first, second: task.second, error: 'rate_limit_1015' });
                        } else if (text.includes("Just a moment...") || text.includes("Turnstile")) {
                            task.resolve({ first: task.first, second: task.second, error: 'cloudflare_challenge' });
                        } else {
                            let data = JSON.parse(text);
                            task.resolve({ first: task.first, second: task.second, ...data });
                        }
                    } catch (err) {
                        task.resolve({ first: task.first, second: task.second, error: err.message });
                    }
                    window.__IC_dispatch();
                };

                iframe.onerror = () => {
                    if (!worker.busy || !worker.task) return;
                    clearTimeout(worker.timer);
                    let task = worker.task;
                    worker.busy = false;
                    worker.task = null;
                    task.resolve({ first: task.first, second: task.second, error: 'network_error' });
                    window.__IC_dispatch();
                };

                window.__IC_workers.push(worker);
            }

            // 2. High-speed batch query interface (reusing static pool)
            window.__IC_batch_query = function(pairs, timeoutMs = 5000) {
                if (!pairs || pairs.length === 0) return Promise.resolve([]);
                let promises = pairs.map(p => {
                    return new Promise((resolve) => {
                        window.__IC_queue.push({
                            first: p[0],
                            second: p[1],
                            timeoutMs: timeoutMs,
                            resolve: resolve
                        });
                    });
                });
                window.__IC_dispatch();
                return Promise.all(promises);
            };

            // 3. Continuous streaming sliding queue interfaces
            window.__IC_stream_push = function(pairs, timeoutMs = 5000) {
                for (let i = 0; i < pairs.length; i++) {
                    let p = pairs[i];
                    window.__IC_queue.push({
                        first: p[0],
                        second: p[1],
                        timeoutMs: timeoutMs,
                        resolve: (res) => {
                            window.__IC_stream_results.push(res);
                        }
                    });
                }
                window.__IC_dispatch();
                return window.__IC_queue.length;
            };

            window.__IC_stream_pull = function(maxCount = 50) {
                let count = Math.min(maxCount, window.__IC_stream_results.length);
                let pulled = window.__IC_stream_results.splice(0, count);
                let busyCount = 0;
                for (let i = 0; i < window.__IC_workers.length; i++) {
                    if (window.__IC_workers[i].busy) busyCount++;
                }
                return {
                    results: pulled,
                    queued: window.__IC_queue.length,
                    active: busyCount
                };
            };

            // Save data synchronizer to retain save data in Opera
            window.__IC_sync_new_item = function(name, emoji, isNew, recipePair) {
                let vueInst = document.querySelector('.container')?.__vue__;
                if (!vueInst) return false;

                let existing = vueInst.items.find(i => i.text.toLowerCase() === name.toLowerCase());
                if (existing) {
                    return true;
                }

                let newItem = {
                    id: vueInst.items.length,
                    saveId: vueInst.currSave,
                    text: name,
                    emoji: emoji || '✨',
                    discovered: !!isNew,
                    recipes: recipePair ? [recipePair] : []
                };

                vueInst.items.push(newItem);
                if (vueInst.currSaveData) {
                    vueInst.currSaveData.numItems += 1;
                }

                try {
                    window.dispatchEvent(new Event('storage'));
                } catch(e) {}

                return true;
            };

            return true;
        })()
        """
        bridge_js = bridge_template.replace("__SAFE_WORKERS__", str(safe_workers)).replace("__QUERY_INTERVAL_MS__", str(self.query_interval_ms))
        self.eval_js(bridge_js)

    def get_browser_inventory(self) -> List[Dict[str, Any]]:
        """Retrieves all elements currently unlocked in the browser's save data."""
        self.handle_cloudflare_if_needed()
        query_js = """
        (() => {
            let vueInst = document.querySelector('.container')?.__vue__;
            if (!vueInst || !vueInst.items) return [];
            return vueInst.items.map(i => ({
                id: i.id,
                text: i.text,
                emoji: i.emoji,
                discovered: !!i.discovered
            }));
        })()
        """
        items = self.eval_js(query_js)
        return items or []

    def batch_query_pairs(self, pairs: List[Tuple[str, str]], timeout: float = 30.0) -> List[Dict[str, Any]]:
        """Queries a batch of element pairs with high-speed sliding pipeline."""
        self.handle_cloudflare_if_needed()
        pairs_json = json.dumps(pairs)
        timeout_ms = int(min(timeout * 1000, 10000))
        call_js = f"window.__IC_batch_query({pairs_json}, {timeout_ms})"
        try:
            return self.eval_js(call_js, await_promise=True, timeout=timeout)
        except RuntimeError as e:
            if "is not a function" in str(e) or "__IC_batch_query" in str(e):
                self.inject_bridge()
                return self.eval_js(call_js, await_promise=True, timeout=timeout)
            raise

    def stream_push(self, pairs: List[Tuple[str, str]], timeout_ms: int = 6000) -> int:
        """Pushes untested pairs to in-page continuous streaming queue."""
        self.handle_cloudflare_if_needed()
        pairs_json = json.dumps(pairs)
        return int(self.eval_js(f"window.__IC_stream_push({pairs_json}, {timeout_ms})") or 0)

    def stream_pull(self, max_count: int = 50) -> Dict[str, Any]:
        """Pulls completed query results from in-page stream buffer."""
        return self.eval_js(f"window.__IC_stream_pull({max_count})") or {"results": [], "queued": 0, "active": 0}

    def sync_new_item(self, name: str, emoji: str, is_new: bool, recipe: Optional[List[int]] = None) -> bool:
        """Syncs a newly discovered element into Opera's save data and UI."""
        recipe_arg = json.dumps(recipe) if recipe else "null"
        clean_name = json.dumps(name)
        clean_emoji = json.dumps(emoji)
        sync_js = f"window.__IC_sync_new_item({clean_name}, {clean_emoji}, {str(is_new).lower()}, {recipe_arg})"
        try:
            return bool(self.eval_js(sync_js))
        except Exception:
            return False

    def close(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None
