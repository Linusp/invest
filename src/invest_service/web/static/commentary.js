(() => {
    const sessionLabels = {
        pre_market: "盘前", intraday: "盘中", post_market: "盘后",
        daily: "日度复盘", weekly: "周度复盘",
    };
    const sourceLabels = {human: "人工", ai: "AI", import: "导入", system: "系统"};
    let sequence = 0;

    const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, character => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
    })[character]);
    const today = () => new Date().toLocaleDateString("en-CA", {timeZone: "Asia/Shanghai"});

    function subjectParams(subject) {
        if (!subject) return {};
        if (subject.subject_type === "market") {
            return {subject_type: "market", market_scope_code: subject.market_scope_code};
        }
        if (subject.subject_type === "portfolio") {
            return {subject_type: "portfolio", portfolio_id: subject.portfolio_id};
        }
        return {
            subject_type: "asset", asset_symbol: subject.asset_symbol,
            asset_category: subject.asset_category,
        };
    }

    function mount({container}) {
        const root = typeof container === "string" ? document.querySelector(container) : container;
        const id = `commentary-${++sequence}`;
        let subject = null;
        root.innerHTML = `
            <section class="panel commentary-panel">
                <div class="commentary-toolbar">
                        <select class="input commentary-session-filter" aria-label="按时段筛选">
                            <option value="">全部时段</option>
                            ${Object.entries(sessionLabels).map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}
                        </select>
                        <button class="button primary commentary-add" type="button"><i data-lucide="message-square-plus"></i><span>添加</span></button>
                </div>
                <div class="table-wrap"><table class="data-table commentary-table"><thead><tr><th>日期</th><th>时段</th><th>标题</th><th>摘要</th><th>来源</th></tr></thead><tbody class="commentary-list"><tr><td colspan="5"><div class="empty-state compact">请选择分析对象</div></td></tr></tbody></table></div>
            </section>
            <dialog id="${id}-dialog" class="dialog-wide">
                <form>
                    <div class="dialog-header"><h2>添加点评</h2><button class="icon-button commentary-close" type="button" aria-label="关闭"><i data-lucide="x"></i></button></div>
                    <div class="dialog-body dialog-body-scroll">
                        <div class="form-grid">
                            <label class="field"><span class="label">交易日期</span><input name="trading_date" class="input" type="date" required></label>
                            <label class="field"><span class="label">时段</span><select name="session" class="input" required>${Object.entries(sessionLabels).map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}</select></label>
                            <label class="field"><span class="label">来源</span><select name="source" class="input">${Object.entries(sourceLabels).map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}</select></label>
                        </div>
                        <label class="field"><span class="label">标题</span><input name="title" class="input" maxlength="255" required></label>
                        <label class="field"><span class="label">摘要</span><textarea name="summary" class="textarea"></textarea></label>
                        <label class="field"><span class="label">正文（Markdown）</span><textarea name="content" class="textarea commentary-editor" required placeholder="支持标题、列表、引用等 Markdown 内容"></textarea></label>
                        <div class="checkbox-row">
                            <label><input name="has_outlook" type="checkbox"> 包含预判</label>
                            <label><input name="has_risk" type="checkbox"> 包含风险</label>
                            <label><input name="has_trade_plan" type="checkbox"> 包含交易计划</label>
                        </div>
                    </div>
                    <div class="dialog-footer"><button class="button commentary-close" type="button">取消</button><button class="button primary" type="submit">保存点评</button></div>
                </form>
            </dialog>`;
        const list = root.querySelector(".commentary-list");
        const dialog = root.querySelector("dialog");
        const detailDialog = document.createElement("dialog");
        detailDialog.className = "dialog-wide";
        document.body.append(detailDialog);
        const form = dialog.querySelector("form");
        const filter = root.querySelector(".commentary-session-filter");

        async function load() {
            if (!subject) {
                list.innerHTML = '<tr><td colspan="5"><div class="empty-state compact">请选择分析对象</div></td></tr>';
                return;
            }
            const params = new URLSearchParams(subjectParams(subject));
            if (filter.value) params.set("session", filter.value);
            const items = await window.api(`/commentaries?${params}`);
            list.innerHTML = items.length ? items.map((item, index) => `
                <tr class="commentary-list-row" tabindex="0" role="button" data-commentary-index="${index}">
                    <td class="mono">${escapeHtml(item.trading_date)}</td>
                    <td><span class="badge">${escapeHtml(sessionLabels[item.session] || item.session)}</span></td>
                    <td class="commentary-list-title">${escapeHtml(item.title)}</td>
                    <td class="commentary-list-summary">${escapeHtml(item.summary || "--")}</td>
                    <td>${escapeHtml(sourceLabels[item.source] || item.source)}</td>
                </tr>`).join("") : '<tr><td colspan="5"><div class="empty-state compact">暂无点评</div></td></tr>';
            list.querySelectorAll("[data-commentary-index]").forEach(button => {
                button.addEventListener("click", () => {
                    const item = items[Number(button.dataset.commentaryIndex)];
                    detailDialog.innerHTML = `<div class="dialog-header"><h2>${escapeHtml(item.title)}</h2><button class="icon-button" type="button" aria-label="关闭"><i data-lucide="x"></i></button></div><div class="dialog-body"><div class="commentary-meta"><span class="badge">${escapeHtml(sessionLabels[item.session] || item.session)}</span><time>${escapeHtml(item.trading_date)}</time></div>${item.summary ? `<p class="commentary-summary">${escapeHtml(item.summary)}</p>` : ""}<div class="commentary-content">${item.content_html}</div></div>`;
                    detailDialog.querySelector("button").addEventListener("click", () => detailDialog.close());
                    detailDialog.showModal();
                    window.lucide?.createIcons();
                });
                button.addEventListener("keydown", event => {
                    if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        button.click();
                    }
                });
            });
        }

        async function save(event) {
            event.preventDefault();
            if (!subject) return;
            const data = new FormData(form);
            const payload = {
                ...subjectParams(subject),
                session: data.get("session"), trading_date: data.get("trading_date"),
                title: data.get("title").trim(), summary: data.get("summary").trim() || null,
                content: data.get("content"), content_format: "markdown",
                source: data.get("source"), has_outlook: data.get("has_outlook") === "on",
                has_risk: data.get("has_risk") === "on",
                has_trade_plan: data.get("has_trade_plan") === "on",
            };
            try {
                await window.api("/commentaries", {method: "POST", body: JSON.stringify(payload)});
                dialog.close();
                window.showToast("点评已保存", "success");
                await load();
            } catch (error) { window.showToast(error.message, "error"); }
        }

        root.querySelector(".commentary-add").addEventListener("click", () => {
            if (!subject) return;
            form.reset();
            form.elements.trading_date.value = today();
            dialog.showModal();
        });
        root.querySelectorAll(".commentary-close").forEach(button =>
            button.addEventListener("click", () => dialog.close())
        );
        filter.addEventListener("change", () => load().catch(error => window.showToast(error.message, "error")));
        form.addEventListener("submit", save);
        window.lucide?.createIcons();
        return {
            setSubject(nextSubject) {
                subject = nextSubject;
                return load().catch(error => window.showToast(error.message, "error"));
            },
            reload: load,
        };
    }

    window.CommentaryTimeline = {mount};
})();
