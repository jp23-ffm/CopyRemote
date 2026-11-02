/* User change requests: comment or "these fields are wrong" (nothing is modified, admins review). */
(function () {
    let state = null;   // {key, urlBase, ackUrl, canAck, picked: {FIELD: true}, tab, changed}
    let allFields = [];

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

    window.openRequests = function (btn) {
        const data = document.getElementById('request-fields-data');
        allFields = data ? JSON.parse(data.textContent) : [];
        state = {
            key: btn.dataset.key, urlBase: btn.dataset.url, ackUrl: btn.dataset.ack,
            canAck: btn.dataset.canack === 'true', picked: {}, tab: 'fields', changed: false
        };
        el('cr-item').textContent = state.key.replace('|', '  ·  ');
        el('cr-comment').value = '';
        el('cr-reason').value = '';
        message('');
        el('requestModal').style.display = 'flex';
        render();
        loadHistory();
    };

    window.closeRequests = function () {
        el('requestModal').style.display = 'none';
        const reload = state && state.changed;
        state = null;
        if (reload) window.location.reload();   // refresh the badges in the table
    };

    window.switchRequestTab = function (tab) { state.tab = tab; message(''); render(); };

    function toggleField(name) {
        if (state.picked[name]) delete state.picked[name]; else state.picked[name] = true;
        render();
    }

    function render() {
        el('cr-tab-fields').classList.toggle('active', state.tab === 'fields');
        el('cr-tab-comment').classList.toggle('active', state.tab === 'comment');
        el('cr-pane-fields').style.display = state.tab === 'fields' ? '' : 'none';
        el('cr-pane-comment').style.display = state.tab === 'comment' ? '' : 'none';
        const n = Object.keys(state.picked).length;
        el('cr-count').textContent = n;
        el('cr-count').style.display = n ? '' : 'none';
        el('cr-reason-wrap').style.display = state.tab === 'fields' ? '' : 'none';

        const chips = el('cr-chips');
        chips.replaceChildren();
        allFields.forEach(f => {
            const b = node('button', {type: 'button', class: 'cr-chip', 'aria-pressed': state.picked[f.name] ? 'true' : 'false', text: f.label});
            b.addEventListener('click', () => toggleField(f.name));
            chips.appendChild(b);
        });

        // keep what the user already typed when re-rendering
        const typed = {};
        el('cr-grid').querySelectorAll('input[data-field]').forEach(i => { typed[i.dataset.field] = i.value; });
        const grid = el('cr-grid');
        grid.replaceChildren();
        if (!n) { grid.style.display = 'none'; el('cr-none').style.display = ''; return; }
        grid.style.display = ''; el('cr-none').style.display = 'none';
        ['Field', 'Current value', 'Expected value'].forEach(h => grid.appendChild(node('div', {class: 'cr-head', text: h})));
        allFields.filter(f => state.picked[f.name]).forEach(f => {
            const input = node('input', {type: 'text', 'data-field': f.name, 'aria-label': 'Expected value for ' + f.label, placeholder: 'Correct value', maxlength: '500'});
            input.value = typed[f.name] || '';
            grid.appendChild(node('div', {text: f.label, style: 'font-weight:600'}));
            grid.appendChild(node('div', {class: 'cr-current', text: currentValue(f.name) || '–'}));
            grid.appendChild(node('div', {}, [input]));
        });
    }

    window.submitRequest = function () {
        const key = state.key;
        let params;
        if (state.tab === 'comment') {
            const comment = el('cr-comment').value.trim();
            if (!comment) { message('The comment is empty.', 'error'); return; }
            params = {key, kind: 'comment', comment};
        } else {
            const changes = [];
            let missing = false;
            el('cr-grid').querySelectorAll('input[data-field]').forEach(i => {
                const v = i.value.trim();
                if (!v) missing = true;
                changes.push({field: i.dataset.field, proposed: v});
            });
            if (!changes.length) { message('Select at least one field.', 'error'); return; }
            if (missing) { message('Enter the expected value for every selected field.', 'error'); return; }
            params = {key, kind: 'fields', changes: JSON.stringify(changes), reason: el('cr-reason').value.trim()};
        }
        const btn = el('cr-send'); btn.disabled = true;
        post(state.urlBase, params)
            .then(() => {
                state.changed = true; state.picked = {};
                el('cr-comment').value = ''; el('cr-reason').value = '';
                message('Request sent. Thank you!', 'ok');
                render(); loadHistory();
            })
            .catch(e => message(e.message, 'error'))
            .finally(() => { btn.disabled = false; });
    };

    function loadHistory() {
        const box = el('cr-list');
        fetch(state.urlBase + '?key=' + encodeURIComponent(state.key))
            .then(r => r.json())
            .then(d => renderHistory(d.requests || []))
            .catch(() => { box.replaceChildren(node('div', {class: 'cr-hint', text: 'Could not load previous requests.'})); });
    }

    function describe(r) {
        if (r.kind === 'comment') return [node('span', {text: 'Comment: “' + r.comment + '”'})];
        const parts = r.changes.map(c => node('div', {text: c.label + ': “' + c.current + '” → “' + c.proposed + '”'}));
        if (r.reason) parts.push(node('div', {class: 'cr-hint', text: 'Why: ' + r.reason}));
        return parts;
    }

    function renderHistory(list) {
        const box = el('cr-list');
        box.replaceChildren();
        el('cr-history').style.display = list.length ? '' : 'none';
        const newOnes = list.filter(r => r.status === 'new');
        if (state.canAck && newOnes.length) {
            const all = node('button', {type: 'button', class: 'cr-ack-btn', text: 'Acknowledge all (' + newOnes.length + ')'});
            all.addEventListener('click', () => acknowledge({key: state.key}));
            box.appendChild(node('div', {style: 'margin-bottom:8px'}, [all]));
        }
        list.forEach(r => {
            const when = new Date(r.date).toLocaleDateString('en-GB');
            const head = node('div', {}, [node('strong', {text: r.user}), node('span', {text: ' · ' + when})]);
            const body = node('div', {class: 'cr-entry-body'}, [head].concat(describe(r)));
            if (r.status === 'acknowledged' && r.acknowledged_by) {
                body.appendChild(node('div', {class: 'cr-hint', text: 'acknowledged by ' + r.acknowledged_by}));
            }
            const kids = [node('span', {class: 'cr-status ' + r.status, text: r.status}), body];
            if (state.canAck && r.status === 'new') {
                const b = node('button', {type: 'button', class: 'cr-ack-btn', text: 'Acknowledge'});
                b.addEventListener('click', () => acknowledge({ids: String(r.id)}));
                kids.push(b);
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
