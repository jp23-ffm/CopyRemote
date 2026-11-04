/* User change requests: comment or "these fields are wrong" (nothing is modified, admins review). */
(function () {
    let state = null;   // {key, urlBase, ackUrl, canAck, rows: [{field, value}], tab, changed}
    let allFields = [];
    const MAX_ROWS = 10;  // same limit as MAX_REQUEST_CHANGES on the server

    function emptyRow() { return {field: '', value: ''}; }

    function el(id) { return document.getElementById(id); }

    function node(tag, props, children) {
        const n = document.createElement(tag);
        Object.entries(props || {}).forEach(([k, v]) => {
            if (k === 'text') n.textContent = v;
            else if (k === 'class') n.className = v;
            else n.setAttribute(k, v);
        });
        (children || []).forEach(c => n.appendChild(c));
        return n;
    }

    function csrf() {
        const m = document.querySelector('meta[name="csrf-token"]');
        if (m) return m.getAttribute('content');
        const c = document.cookie.split(';').map(s => s.trim()).find(s => s.startsWith('csrftoken='));
        return c ? c.split('=')[1] : '';
    }

    function post(url, params) {
        return fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrf()},
            body: new URLSearchParams(params)
        }).then(r => r.json().then(j => { if (!r.ok || j.success === false) throw new Error(j.message || r.status); return j; }));
    }

    function message(text, kind) {
        const m = el('cr-msg');
        m.textContent = text || '';
        m.className = 'cr-msg' + (kind ? ' ' + kind : '');
    }

    /* Current value shown in the table row (the server stores the DB value, this is for display only) */
    function currentValue(field) {
        const rows = document.querySelectorAll('#serversTable tr.server-row');
        for (const row of rows) {
            if (row.dataset.hostname !== state.key) continue;
            const cell = row.querySelector('td[data-column="' + field + '"]');
            if (!cell) return '(column hidden)';
            const t = cell.textContent.trim();
            return t === 'MISSING' ? '' : t;
        }
        return '';
    }

    /* mode 'new': request form only (flag button) / 'history': previous requests only (badges) */
    function open(btn, mode) {
        const data = document.getElementById('request-fields-data');
        allFields = data ? JSON.parse(data.textContent) : [];
        state = {
            mode, key: btn.dataset.key, urlBase: btn.dataset.url, ackUrl: btn.dataset.ack, rejectUrl: btn.dataset.reject,
            canAck: btn.dataset.canack === 'true', rows: [emptyRow()], tab: 'fields', changed: false,
            history: [], rejecting: null   // rejecting: id of the request whose reject reason is being typed
        };
        const isNew = mode === 'new';
        el('cr-title').textContent = el('cr-title').dataset[mode];
        el('cr-item').textContent = state.key.replace('|', '  ·  ');
        el('cr-tabs').style.display = isNew ? '' : 'none';
        el('cr-send').style.display = isNew ? '' : 'none';
        el('cr-history').style.display = isNew ? 'none' : '';
        el('cr-comment').value = '';
        el('cr-reason').value = '';
        message('');
        el('requestModal').style.display = 'flex';
        if (isNew) {
            render();
        } else {
            ['cr-pane-fields', 'cr-pane-comment', 'cr-reason-wrap'].forEach(id => { el(id).style.display = 'none'; });
            const link = el('cr-all-link');
            link.href = link.dataset.base + '?' + new URLSearchParams({type: btn.dataset.type, item: '@' + state.key});
            el('cr-list').replaceChildren(node('div', {class: 'cr-hint', text: 'Loading…'}));
            loadHistory();
        }
    }

    window.openRequests = function (btn) { open(btn, 'new'); };

    /* Badge click: the request data attributes live on the flag button of the same cell */
    window.openRequestHistory = function (badge) {
        open(badge.closest('td').querySelector('.btn-open-requests'), 'history');
    };

    window.closeRequests = function () {
        el('requestModal').style.display = 'none';
        const reload = state && state.changed;
        state = null;
        if (reload) window.location.reload();   // refresh the badges in the table
    };

    window.switchRequestTab = function (tab) { state.tab = tab; message(''); render(); };

    window.addRequestRow = function () {
        if (state.rows.length >= MAX_ROWS) return;
        state.rows.push(emptyRow());
        render();
        const selects = el('cr-grid').querySelectorAll('select');
        selects[selects.length - 1].focus();
    };

    function render() {
        el('cr-tab-fields').classList.toggle('active', state.tab === 'fields');
        el('cr-tab-comment').classList.toggle('active', state.tab === 'comment');
        el('cr-pane-fields').style.display = state.tab === 'fields' ? '' : 'none';
        el('cr-pane-comment').style.display = state.tab === 'comment' ? '' : 'none';
        const n = state.rows.filter(r => r.field).length;
        el('cr-count').textContent = n;
        el('cr-count').style.display = n ? '' : 'none';
        el('cr-reason-wrap').style.display = state.tab === 'fields' ? '' : 'none';

        const grid = el('cr-grid');
        grid.replaceChildren();
        ['Field', 'Current value', 'Expected value', ''].forEach(h => grid.appendChild(node('div', {class: 'cr-head', text: h})));
        const used = new Set(state.rows.map(r => r.field).filter(Boolean));
        state.rows.forEach((row, i) => {
            // a field already picked on another row is disabled here
            const select = node('select', {'aria-label': 'Field to correct'}, [node('option', {value: '', text: 'Choose a field…'})]);
            allFields.forEach(f => {
                const opt = node('option', {value: f.name, text: f.label});
                if (f.name === row.field) opt.selected = true;
                else if (used.has(f.name)) opt.disabled = true;
                select.appendChild(opt);
            });
            select.addEventListener('change', () => {
                row.field = select.value;
                render();
                const input = el('cr-grid').querySelectorAll('input')[i];
                if (row.field) input.focus();
            });

            const input = node('input', {type: 'text', 'aria-label': 'Expected value', placeholder: 'Correct value', maxlength: '500'});
            input.value = row.value;
            input.disabled = !row.field;
            input.addEventListener('input', () => { row.value = input.value; });

            const del = node('button', {type: 'button', class: 'cr-del-btn', title: 'Remove this field', 'aria-label': 'Remove this field', text: '×'});
            del.addEventListener('click', () => {
                state.rows.splice(i, 1);
                if (!state.rows.length) state.rows.push(emptyRow());
                render();
            });

            grid.appendChild(node('div', {}, [select]));
            grid.appendChild(node('div', {class: 'cr-current', text: row.field ? (currentValue(row.field) || '–') : ''}));
            grid.appendChild(node('div', {}, [input]));
            grid.appendChild(node('div', {}, [del]));
        });
        el('cr-add').disabled = state.rows.length >= Math.min(MAX_ROWS, allFields.length);
    }

    window.submitRequest = function () {
        const key = state.key;
        let params;
        if (state.tab === 'comment') {
            const comment = el('cr-comment').value.trim();
            if (!comment) { message('The comment is empty.', 'error'); return; }
            params = {key, kind: 'comment', comment};
        } else {
            // rows without a field are ignored
            const changes = state.rows.filter(r => r.field).map(r => ({field: r.field, proposed: r.value.trim()}));
            const missing = changes.some(c => !c.proposed);
            if (!changes.length) { message('Select at least one field.', 'error'); return; }
            if (missing) { message('Enter the expected value for every selected field.', 'error'); return; }
            params = {key, kind: 'fields', changes: JSON.stringify(changes), reason: el('cr-reason').value.trim()};
        }
        const btn = el('cr-send'); btn.disabled = true;
        post(state.urlBase, params)
            .then(() => { state.changed = true; closeRequests(); })   // reload shows the new badge
            .catch(e => { message(e.message, 'error'); btn.disabled = false; });
    };

    function loadHistory() {
        const box = el('cr-list');
        fetch(state.urlBase + '?key=' + encodeURIComponent(state.key))
            .then(r => r.json())
            .then(d => { state.history = d.requests || []; state.rejecting = null; renderHistory(); })
            .catch(() => { box.replaceChildren(node('div', {class: 'cr-hint', text: 'Could not load previous requests.'})); });
    }

    function describe(r) {
        if (r.kind === 'comment') return [node('span', {text: 'Comment: “' + r.comment + '”'})];
        const parts = r.changes.map(c => node('div', {text: c.label + ': “' + c.current + '” → “' + c.proposed + '”'}));
        if (r.reason) parts.push(node('div', {class: 'cr-hint', text: 'Why: ' + r.reason}));
        return parts;
    }

    function rejectForm(r) {
        const input = node('input', {type: 'text', maxlength: '500', 'aria-label': 'Reason for rejecting',
                                     placeholder: 'Reason (required, shown to the requester)'});
        const confirm = node('button', {type: 'button', class: 'cr-ack-btn cr-reject-btn', text: 'Reject'});
        const cancel = node('button', {type: 'button', class: 'cr-ack-btn', text: 'Cancel'});
        confirm.addEventListener('click', () => {
            const reason = input.value.trim();
            if (!reason) { message('Enter a reason to reject this request.', 'error'); input.focus(); return; }
            post(state.rejectUrl, {id: String(r.id), reason})
                .then(() => { state.changed = true; message(''); loadHistory(); })
                .catch(e => message(e.message, 'error'));
        });
        cancel.addEventListener('click', () => { state.rejecting = null; message(''); renderHistory(); });
        input.addEventListener('keydown', e => { if (e.key === 'Enter') confirm.click(); });
        setTimeout(() => input.focus(), 0);
        return node('div', {class: 'cr-reject-form'}, [input, confirm, cancel]);
    }

    function renderHistory() {
        const list = state.history;
        const box = el('cr-list');
        box.replaceChildren();
        if (!list.length) { box.appendChild(node('div', {class: 'cr-hint', text: 'No request on this item.'})); return; }
        const newOnes = list.filter(r => r.status === 'new');
        if (state.canAck && newOnes.length) {
            const all = node('button', {type: 'button', class: 'cr-ack-btn', text: 'Acknowledge all (' + newOnes.length + ')'});
            all.addEventListener('click', () => acknowledge({key: state.key}));
            box.appendChild(node('div', {style: 'margin-bottom:8px; text-align:right'}, [all]));
        }
        list.forEach(r => {
            const when = new Date(r.date).toLocaleDateString('en-GB');
            const head = node('div', {}, [node('strong', {text: r.user}), node('span', {text: ' · ' + when})]);
            const body = node('div', {class: 'cr-entry-body'}, [head].concat(describe(r)));
            if (r.status === 'acknowledged' && r.acknowledged_by) {
                body.appendChild(node('div', {class: 'cr-hint', text: 'acknowledged by ' + r.acknowledged_by}));
            }
            if (r.status === 'rejected') {
                body.appendChild(node('div', {class: 'cr-hint cr-rejected-reason',
                    text: 'rejected' + (r.acknowledged_by ? ' by ' + r.acknowledged_by : '') + ': “' + r.reject_reason + '”'}));
            }
            if (state.rejecting === r.id) body.appendChild(rejectForm(r));
            const kids = [node('span', {class: 'cr-status ' + r.status, text: r.status}), body];
            if (state.canAck && r.status === 'new' && state.rejecting !== r.id) {
                const ack = node('button', {type: 'button', class: 'cr-ack-btn', text: 'Acknowledge'});
                ack.addEventListener('click', () => acknowledge({ids: String(r.id)}));
                const rej = node('button', {type: 'button', class: 'cr-ack-btn cr-reject-btn', text: 'Reject'});
                rej.addEventListener('click', () => { state.rejecting = r.id; message(''); renderHistory(); });
                kids.push(node('div', {class: 'cr-entry-actions'}, [ack, rej]));
            }
            box.appendChild(node('div', {class: 'cr-entry'}, kids));
        });
    }

    function acknowledge(params) {
        post(state.ackUrl, params)
            .then(() => { state.changed = true; loadHistory(); })
            .catch(e => message(e.message, 'error'));
    }

    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && state && el('requestModal').style.display === 'flex') closeRequests();
    });
    document.addEventListener('click', e => {
        if (state && e.target === el('requestModal')) closeRequests();
    });
})();
