class InventoryViewer {
    constructor() {
        this.inventoryData = [];
        this.itemIcons = {};
        this.itemNames = {};
        this.itemCategories = {};
        this.itemBlacklist = new Set();
        this.isLoading = false;
        this.selectedIds = new Set(); // instanceIds checked for bulk refresh
        /** Full filtered list for the current search/sort (used by virtual scroll + select-all). */
        this._displayedItems = [];

        // Virtual scroll (large lists on mobile/low-power devices)
        this._virtualRowHeight = 56;
        /** Last rendered slice; skip DOM work when scroll doesn't change window. */
        this._virtualLastStart = -1;
        this._virtualLastEnd = -1;
        this._virtualScrollRaf = null;
        /** Skip icon column network/decoding on narrow viewports (set in filterAndDisplay). */
        this._compactMobile = false;
        this._filterDebounceTimer = null;
        this._virtualScrollAttached = false;
        this._resizeBound = false;
        this._onInventoryScroll = () => {
            if (this._virtualScrollRaf) cancelAnimationFrame(this._virtualScrollRaf);
            this._virtualScrollRaf = requestAnimationFrame(() => {
                this._virtualScrollRaf = null;
                const c = document.getElementById('inventoryGrid');
                if (c && c.querySelector('#inventoryTableBody') && this._displayedItems.length) {
                    this._renderVirtualWindow(c, this._displayedItems);
                }
            });
        };

        // Dupe loop state
        this._loopActive = false;
        this._loopTimer  = null;
        this._loopCount  = 0;
        this._loopGameAssetIds = [];

        this.init();
    }

    async init() {
        this.bindEvents();
        this.showLoading(true);
        try {
            const [dataOutcome, invOutcome] = await Promise.allSettled([
                this.loadDataEssential(),
                this._fetchInventoryJson()
            ]);
            if (dataOutcome.status === 'rejected') console.error('Static data:', dataOutcome.reason);
            if (invOutcome.status === 'rejected') {
                const err = invOutcome.reason;
                throw err instanceof Error ? err : new Error(String(err));
            }
            this._syncInventoryFromApi(invOutcome.value);
            console.log(`✅ Loaded ${this.inventoryData.length} items`);
            this.updateStats();
            this.filterAndDisplay();
            this.showTemporaryMessage(`✅ Refreshed! ${this.inventoryData.length} items`, '#10b981');
        } catch (err) {
            console.error('Error loading inventory:', err);
            this.showError(err.message || String(err));
        } finally {
            this.showLoading(false);
        }

        // Large catalog (~80KB + JSON parse): defer until first paint so the page feels fast on phones.
        this._scheduleLoadItemIcons();
    }

    /**
     * Names, categories, blacklist — small files, enough to render the table on first paint.
     */
    async loadDataEssential() {
        const [namesRes, catsRes, blackRes] = await Promise.all([
            fetch('/data/item_names.json'),
            fetch('/data/item_categories.json'),
            fetch('/data/item_blacklist.json')
        ]);
        this.itemNames      = await namesRes.json();
        this.itemCategories = await catsRes.json();
        const blacklistArr   = await blackRes.json();
        this.itemBlacklist  = new Set(blacklistArr.map(id => String(id)));
        console.log('✅ Loaded essential data files');
    }

    _scheduleLoadItemIcons() {
        const run = async () => {
            try {
                const res = await fetch('/data/item_icons.json');
                if (!res.ok) throw new Error(`item_icons HTTP ${res.status}`);
                this.itemIcons = await res.json();
                console.log('✅ Loaded item icons catalog');
                if (this.inventoryData.length) {
                    this.updateStats();
                    this.filterAndDisplay();
                }
            } catch (err) {
                console.error('Error loading item_icons:', err);
            }
        };

        const idle = window.requestIdleCallback;
        if (typeof idle === 'function') {
            idle(() => run(), { timeout: 2500 });
        } else {
            setTimeout(run, 50);
        }
    }

    // ── Static data (full reload if ever needed) ────────────────────────────────

    async loadData() {
        await this.loadDataEssential();
        try {
            const iconsRes = await fetch('/data/item_icons.json');
            this.itemIcons = await iconsRes.json();
        } catch (err) {
            console.error('Error loading item_icons:', err);
        }
    }

    getItemName(assetId) {
        const id = String(assetId);
        if (this.itemIcons[id]) return this.itemIcons[id].name;
        if (this.itemNames[id]) return this.itemNames[id];
        return `Unknown (${assetId})`;
    }

    getItemIcon(assetId) {
        const id = String(assetId);
        return (this.itemIcons[id] && this.itemIcons[id].icon) ? this.itemIcons[id].icon : null;
    }

    getItemCategory(assetId) {
        return this.itemCategories[String(assetId)] || 'Misc';
    }

    isBlacklisted(assetId) {
        return this.itemBlacklist.has(String(assetId));
    }

    // ── Events ─────────────────────────────────────────────────────────────────

    bindEvents() {
        document.getElementById('refreshBtn').onclick  = () => this.loadInventory();
        const searchInput = document.getElementById('searchInput');
        searchInput.oninput = () => {
            if (this._filterDebounceTimer) clearTimeout(this._filterDebounceTimer);
            this._filterDebounceTimer = setTimeout(() => {
                this._filterDebounceTimer = null;
                this.filterAndDisplay();
            }, 200);
        };
        document.getElementById('sortBy').onchange = () => this.filterAndDisplay();

        const bulkBtn = document.getElementById('bulkRefreshBtn');
        if (bulkBtn) bulkBtn.onclick = () => this.bulkRefreshSelected();

        const grid = document.getElementById('inventoryGrid');
        grid.addEventListener('change', e => this._onInventoryGridChange(e));
        grid.addEventListener('click', e => this._onInventoryGridClick(e));
    }

    _onInventoryGridChange(e) {
        const t = e.target;
        if (!(t instanceof HTMLInputElement)) return;

        if (t.id === 'selectAllCheckbox') {
            const checked = t.checked;
            const items = this._displayedItems;
            for (const it of items) {
                if (checked) this.selectedIds.add(it.instanceId);
                else this.selectedIds.delete(it.instanceId);
            }
            const grid = document.getElementById('inventoryGrid');
            if (grid.querySelector('#inventoryTableBody')) {
                this._invalidateVirtualRange();
                this._renderVirtualWindow(grid, this._displayedItems);
            } else {
                grid.querySelectorAll('.row-checkbox').forEach(cb => {
                    cb.checked = checked;
                    const row = cb.closest('tr');
                    if (checked) row.classList.add('row-selected');
                    else row.classList.remove('row-selected');
                });
                this.updateSelectAllCheckbox();
            }
            this.updateBulkBar();
            return;
        }

        if (!t.classList.contains('row-checkbox')) return;

        const instanceId = t.dataset.instance;
        const row        = t.closest('tr');
        if (t.checked) {
            this.selectedIds.add(instanceId);
            row.classList.add('row-selected');
        } else {
            this.selectedIds.delete(instanceId);
            row.classList.remove('row-selected');
        }
        this.updateSelectAllCheckbox();
        this.updateBulkBar();
    }

    _onInventoryGridClick(e) {
        const refreshBtn = e.target.closest('.btn-refresh-id');
        if (refreshBtn) {
            e.preventDefault();
            e.stopPropagation();
            const row = refreshBtn.closest('tr');
            if (!row) return;
            const instanceId = row.dataset.instance;
            const item = this._displayedItems.find(i => i.instanceId === instanceId);
            if (item) this._runRefreshIdForRow(refreshBtn, item);
            return;
        }

        const row = e.target.closest('.inventory-table tbody tr');
        if (!row || row.classList.contains('virtual-spacer')) return;
        if (e.target.closest('button') || e.target.closest('input')) return;

        const instanceId = row.dataset.instance;
        const item       = this._displayedItems.find(i => i.instanceId === instanceId);
        if (item) this.showDetails(item);
    }

    async _runRefreshIdForRow(btn, item) {
        const name = this.getItemName(item.gameAssetId);
        const ok = confirm(
            `🔄 Refresh Instance ID (Recursive)\n\n` +
            `Item: ${name}\n` +
            `Current ID: ${item.instanceId}\n\n` +
            `This will:\n` +
            `  1. Create a new item with a fresh ID\n` +
            `  2. Delete the old item\n` +
            `  3. Update the container\n` +
            `  4. Recursively refresh all attachments & mods\n\n` +
            `Continue?`
        );
        if (!ok) return;

        btn.disabled    = true;
        btn.textContent = '⏳…';
        this.showLoading(true);
        try {
            await this.refreshItemId(item);
            this.showTemporaryMessage(`✅ ID refreshed! ${name}`, '#10b981');
            setTimeout(() => this.loadInventory(), 800);
        } catch (err) {
            this.showError(`Refresh ID failed: ${err.message}`);
            btn.disabled    = false;
            btn.textContent = '🔄 Refresh ID';
        } finally {
            this.showLoading(false);
        }
    }

    // ── Inventory fetch ────────────────────────────────────────────────────────

    async _fetchInventoryJson() {
        const resp = await fetch(`/api/inventory?nocache=${Date.now()}`, {
            cache: 'no-store',
            headers: { 'Cache-Control': 'no-cache, no-store, must-revalidate', 'Pragma': 'no-cache' }
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return resp.json();
    }

    _syncInventoryFromApi(data) {
        this.inventoryData = data.items || [];
        this.selectedIds.forEach(id => {
            if (!this.inventoryData.find(i => i.instanceId === id)) this.selectedIds.delete(id);
        });
    }

    async loadInventory() {
        if (this.isLoading) return;
        this.isLoading = true;
        this.showLoading(true);
        try {
            const data = await this._fetchInventoryJson();
            this._syncInventoryFromApi(data);
            console.log(`✅ Loaded ${this.inventoryData.length} items`);
            this.updateStats();
            this.filterAndDisplay();
            this.showTemporaryMessage(`✅ Refreshed! ${this.inventoryData.length} items`, '#10b981');
        } catch (err) {
            console.error('Error loading inventory:', err);
            this.showError(err.message);
        } finally {
            this.isLoading = false;
            this.showLoading(false);
        }
    }

    // ── Single Refresh Instance ID (using backend /api/change-id) ──────────────

    async refreshItemId(item) {
        const name = this.getItemName(item.gameAssetId);
        console.log(`🔄 Refreshing ID for: ${name} (${item.instanceId})`);

        // Call backend's recursive ID changer
        const response = await fetch('/api/change-id', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ targetId: item.instanceId })
        });

        const result = await response.json();

        if (!response.ok || !result.success) {
            throw new Error(result.error || result.message || 'Change ID failed');
        }

        console.log(`✅ Refreshed: ${name} → ${result.new_id}`);
        return result.new_id;
    }

    // ── Bulk Refresh Selected ──────────────────────────────────────────────────

    async bulkRefreshSelected() {
        if (this.selectedIds.size === 0) {
            alert('No items selected.\nCheck the boxes on the left of each item first.');
            return;
        }

        const count = this.selectedIds.size;
        const ok = confirm(
            `🔄 Bulk Refresh Instance IDs\n\n` +
            `${count} item(s) selected.\n\n` +
            `Each item will be processed one at a time:\n` +
            `  • Fetch fresh inventory\n` +
            `  • Create new item with fresh ID\n` +
            `  • Delete old item\n` +
            `  • Update container\n` +
            `  • Recursively update attachments & mods\n\n` +
            `Continue?`
        );
        if (!ok) return;

        // Snapshot the list
        const instanceIds = [...this.selectedIds];
        this.selectedIds.clear();
        this.updateBulkBar();

        const progress = this.showBulkProgress(instanceIds.length);

        let done = 0, failed = 0;
        const errors = [];

        for (const instanceId of instanceIds) {
            const item = this.inventoryData.find(i => i.instanceId === instanceId);
            if (!item) {
                progress.update(++done + failed, `⚠️ Skipped (not found): ${instanceId.substring(0, 8)}…`);
                failed++;
                continue;
            }

            const name = this.getItemName(item.gameAssetId);
            progress.update(done + failed, `Processing: ${name.length > 30 ? name.substring(0,28)+'…' : name}`);

            try {
                await this.refreshItemId(item);
                done++;
                progress.update(done + failed, `✅ Done: ${name.length > 30 ? name.substring(0,28)+'…' : name}`);
            } catch (err) {
                failed++;
                errors.push(`${name}: ${err.message}`);
                console.error(`❌ Failed for ${name}:`, err);
                progress.update(done + failed, `❌ Failed: ${name.length > 30 ? name.substring(0,28)+'…' : name}`);
            }

            // Small delay between items
            await new Promise(r => setTimeout(r, 300));
        }

        progress.finish(done, failed, errors);

        // Reload inventory once everything is done
        setTimeout(() => this.loadInventory(), 800);
    }

    // ── Super Safe Pocket (multi-cycle bulk ID refresh) ────────────────────────

    async safePocket() {
        if (this.selectedIds.size === 0) {
            alert('No items selected.\nUse the checkbox on each row or Select All first.');
            return;
        }

        const count = this.selectedIds.size;
        const cyclesStr = prompt(
            `🔒 Super Safe Pocket\n\n` +
            `${count} item(s) selected.\n\n` +
            `Each cycle re-generates all item IDs, making them untraceable.\n` +
            `More cycles = more protection.\n\n` +
            `How many cycles? (1–10, default 1):`,
            '1'
        );
        if (cyclesStr === null) return; // cancelled
        const cycles = Math.max(1, Math.min(10, parseInt(cyclesStr, 10) || 1));

        const ok = confirm(
            `🔒 Super Safe Pocket\n\n` +
            `${count} item(s) × ${cycles} cycle(s)\n\n` +
            `This will change all selected item IDs ${cycles} time(s).\n` +
            `Continue?`
        );
        if (!ok) return;

        const instanceIds = [...this.selectedIds];
        this.selectedIds.clear();
        this.updateBulkBar();

        const overlay = document.createElement('div');
        overlay.id = 'safePocketOverlay';
        overlay.style.cssText = `
            position:fixed; bottom:20px; right:20px; z-index:9999;
            background:#1a1a3a; border:1px solid #10b981; border-radius:12px;
            padding:20px 24px; min-width:320px; max-width:420px;
            box-shadow:0 10px 40px rgba(0,0,0,0.7);
            font-family:monospace; font-size:13px; color:#e0e0e0;
            animation: slideUp 0.3s ease-out;
        `;
        overlay.innerHTML = `
            <div style="font-weight:bold;color:#10b981;margin-bottom:12px;font-size:14px">
                🔒 Super Safe Pocket — Running…
            </div>
            <div id="spBar" style="
                background:rgba(16,185,129,0.15); border-radius:6px;
                height:8px; margin-bottom:12px; overflow:hidden;
            ">
                <div id="spFill" style="
                    background:linear-gradient(90deg,#10b981,#34d399);
                    height:100%; width:5%; transition:width 0.5s ease;
                    border-radius:6px;
                "></div>
            </div>
            <div id="spStatus" style="color:#ccc;margin-bottom:6px">Sending request…</div>
            <div id="spCycle" style="color:#10b981">Cycle 0 / ${cycles}</div>
        `;
        document.body.appendChild(overlay);

        const setStatus = (msg, cycle) => {
            const s = document.getElementById('spStatus');
            const c = document.getElementById('spCycle');
            const f = document.getElementById('spFill');
            if (s) s.textContent = msg;
            if (c) c.textContent = `Cycle ${cycle} / ${cycles}`;
            if (f) f.style.width = `${Math.round((cycle / cycles) * 100)}%`;
        };

        try {
            setStatus('Processing…', 0);
            const resp = await fetch('/api/safe-pocket', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ targetIds: instanceIds, cycles })
            });
            const result = await resp.json();

            if (!resp.ok || !result.ok) {
                throw new Error(result.error || result.message || 'Safe Pocket failed');
            }

            setStatus(`✅ ${result.message || 'Done!'}`, result.cycles_done || cycles);
            const fill = document.getElementById('spFill');
            if (fill) {
                fill.style.width = '100%';
                fill.style.background = 'linear-gradient(90deg,#10b981,#34d399)';
            }
            const title = overlay.querySelector('div');
            if (title) {
                title.textContent = `🔒 Super Safe Pocket — Done!`;
                title.style.color = '#10b981';
            }
        } catch (err) {
            const s = document.getElementById('spStatus');
            if (s) s.innerHTML = `<span style="color:#ef4444">❌ ${err.message}</span>`;
            const fill = document.getElementById('spFill');
            if (fill) fill.style.background = '#ef4444';
            console.error('Safe Pocket error:', err);
        }

        setTimeout(() => overlay.remove(), 5000);
        setTimeout(() => this.loadInventory(), 800);
    }

    // ── Dupe Backpack — Infinite Refresh Loop ─────────────────────────────────

    startDupeLoop() {
        if (this.selectedIds.size === 0) {
            alert('No items selected.\nCheck the boxes first.');
            return;
        }

        // Save stable gameAssetIds as strings — never change even when instanceIds rotate
        this._loopGameAssetIds = [];
        this.selectedIds.forEach(id => {
            const item = this.inventoryData.find(i => i.instanceId === id);
            if (item && item.gameAssetId != null) {
                this._loopGameAssetIds.push(String(item.gameAssetId));
            }
        });

        if (this._loopGameAssetIds.length === 0) {
            alert('Could not map selected items to asset IDs.\nTry refreshing inventory first.');
            return;
        }

        this._loopActive = true;
        this._loopCount  = 0;
        this._updateDupeBtn();
        this._loopFire();
    }

    stopDupeLoop() {
        this._loopActive = false;
        if (this._loopTimer) {
            clearTimeout(this._loopTimer);
            this._loopTimer = null;
        }
        this._updateDupeBtn();
        this.loadInventory();
    }

    _updateDupeBtn() {
        const btn = document.getElementById('dupeBackpackBtn');
        if (!btn) return;
        if (this._loopActive) {
            btn.textContent = '⏹ STOP';
            btn.style.background = 'linear-gradient(135deg,#7f1d1d,#ef4444)';
            btn.onclick = () => this.stopDupeLoop();
        } else {
            btn.textContent = '♾️ DUPE BACKPACK';
            btn.style.background = 'linear-gradient(135deg,#1e3a5f,#3b82f6)';
            btn.onclick = () => this.startDupeLoop();
        }
    }

    _loopFire() {
        if (!this._loopActive) return;
        this._loopCount++;
        this._loopTask(this._loopCount); // fire and forget — no await
        this._loopTimer = setTimeout(() => this._loopFire(), 100);
    }

    async _loopTask(num) {
        try {
            // 1. Fetch fresh inventory — instanceIds rotate after each refresh
            const resp = await fetch(`/api/inventory?nocache=${Date.now()}`, {
                cache: 'no-store',
                headers: { 'Cache-Control': 'no-cache, no-store, must-revalidate', 'Pragma': 'no-cache' }
            });
            if (!resp.ok) return;

            const data = await resp.json();

            // Normalize response — handles both array and {items:[...]} formats
            let freshInventory;
            if (Array.isArray(data)) {
                freshInventory = data;
            } else if (data && typeof data === 'object') {
                freshInventory = data.items || data.Items || data.inventory || data.Inventory || data.data || [];
                if (!Array.isArray(freshInventory)) freshInventory = [];
            } else {
                return;
            }

            if (!freshInventory.length) return;

            // Update local cache
            this.inventoryData = freshInventory;

            // 2. Remap by gameAssetId (string) → get current instanceIds
            const needed   = [...this._loopGameAssetIds]; // copy to splice safely
            const freshIds = [];
            for (const itm of freshInventory) {
                const pos = needed.indexOf(String(itm.gameAssetId));
                if (pos !== -1) {
                    freshIds.push(itm.instanceId);
                    needed.splice(pos, 1);
                    if (needed.length === 0) break;
                }
            }

            if (!freshIds.length) return;

            // 3. POST /api/change-id-bulk with the freshly-remapped instanceIds
            await fetch('/api/change-id-bulk', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ targetIds: freshIds })
            });
        } catch (_err) {
            // Silently swallow — task errors must never kill the loop
        }
    }

    // ── Bulk progress UI ───────────────────────────────────────────────────────

    showBulkProgress(total) {
        const overlay = document.createElement('div');
        overlay.id = 'bulkProgressOverlay';
        overlay.style.cssText = `
            position:fixed; bottom:20px; right:20px; z-index:9999;
            background:#1a1a3a; border:1px solid #7c3aed; border-radius:12px;
            padding:20px 24px; min-width:320px; max-width:420px;
            box-shadow:0 10px 40px rgba(0,0,0,0.7);
            font-family:monospace; font-size:13px; color:#e0e0e0;
            animation: slideUp 0.3s ease-out;
        `;
        overlay.innerHTML = `
            <div style="font-weight:bold;color:#a78bfa;margin-bottom:12px;font-size:14px">
                🔄 Bulk Refresh in Progress
            </div>
            <div id="bpBar" style="
                background:rgba(124,58,237,0.2); border-radius:6px;
                height:8px; margin-bottom:12px; overflow:hidden;
            ">
                <div id="bpFill" style="
                    background:linear-gradient(90deg,#7c3aed,#a78bfa);
                    height:100%; width:0%; transition:width 0.3s ease;
                    border-radius:6px;
                "></div>
            </div>
            <div id="bpStatus" style="color:#ccc;margin-bottom:6px">Starting…</div>
            <div id="bpCount" style="color:#a78bfa">0 / ${total}</div>
        `;
        document.body.appendChild(overlay);

        return {
            update(current, statusText) {
                const pct = Math.round((current / total) * 100);
                document.getElementById('bpFill').style.width   = `${pct}%`;
                document.getElementById('bpStatus').textContent = statusText;
                document.getElementById('bpCount').textContent  = `${current} / ${total}`;
            },
            finish(done, failed, errors) {
                const fill = document.getElementById('bpFill');
                fill.style.width      = '100%';
                fill.style.background = failed > 0 ? '#f59e0b' : '#10b981';

                document.getElementById('bpStatus').innerHTML =
                    failed > 0
                        ? `<span style="color:#f59e0b">⚠️ ${done} succeeded, ${failed} failed</span>`
                        : `<span style="color:#10b981">✅ All ${done} items refreshed!</span>`;

                document.getElementById('bpCount').textContent = `${done + failed} / ${total}`;

                if (errors.length) {
                    const errDiv = document.createElement('div');
                    errDiv.style.cssText = 'margin-top:10px;color:#ef4444;font-size:11px;max-height:80px;overflow-y:auto';
                    errDiv.textContent = errors.join('\n');
                    overlay.appendChild(errDiv);
                }

                setTimeout(() => overlay.remove(), 5000);
            }
        };
    }

    // ── Bulk selection bar ─────────────────────────────────────────────────────

    updateBulkBar() {
        const count = this.selectedIds.size;
        let bar = document.getElementById('bulkActionBar');

        if (count === 0) {
            if (this._loopActive) this.stopDupeLoop();
            if (bar) bar.remove();
            return;
        }

        if (!bar) {
            bar = document.createElement('div');
            bar.id = 'bulkActionBar';
            bar.style.cssText = `
                position:fixed; bottom:20px; left:50%; transform:translateX(-50%);
                background:#1a1a3a; border:1px solid #7c3aed; border-radius:10px;
                padding:12px 24px; display:flex; align-items:center; gap:16px;
                box-shadow:0 8px 32px rgba(0,0,0,0.6); z-index:500;
                animation: slideUp 0.25s ease-out;
                white-space:nowrap;
            `;
            bar.innerHTML = `
                <span id="bulkBarCount" style="color:#a78bfa;font-weight:bold"></span>
                <button id="bulkRefreshBarBtn" style="
                    background:linear-gradient(135deg,#7c3aed,#a78bfa);
                    color:white; border:none; border-radius:7px;
                    padding:8px 18px; cursor:pointer; font-weight:bold; font-size:13px;
                ">🔄 Refresh Selected IDs</button>
                <button id="safePocketBtn" style="
                    background:linear-gradient(135deg,#065f46,#10b981);
                    color:white; border:none; border-radius:7px;
                    padding:8px 18px; cursor:pointer; font-weight:bold; font-size:13px;
                ">🔒 Super Safe Pocket</button>
                <button id="dupeBackpackBtn" style="
                    background:linear-gradient(135deg,#1e3a5f,#3b82f6);
                    color:white; border:none; border-radius:7px;
                    padding:8px 18px; cursor:pointer; font-weight:bold; font-size:13px;
                ">♾️ DUPE BACKPACK</button>
                <button id="bulkClearBtn" style="
                    background:rgba(220,38,38,0.2); color:#ef4444;
                    border:1px solid #ef4444; border-radius:7px;
                    padding:8px 14px; cursor:pointer; font-size:13px;
                ">✕ Clear</button>
            `;
            document.body.appendChild(bar);

            document.getElementById('bulkRefreshBarBtn').onclick = () => this.bulkRefreshSelected();
            document.getElementById('safePocketBtn').onclick     = () => this.safePocket();
            document.getElementById('dupeBackpackBtn').onclick   = () => this.startDupeLoop();
            document.getElementById('bulkClearBtn').onclick = () => {
                this.selectedIds.clear();
                document.querySelectorAll('.row-checkbox').forEach(cb => { cb.checked = false; });
                document.querySelectorAll('.inventory-table tbody tr').forEach(r => {
                    if (!r.classList.contains('virtual-spacer')) r.classList.remove('row-selected');
                });
                this.updateBulkBar();
                this.updateSelectAllCheckbox();
                const grid = document.getElementById('inventoryGrid');
                if (grid && grid.querySelector('#inventoryTableBody') && this._displayedItems.length) {
                    this._invalidateVirtualRange();
                    this._renderVirtualWindow(grid, this._displayedItems);
                }
            };

            // Restore button state if loop was already running when bar was recreated
            this._updateDupeBtn();
        }

        document.getElementById('bulkBarCount').textContent = `${count} item${count > 1 ? 's' : ''} selected`;
    }

    updateSelectAllCheckbox() {
        const selectAll = document.getElementById('selectAllCheckbox');
        if (!selectAll) return;
        const list = this._displayedItems;
        if (!list || list.length === 0) {
            selectAll.checked = false;
            selectAll.indeterminate = false;
            return;
        }
        let selected = 0;
        for (const it of list) {
            if (this.selectedIds.has(it.instanceId)) selected++;
        }
        if (selected === 0) {
            selectAll.checked = false;
            selectAll.indeterminate = false;
        } else if (selected === list.length) {
            selectAll.checked = true;
            selectAll.indeterminate = false;
        } else {
            selectAll.checked = false;
            selectAll.indeterminate = true;
        }
    }

    // ── Stats ──────────────────────────────────────────────────────────────────

    updateStats() {
        const total = this.inventoryData.length;
        let totalAmount = 0;
        let identified = 0;
        for (const i of this.inventoryData) {
            totalAmount += i.amount || 1;
            if (!this.getItemName(i.gameAssetId).startsWith('Unknown')) identified++;
        }
        document.getElementById('stats').innerHTML = `
            📦 ${total.toLocaleString()} items |
            🔢 ${totalAmount.toLocaleString()} units |
            ✅ ${identified} identified |
            🕐 ${new Date().toLocaleTimeString()}
        `;
    }

    // ── Filter & sort ──────────────────────────────────────────────────────────

    filterAndDisplay() {
        if (!this.inventoryData.length) return;
        this._compactMobile = this._isNarrowViewport();
        let filtered = [...this.inventoryData];
        const search = document.getElementById('searchInput').value.toLowerCase();
        if (search) {
            filtered = filtered.filter(item => {
                const name = this.getItemName(item.gameAssetId);
                return name.toLowerCase().includes(search) || String(item.gameAssetId).includes(search);
            });
        }
        const sortBy = document.getElementById('sortBy').value;
        if (sortBy === 'name') {
            const keyed = filtered.map(it => ({ it, key: this.getItemName(it.gameAssetId) }));
            keyed.sort((a, b) => a.key.localeCompare(b.key));
            filtered = keyed.map(x => x.it);
        } else {
            filtered.sort((a, b) => {
                if (sortBy === 'amount') return (b.amount || 0) - (a.amount || 0);
                return (b.updatedAt || 0) - (a.updatedAt || 0);
            });
        }
        this._displayedItems = filtered;
        this._invalidateVirtualRange();
        const container = document.getElementById('inventoryGrid');
        container.scrollTop = 0;
        this.renderTable(filtered);
    }

    _isNarrowViewport() {
        return typeof window !== 'undefined' && window.matchMedia('(max-width: 896px)').matches;
    }

    _invalidateVirtualRange() {
        this._virtualLastStart = -1;
        this._virtualLastEnd = -1;
    }

    _effectiveOverscan() {
        return this._isNarrowViewport() ? 3 : 7;
    }

    _effectiveRowHeight() {
        return this._compactMobile ? 50 : this._virtualRowHeight;
    }

    _virtualThreshold() {
        return this._isNarrowViewport() ? 12 : 55;
    }

    _ensureVirtualScrollResize() {
        if (this._resizeBound) return;
        this._resizeBound = true;
        let t;
        window.addEventListener('resize', () => {
            clearTimeout(t);
            t = setTimeout(() => {
                this._invalidateVirtualRange();
                if (this._displayedItems.length > this._virtualThreshold()) {
                    this._scheduleVirtualRender();
                }
            }, 150);
        });
    }

    _attachVirtualScroll(container) {
        if (this._virtualScrollAttached) return;
        this._virtualScrollAttached = true;
        this._ensureVirtualScrollResize();
        container.addEventListener('scroll', this._onInventoryScroll, { passive: true });
    }

    _detachVirtualScroll(container) {
        if (!this._virtualScrollAttached || !container) return;
        container.removeEventListener('scroll', this._onInventoryScroll);
        this._virtualScrollAttached = false;
    }

    _scheduleVirtualRender() {
        const container = document.getElementById('inventoryGrid');
        if (!container || !this._displayedItems.length) return;
        requestAnimationFrame(() => this._renderVirtualWindow(container, this._displayedItems));
    }

    // ── Render ─────────────────────────────────────────────────────────────────

    _buildTableShell() {
        return `
            <table class="inventory-table">
                <thead>
                    <tr>
                        <th style="width:40px;text-align:center">
                            <input type="checkbox" id="selectAllCheckbox" title="Select all visible items"
                                style="width:16px;height:16px;cursor:pointer;accent-color:#7c3aed">
                        </th>
                        <th>Icon</th>
                        <th>Name</th>
                        <th>Category</th>
                        <th>Amount</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody id="inventoryTableBody"></tbody>
            </table>
        `;
    }

    _rowHtml(item) {
        const name          = this.getItemName(item.gameAssetId);
        const icon          = this.getItemIcon(item.gameAssetId);
        const category      = this.getItemCategory(item.gameAssetId);
        const isBlacklisted = this.isBlacklisted(item.gameAssetId);
        const isSelected    = this.selectedIds.has(item.instanceId);
        const rowClass      = [
            isBlacklisted ? 'blacklisted-row' : '',
            isSelected    ? 'row-selected'    : ''
        ].filter(Boolean).join(' ');
        const amount = item.amount || 1;
        const safeTitle = this.escapeHtml(name).replace(/"/g, '&quot;');

        return `
            <tr class="${rowClass}"
                data-instance="${item.instanceId}"
                data-asset="${item.gameAssetId}">
                <td style="text-align:center;width:40px" class="checkbox-cell">
                    <input type="checkbox" class="row-checkbox"
                        data-instance="${item.instanceId}"
                        ${isSelected ? 'checked' : ''}
                        style="width:16px;height:16px;cursor:pointer;accent-color:#7c3aed">
                </td>
                <td class="icon-cell">
                    ${this._compactMobile
                        ? '<span class="no-icon" aria-hidden="true">·</span>'
                        : (icon
                            ? `<img src="${icon}" class="item-icon" loading="lazy" decoding="async" width="36" height="36" alt="" onerror="this.style.display='none';this.parentElement.innerHTML='<span class=\\'no-icon\\'>🎮</span>'">`
                            : '<span class="no-icon">🎮</span>')}
                </td>
                <td class="name-cell" title="${safeTitle}">
                    ${this.escapeHtml(name.length > 40 ? name.substring(0, 37) + '…' : name)}
                </td>
                <td class="category-cell">${category}</td>
                <td class="amount-cell">${amount}</td>
                <td class="actions-cell">
                    <button class="btn-refresh-id" title="Refresh Instance ID (recursive)">🔄 Refresh ID</button>
                </td>
            </tr>
        `;
    }

    _renderVirtualWindow(container, items) {
        const tbody = container.querySelector('#inventoryTableBody');
        if (!tbody || !items.length) return;

        const thead = container.querySelector('.inventory-table thead');
        const headH = thead ? thead.getBoundingClientRect().height : 48;
        const viewH = container.clientHeight;
        const rowH = this._effectiveRowHeight();
        const overscan = this._effectiveOverscan();
        const scrollTop = Math.max(0, container.scrollTop - headH);
        let start = Math.floor(scrollTop / rowH) - overscan;
        if (start < 0) start = 0;
        const visibleRows = Math.ceil(viewH / rowH) + overscan * 2;
        let end = start + visibleRows;
        if (end > items.length) end = items.length;
        if (end - start < Math.min(visibleRows, items.length)) {
            start = Math.max(0, end - visibleRows);
        }

        if (start === this._virtualLastStart && end === this._virtualLastEnd) return;

        this._virtualLastStart = start;
        this._virtualLastEnd = end;

        const topPad = start * rowH;
        const bottomPad = (items.length - end) * rowH;

        let bodyHtml = '';
        if (topPad > 0) {
            bodyHtml += `<tr class="virtual-spacer" aria-hidden="true"><td colspan="6" style="padding:0;border:none;height:${topPad}px;line-height:0;font-size:0"></td></tr>`;
        }
        for (let i = start; i < end; i++) {
            bodyHtml += this._rowHtml(items[i]);
        }
        if (bottomPad > 0) {
            bodyHtml += `<tr class="virtual-spacer" aria-hidden="true"><td colspan="6" style="padding:0;border:none;height:${bottomPad}px;line-height:0;font-size:0"></td></tr>`;
        }

        tbody.innerHTML = bodyHtml;
        this.updateSelectAllCheckbox();
    }

    renderTable(items) {
        const container = document.getElementById('inventoryGrid');

        if (!items.length) {
            this._detachVirtualScroll(container);
            container.innerHTML = '<p style="text-align:center;padding:40px;color:#888">No items found</p>';
            return;
        }

        const useVirtual = items.length > this._virtualThreshold();
        if (useVirtual) {
            this._invalidateVirtualRange();
            container.innerHTML = this._buildTableShell();
            this._attachVirtualScroll(container);
            this._renderVirtualWindow(container, items);
            return;
        }

        this._detachVirtualScroll(container);

        const bodyInner = items.map(item => this._rowHtml(item)).join('');
        container.innerHTML = this._buildTableShell().replace(
            /\s*<tbody id="inventoryTableBody"><\/tbody>\s*/,
            `<tbody>${bodyInner}</tbody>`
        );
        this.updateSelectAllCheckbox();
    }

    // ── Detail modal ───────────────────────────────────────────────────────────

    showDetails(item) {
        const name          = this.getItemName(item.gameAssetId);
        const icon          = this.getItemIcon(item.gameAssetId);
        const category      = this.getItemCategory(item.gameAssetId);
        const date          = new Date(Number(item.updatedAt) / 1000000);
        const isBlacklisted = this.isBlacklisted(item.gameAssetId);

        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content" style="max-width:500px">
                <span class="close-modal">&times;</span>
                <div class="modal-header">
                    ${icon ? `<img src="${icon}" class="modal-icon" loading="lazy" decoding="async" width="48" height="48" alt="">` : '<div class="modal-icon-placeholder">🎮</div>'}
                    <h3>${this.escapeHtml(name)}</h3>
                </div>
                <div class="modal-details">
                    <p><strong>Category:</strong> ${category}</p>
                    <p><strong>Asset ID:</strong> ${item.gameAssetId}</p>
                    <p><strong>Instance ID:</strong> <code style="font-size:11px;word-break:break-all">${item.instanceId}</code></p>
                    <p><strong>Amount:</strong> ${item.amount || 1}</p>
                    <p><strong>Durability:</strong> ${item.durability || 0}/${item.maxDurability || 0}</p>
                    <p><strong>Updated:</strong> ${date.toLocaleString()}</p>
                    ${item.slots && item.slots.length ? `<p><strong>Slots:</strong> ${item.slots.length} equipped</p>` : ''}
                    ${isBlacklisted ? '<p style="color:#ef4444"><strong>⚠️ Blacklisted</strong></p>' : ''}
                    <div style="margin-top:20px;padding-top:15px;border-top:1px solid rgba(124,58,237,0.3)">
                        <button id="modalRefreshIdBtn"
                            style="width:100%;background:#fbbf24;color:#1a1a3a;padding:10px;border:none;
                                   border-radius:6px;cursor:pointer;font-weight:bold;font-size:14px;">
                            🔄 Refresh Instance ID (Recursive)
                        </button>
                    </div>
                </div>
                <button class="btn btn-primary close-btn">Close</button>
            </div>
        `;
        document.body.appendChild(modal);

        modal.querySelector('#modalRefreshIdBtn').onclick = async () => {
            const ok = confirm(
                `🔄 Refresh Instance ID (Recursive)\n\nItem: ${name}\nCurrent ID: ${item.instanceId}\n\n` +
                `This will recursively refresh the item, its attachments, and mods.\n\nContinue?`
            );
            if (ok) {
                modal.remove();
                this.showLoading(true);
                try {
                    await this.refreshItemId(item);
                    this.showTemporaryMessage(`✅ ID refreshed! ${name}`, '#10b981');
                    setTimeout(() => this.loadInventory(), 800);
                } catch (err) {
                    this.showError(`Refresh ID failed: ${err.message}`);
                } finally {
                    this.showLoading(false);
                }
            }
        };

        const close = () => modal.remove();
        modal.querySelector('.close-modal').onclick = close;
        modal.querySelector('.close-btn').onclick   = close;
        modal.onclick = (e) => { if (e.target === modal) close(); };
    }

    // ── Utilities ──────────────────────────────────────────────────────────────

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    showLoading(show) {
        const loadingDiv = document.getElementById('loading');
        const refreshBtn = document.getElementById('refreshBtn');
        if (show) {
            loadingDiv.style.display = 'flex';
            refreshBtn.disabled      = true;
            refreshBtn.style.opacity = '0.6';
            refreshBtn.innerHTML     = '<span class="btn-icon">⏳</span> Loading...';
        } else {
            loadingDiv.style.display = 'none';
            refreshBtn.disabled      = false;
            refreshBtn.style.opacity = '1';
            refreshBtn.innerHTML     = '<span class="btn-icon">🔄</span> Refresh';
        }
    }

    showError(message) {
        const errorDiv = document.getElementById('errorMessage');
        errorDiv.textContent    = `❌ ${message}`;
        errorDiv.style.display  = 'block';
        setTimeout(() => errorDiv.style.display = 'none', 6000);
    }

    showTemporaryMessage(message, color = '#10b981') {
        const statsDiv   = document.getElementById('stats');
        const original   = statsDiv.innerHTML;
        statsDiv.innerHTML   = message;
        statsDiv.style.color = color;
        setTimeout(() => {
            statsDiv.innerHTML   = original;
            statsDiv.style.color = '';
        }, 2500);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.inventoryViewer = new InventoryViewer();
});