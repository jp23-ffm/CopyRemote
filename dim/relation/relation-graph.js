/**
 * relation-graph.js — Expandable server relation graph (D3 v7)
 *
 * Interaction model:
 *   - Open for a server → shows center node + all direct relations
 *   - Click property/server node  → expands in-place (fetches & adds children)
 *   - Click expanded node again   → collapses (removes its children)
 *   - If expansion > LIST_THRESHOLD → shows list panel instead of graph nodes
 *   - Click center node            → opens server detail modal
 */
(function () {
    'use strict';

    const LIST_THRESHOLD = 20;

    // ── Color palette (keyed by node.color or node.type) ─────────────────────
    const COLORS = {
        center:           '#22d3ee',
        server_satellite: '#22d3ee',
        hypervisor:       '#34d399',
        server:           '#34d399',
        app:              '#a78bfa',
        datacenter:       '#f97316',
        cluster:          '#fbbf24',
        env:              '#10b981',
        vms:              '#f97316',
        property:         '#94a3b8',
        group:            '#334155',
        property_center:  '#e11d48',
    };

    // ── Mutable graph state ───────────────────────────────────────────────────
    let graphNodes = [];
    let graphLinks = [];
    let expandedBy = new Map();  // nodeId → [childNodeIds added by its expansion]

    // ── D3 handles ────────────────────────────────────────────────────────────
    let simulation = null;
    let tooltip    = null;
    let g = null, linkG = null, nodeG = null;
    let currentW = 900, currentH = 520;

    // ── Public API ────────────────────────────────────────────────────────────
    window.openRelationsModal = function (hostname) {
        document.getElementById('relationsModal').style.display = 'flex';
        initGraph();
        loadInitial(hostname);
    };

    window.closeRelationsModal = function () {
        document.getElementById('relationsModal').style.display = 'none';
        cleanup();
    };

    window.closeListPanel = function () {
        document.getElementById('relationsListPanel').style.display = 'none';
    };

    window.filterList = function (q) {
        document.querySelectorAll('#relationsListItems li').forEach(li => {
            li.style.display = li.dataset.label.toLowerCase().includes(q.toLowerCase()) ? '' : 'none';
        });
    };

    window.relationsListItemClick = function (serverId) {
        document.getElementById('relationsListPanel').style.display = 'none';
        // Reset graph state and load the clicked server as new center
        graphNodes = [];
        graphLinks = [];
        expandedBy = new Map();
        if (simulation) { simulation.alpha(0); }
        if (nodeG) nodeG.selectAll('*').remove();
        if (linkG) linkG.selectAll('*').remove();
        loadInitial(serverId);
    };

    // ── Init / cleanup ────────────────────────────────────────────────────────
    function initGraph() {
        const container = document.getElementById('relationsGraph');
        container.innerHTML = '';
        graphNodes = [];
        graphLinks = [];
        expandedBy = new Map();

        currentW = container.clientWidth  || 900;
        currentH = container.clientHeight || 520;

        const svgEl = d3.select(container).append('svg')
            .attr('width', '100%').attr('height', '100%')
            .attr('viewBox', `0 0 ${currentW} ${currentH}`);

        // ── Defs: glow filters + grid pattern ────────────────────────────────
        const defs = svgEl.append('defs');

        // One feGaussianBlur-based glow per color key
        [...new Set(Object.keys(COLORS))].forEach(key => {
            const f = defs.append('filter').attr('id', `rg-glow-${key}`).attr('x', '-50%').attr('y', '-50%').attr('width', '200%').attr('height', '200%');
            f.append('feGaussianBlur').attr('stdDeviation', 5).attr('result', 'blur');
            const m = f.append('feMerge');
            m.append('feMergeNode').attr('in', 'blur');
            m.append('feMergeNode').attr('in', 'SourceGraphic');
        });

        // Subtle grid background
        const pat = defs.append('pattern')
            .attr('id', 'rg-grid').attr('width', 40).attr('height', 40)
            .attr('patternUnits', 'userSpaceOnUse');
        pat.append('path').attr('class', 'rg-grid-path').attr('d', 'M40,0 L0,0 0,40')
            .attr('fill', 'none').attr('stroke-width', 0.5);

        svgEl.insert('rect', ':first-child')
            .attr('width', '100%').attr('height', '100%')
            .attr('fill', 'url(#rg-grid)').attr('pointer-events', 'none');

        // Zoom / pan
        svgEl.call(d3.zoom().scaleExtent([0.15, 6])
            .on('zoom', e => g.attr('transform', e.transform)));

        g     = svgEl.append('g');
        linkG = g.append('g');
        nodeG = g.append('g');

        simulation = d3.forceSimulation()
            .force('link',    d3.forceLink().id(d => d.id).distance(d => {
                const t = findNode(tgtId(d));
                return (t?.type === 'server' || t?.type === 'server_satellite') ? 170 : 130;
            }))
            .force('charge',  d3.forceManyBody().strength(-280))
            .force('center',  d3.forceCenter(currentW / 2, currentH / 2).strength(0.04))
            .force('collide', d3.forceCollide(d => nodeRadius(d) + 24))
            .on('tick', onTick);

        tooltip = d3.select('body').append('div').attr('class', 'rg-tooltip').style('display', 'none');
    }

    function cleanup() {
        if (simulation) { simulation.stop(); simulation = null; }
        if (tooltip)    { tooltip.remove();  tooltip    = null; }
        g = linkG = nodeG = null;
        const c = document.getElementById('relationsGraph');
        if (c) c.innerHTML = '';
        const lp = document.getElementById('relationsListPanel');
        if (lp) lp.style.display = 'none';
        setInfoBar(null);
    }

    // ── Initial load ──────────────────────────────────────────────────────────
    function loadInitial(hostname) {
        setTitle(hostname);
        setMeta('');
        fetch(`/inventory/relations/${encodeURIComponent(hostname)}/`)
            .then(r => r.json())
            .then(data => {
                if (data.error) { setError(data.error); return; }
                graphNodes = data.nodes;
                graphLinks = data.links;

                const center = findNode(data.center);
                if (center) { center.fx = currentW / 2; center.fy = currentH / 2; }

                const relCount = graphNodes.filter(n => n.type !== 'center' && n.type !== 'group').length;
                setMeta(`${relCount} direct relation${relCount !== 1 ? 's' : ''}`);

                updateGraph();
            })
            .catch(e => setError(`Request failed: ${e}`));
    }

    // ── Expand / collapse ─────────────────────────────────────────────────────
    async function expandNode(node) {
        if (node.expanded) {
            collapseNode(node);
            return;
        }

        setNodeLoading(node.id, true);
        setInfoBarLoading(node);

        try {
            if (node.type === 'property') {
                if (!node.field || !node.value) return;

                const url = `/inventory/relations/property/?field=${enc(node.field)}&value=${enc(node.value)}`;
                const data = await fetchJson(url);
                if (data.error) return;

                // Show list panel if too many results
                if ((node.child_count ?? 0) > LIST_THRESHOLD) {
                    showListPanel(node, data);
                    return;
                }

                const newIds = [];
                data.nodes.forEach(n => {
                    if (n.id === data.center) return;  // skip property_center
                    if (!findNode(n.id)) {
                        n.x = scatter(node.x); n.y = scatter(node.y);
                        graphNodes.push(n);
                        newIds.push(n.id);
                    }
                    addLink(node.id, n.id);
                });

                expandedBy.set(node.id, newIds);
                node.expanded = true;

            } else if (node.type === 'vms') {
                if (!node.field || !node.value) return;

                const url = `/inventory/relations/property/?field=${enc(node.field)}&value=${enc(node.value)}`;
                const data = await fetchJson(url);
                if (data.error) return;

                if ((node.total ?? 0) > LIST_THRESHOLD) {
                    showListPanel(node, data);
                    return;
                }

                const newIds = [];
                data.nodes.forEach(n => {
                    if (n.id === data.center) return;
                    if (!findNode(n.id)) {
                        n.x = scatter(node.x); n.y = scatter(node.y);
                        graphNodes.push(n);
                        newIds.push(n.id);
                    }
                    addLink(node.id, n.id);
                });

                expandedBy.set(node.id, newIds);
                node.expanded = true;

            } else if (node.type === 'server' || node.type === 'server_satellite') {
                if (!node.pivot_id) return;

                const url = `/inventory/relations/${enc(node.pivot_id)}/`;
                const data = await fetchJson(url);
                if (data.error) return;

                const newIds = [];
                data.nodes.forEach(n => {
                    if (n.id === data.center) return;  // skip center (= current node)
                    if (!findNode(n.id)) {
                        n.x = scatter(node.x); n.y = scatter(node.y);
                        graphNodes.push(n);
                        newIds.push(n.id);
                    }
                });

                // Re-map links: replace data.center with node.id
                data.links.forEach(l => {
                    const s = l.source === data.center ? node.id : l.source;
                    const t = l.target === data.center ? node.id : l.target;
                    addLink(s, t);
                });

                expandedBy.set(node.id, newIds);
                node.expanded = true;
            }

            updateGraph();
        } finally {
            setNodeLoading(node.id, false);
        }
    }

    function collapseNode(node) {
        const childIds = expandedBy.get(node.id) || [];
        const toRemove = new Set();

        childIds.forEach(cid => {
            const sharedByOther = [...expandedBy.entries()]
                .filter(([k]) => k !== node.id)
                .some(([, ids]) => ids.includes(cid));
            if (!sharedByOther) {
                const child = findNode(cid);
                if (child?.expanded) collapseNode(child);
                toRemove.add(cid);
            }
        });

        // Remove nodes
        for (let i = graphNodes.length - 1; i >= 0; i--) {
            if (toRemove.has(graphNodes[i].id)) graphNodes.splice(i, 1);
        }

        // Remove all links touching removed nodes, or added specifically from this node to its children
        for (let i = graphLinks.length - 1; i >= 0; i--) {
            const s = srcId(graphLinks[i]);
            const t = tgtId(graphLinks[i]);
            if (toRemove.has(s) || toRemove.has(t) ||
                (s === node.id && childIds.includes(t))) {
                graphLinks.splice(i, 1);
            }
        }

        node.expanded = false;
        expandedBy.delete(node.id);

        updateGraph();
    }

    function removeNode(node) {
        // Collapse first to clean up children
        if (node.expanded) collapseNode(node);

        // Remove from any parent's expandedBy so parent state stays consistent
        for (const childIds of expandedBy.values()) {
            const idx = childIds.indexOf(node.id);
            if (idx !== -1) childIds.splice(idx, 1);
        }

        // Remove the node itself
        const ni = graphNodes.findIndex(n => n.id === node.id);
        if (ni !== -1) graphNodes.splice(ni, 1);

        // Remove all links touching this node
        for (let i = graphLinks.length - 1; i >= 0; i--) {
            if (srcId(graphLinks[i]) === node.id || tgtId(graphLinks[i]) === node.id)
                graphLinks.splice(i, 1);
        }

        updateGraph();
    }

    // ── D3 update pattern ─────────────────────────────────────────────────────
    function updateGraph() {
        if (!linkG || !nodeG || !simulation) return;

        // Links
        linkG.selectAll('line')
            .data(graphLinks, l => `${srcId(l)}|${tgtId(l)}`)
            .join(
                enter => enter.append('line')
                    .attr('stroke', l => linkColor(l))
                    .attr('stroke-width', 1.5)
                    .attr('stroke-opacity', 0)
                    .attr('stroke-dasharray', l => isDashed(l) ? '4,3' : null)
                    .call(s => s.transition().duration(400).attr('stroke-opacity', 0.35)),
                update => update,
                exit  => exit.transition().duration(200).attr('stroke-opacity', 0).remove()
            );

        // Nodes
        nodeG.selectAll('g.rg-node')
            .data(graphNodes, d => d.id)
            .join(
                enter => {
                    const sel = enter.append('g')
                        .attr('class', 'rg-node')
                        .style('opacity', 0)
                        .style('cursor', d => isClickable(d) ? 'pointer' : 'default')
                        .call(attachInteractions);
                    buildShapes(sel);
                    sel.transition().duration(350).style('opacity', 1);
                    return sel;
                },
                update => {
                    update.select('.rg-xring')
                        .transition().duration(250)
                        .attr('stroke-opacity', d => d.expanded ? 0.65 : 0);
                    update.style('cursor', d => isClickable(d) ? 'pointer' : 'default');
                    return update;
                },
                exit => exit.transition().duration(200).style('opacity', 0).remove()
            );

        simulation.nodes(graphNodes);
        simulation.force('link').links(graphLinks);
        simulation.alpha(0.3).restart();
    }

    function buildShapes(sel) {
        const col  = d => nodeColor(d);
        const gkey = d => d.color || d.type || 'property';
        const r    = d => nodeRadius(d);

        // ── Group nodes → rounded rectangle ──────────────────────────────────
        sel.filter(d => d.type === 'group')
            .append('rect')
            .attr('rx', 5).attr('ry', 5)
            .attr('width',  d => Math.max(56, d.label.length * 6.5 + 14))
            .attr('height', 20)
            .attr('x', d => -(Math.max(56, d.label.length * 6.5 + 14) / 2))
            .attr('y', -10)
            .attr('fill',         d => col(d) + '12')
            .attr('stroke',       d => col(d))
            .attr('stroke-width', 0.8)
            .attr('stroke-opacity', 0.5);

        // ── All other nodes → circles ─────────────────────────────────────────
        const circles = sel.filter(d => d.type !== 'group');

        // Outer glow halo
        circles.append('circle').attr('class', 'rg-halo')
            .attr('r', d => r(d) + 11).attr('fill', 'none')
            .attr('stroke', col).attr('stroke-width', 1)
            .attr('stroke-opacity', 0.1)
            .attr('filter', d => `url(#rg-glow-${gkey(d)})`);

        // Loading spinner ring (hidden by default, animated via CSS when .is-loading)
        circles.append('circle').attr('class', 'rg-load-ring')
            .attr('r', d => r(d) + 8).attr('fill', 'none')
            .attr('stroke', col).attr('stroke-width', 2)
            .attr('stroke-dasharray', '9,5')
            .style('display', 'none');

        // Expand indicator ring (pulsing dashes when expanded)
        circles.append('circle').attr('class', 'rg-xring')
            .attr('r', d => r(d) + 6).attr('fill', 'none')
            .attr('stroke', col).attr('stroke-width', 1.5)
            .attr('stroke-dasharray', '3,3')
            .attr('stroke-opacity', d => d.expanded ? 0.65 : 0);

        // Main circle
        circles.append('circle')
            .attr('r', r)
            .attr('fill',         d => col(d) + '18')
            .attr('stroke',       col)
            .attr('stroke-width', d => d.type === 'center' ? 2.5 : 1.5);

        // Count badge (number inside circle)
        circles.filter(d => (d.type === 'vms' && d.total > 0) ||
                            (d.type !== 'vms' && d.type !== 'center' && (d.child_count ?? 0) > 0))
            .append('text')
            .attr('text-anchor', 'middle').attr('dy', '0.35em')
            .attr('font-size', '9px').attr('font-family', 'monospace')
            .attr('fill', col).attr('fill-opacity', 0.7)
            .attr('pointer-events', 'none')
            .text(d => d.type === 'vms' ? d.total : d.child_count);

        // Main label
        sel.append('text').attr('class', 'rg-node-label')
            .attr('text-anchor', 'middle')
            .attr('dy', d => d.type === 'group' ? 18 : r(d) + 14)
            .attr('font-size',   d => d.type === 'center' ? '11px' : '10px')
            .attr('font-weight', d => ['center', 'group'].includes(d.type) ? '600' : '400')
            .attr('font-family', 'monospace')
            .attr('fill', col).attr('fill-opacity', 0.9)
            .attr('pointer-events', 'none')
            .text(d => truncate(d.label, 22));

        // Sub-label (field name)
        sel.filter(d => d.field_label && !['group', 'center'].includes(d.type))
            .append('text').attr('class', 'rg-node-sublabel')
            .attr('text-anchor', 'middle')
            .attr('dy', d => r(d) + 26)
            .attr('font-size', '9px').attr('font-family', 'monospace')
            .attr('fill', '#2d3e55').attr('pointer-events', 'none')
            .text(d => d.field_label);
    }

    function attachInteractions(sel) {
        sel
            .on('click', (e, d) => { e.stopPropagation(); onNodeClick(d); })
            .on('contextmenu', (e, d) => {
                if (d.type !== 'server' && d.type !== 'server_satellite') return;
                e.preventDefault();
                e.stopPropagation();
                showNodeContextMenu(e, d);
            })
            .on('mouseenter', (e, d) => {
                setInfoBar(d);
                if (d.type === 'vms' && d.vm_list?.length) showVmsTooltip(e, d);
            })
            .on('mousemove', e => moveTooltip(e))
            .on('mouseleave', () => {
                setInfoBar(null);
                if (tooltip) tooltip.style('display', 'none');
            })
            .call(d3.drag()
                .on('start', (e, d) => {
                    if (!e.active) simulation.alphaTarget(0.3).restart();
                    d.fx = d.x; d.fy = d.y;
                })
                .on('drag',  (e, d) => { d.fx = e.x; d.fy = e.y; })
                .on('end',   (e, d) => {
                    if (!e.active) simulation.alphaTarget(0);
                    if (d.type !== 'center') { d.fx = null; d.fy = null; }
                }));
    }

    function onTick() {
        if (!linkG || !nodeG) return;
        linkG.selectAll('line')
            .attr('x1', d => d.source.x ?? 0).attr('y1', d => d.source.y ?? 0)
            .attr('x2', d => d.target.x ?? 0).attr('y2', d => d.target.y ?? 0);
        nodeG.selectAll('g.rg-node')
            .attr('transform', d => `translate(${d.x ?? 0},${d.y ?? 0})`);
    }

    function onNodeClick(d) {
        if (d.type === 'center') {
            window.openServerModal?.(d.id, null);
            return;
        }
        if (d.type === 'group') return;
        expandNode(d);
    }

    // ── List panel ────────────────────────────────────────────────────────────
    function showListPanel(node, data) {
        const panel  = document.getElementById('relationsListPanel');
        const title  = document.getElementById('relationsListTitle');
        const items  = document.getElementById('relationsListItems');
        const count  = document.getElementById('relationsListCount');
        const filter = document.getElementById('relationsListFilter');

        if (filter) filter.value = '';
        title.textContent = `${node.field_label}: ${node.label}`;

        const servers = data.nodes.filter(n => n.type === 'server_satellite');
        items.innerHTML = servers.map(s =>
            `<li data-label="${escHtml(s.label)}" onclick="relationsListItemClick('${escHtml(s.id)}')">
                <span class="rg-list-icon">⬡</span>
                <span class="rg-list-id">${escHtml(s.label)}</span>
             </li>`
        ).join('');

        count.textContent = `${data.total} server${data.total !== 1 ? 's' : ''}` +
            (data.has_more ? ` (showing ${servers.length})` : '');

        panel.style.display = 'flex';
    }

    // ── Node loading state ───────────────────────────────────────────────────
    function setNodeLoading(nodeId, loading) {
        if (!nodeG) return;
        const sel = nodeG.selectAll('g.rg-node').filter(d => d.id === nodeId);
        sel.classed('is-loading', loading);
        sel.select('.rg-load-ring').style('display', loading ? null : 'none');
    }

    function setInfoBarLoading(node) {
        const bar = document.getElementById('relationsInfoBar');
        if (!bar) return;
        const col = nodeColor(node);
        const typeLabel = (node.field_label || node.type || '').toUpperCase();
        bar.innerHTML =
            `<span class="rg-info-type" style="color:${col}">${escHtml(typeLabel)}</span>` +
            `<span class="rg-info-name">${escHtml(node.label)}</span>` +
            `<span class="rg-info-hint rg-loading-text">Loading…</span>`;
    }

    // ── Info bar ──────────────────────────────────────────────────────────────
    function setInfoBar(node) {
        const bar = document.getElementById('relationsInfoBar');
        if (!bar) return;

        if (!node) {
            bar.innerHTML = '<span class="rg-info-hint">Click node to expand &nbsp;·&nbsp; Click again to collapse &nbsp;·&nbsp; Scroll to zoom</span>';
            return;
        }

        const col       = nodeColor(node);
        const typeLabel = (node.field_label || node.type || '').toUpperCase();
        let hint = '';

        if (node.type === 'center') {
            hint = 'click to open server details';
        } else if (node.type === 'property' && node.field) {
            const n = node.child_count ?? 0;
            if (node.expanded)           hint = 'expanded — click to collapse';
            else if (n > LIST_THRESHOLD) hint = `${n} servers — click to show list`;
            else if (n > 0)              hint = `${n} server${n > 1 ? 's' : ''} — click to expand`;
            else                         hint = 'click to expand';
        } else if (node.type === 'vms') {
            const n = node.total ?? 0;
            if (node.expanded)           hint = 'expanded — click to collapse';
            else if (n > LIST_THRESHOLD) hint = `${n} VMs — click to show list`;
            else if (n > 0)              hint = `${n} VM${n > 1 ? 's' : ''} — click to expand`;
        } else if (node.type === 'server' || node.type === 'server_satellite') {
            if (node.expanded)      hint = 'expanded — click to collapse · right-click for options';
            else if (node.pivot_id) hint = 'click to expand · right-click for options';
            else                    hint = 'not in inventory · right-click for options';
        }

        bar.innerHTML =
            `<span class="rg-info-type" style="color:${col}">${escHtml(typeLabel)}</span>` +
            `<span class="rg-info-name">${escHtml(node.label)}</span>` +
            (hint ? `<span class="rg-info-hint">${hint}</span>` : '');
    }

    // ── VMs tooltip ───────────────────────────────────────────────────────────
    function showVmsTooltip(e, d) {
        if (!tooltip) return;
        const items = d.vm_list.map(v => `<li>${escHtml(v)}</li>`).join('');
        const more  = d.has_more
            ? `<li style="color:#2d3e55;font-style:italic">… ${d.total - d.vm_list.length} more</li>` : '';
        tooltip.style('display', 'block')
            .html(`<strong>${escHtml(d.field_label || 'VMs')}</strong><ul>${items}${more}</ul>`);
        moveTooltip(e);
    }

    function moveTooltip(e) {
        if (tooltip?.style('display') !== 'none')
            tooltip.style('left', (e.pageX + 14) + 'px').style('top', (e.pageY - 10) + 'px');
    }

    // ── Node context menu ─────────────────────────────────────────────────────
    let rgContextMenu = null;

    function showNodeContextMenu(e, d) {
        hideNodeContextMenu();

        const serverId = d.pivot_id || d.id;
        const hasDetails = !!(window.openServerModal && window.serversData?.[serverId]);

        let html = `<div class="rg-ctx-header">${escHtml(d.label)}</div>`;
        html += hasDetails
            ? `<button class="rg-ctx-btn" data-action="details">View details</button>`
            : `<button class="rg-ctx-btn rg-ctx-disabled" disabled title="Server not in current view">View details</button>`;
        html += `<button class="rg-ctx-btn" data-action="explore">Set as root node</button>`;
        html += `<button class="rg-ctx-btn rg-ctx-danger" data-action="remove">Remove from graph</button>`;

        rgContextMenu = document.createElement('div');
        rgContextMenu.className = 'rg-context-menu';
        rgContextMenu.innerHTML = html;
        rgContextMenu.style.left = e.pageX + 'px';
        rgContextMenu.style.top  = e.pageY + 'px';
        document.body.appendChild(rgContextMenu);

        rgContextMenu.addEventListener('click', ev => {
            const action = ev.target.dataset.action;
            if (action === 'details') {
                hideNodeContextMenu();
                window.openServerModal(serverId, null);
            } else if (action === 'explore') {
                hideNodeContextMenu();
                relationsListItemClick(serverId);
            } else if (action === 'remove') {
                hideNodeContextMenu();
                removeNode(d);
            }
            ev.stopPropagation();
        });

        // Dismiss on next click anywhere
        setTimeout(() => document.addEventListener('click', hideNodeContextMenu, { once: true }), 0);
    }

    function hideNodeContextMenu() {
        if (rgContextMenu) { rgContextMenu.remove(); rgContextMenu = null; }
    }

    // ── Helpers ───────────────────────────────────────────────────────────────
    function nodeColor(d) {
        return COLORS[d.color] || COLORS[d.type] || COLORS.property;
    }

    function nodeRadius(d) {
        if (d.type === 'center')                                        return 26;
        if (d.type === 'server' || d.type === 'server_satellite')      return 18;
        if (d.type === 'vms')                                          return 18;
        if (d.type === 'group')                                        return 0;
        return 14;
    }

    function isClickable(d) {
        if (d.type === 'center')   return true;
        if (d.type === 'group')    return false;
        if (d.type === 'vms')      return false;
        if (d.type === 'property') return !!(d.field && d.value);
        if (d.type === 'vms')     return !!(d.field && d.value);
        if (d.type === 'server' || d.type === 'server_satellite') return !!d.pivot_id;
        return false;
    }

    function linkColor(l) {
        const t = findNode(tgtId(l));
        return COLORS[t?.color] || COLORS[t?.type] || COLORS.property;
    }

    function isDashed(l) {
        const t = findNode(tgtId(l));
        return t?.type === 'property' || t?.type === 'server_satellite';
    }

    function srcId(l) { return typeof l.source === 'object' ? l.source.id : l.source; }
    function tgtId(l) { return typeof l.target === 'object' ? l.target.id : l.target; }

    function findNode(id) { return graphNodes.find(n => n.id === id); }

    function addLink(s, t) {
        if (!graphLinks.find(l => srcId(l) === s && tgtId(l) === t))
            graphLinks.push({ source: s, target: t });
    }

    function scatter(v) { return (v ?? (currentW / 2)) + (Math.random() - 0.5) * 80; }

    function truncate(s, n) { return s && s.length > n ? s.slice(0, n - 1) + '…' : (s || ''); }

    function enc(s) { return encodeURIComponent(s); }

    function escHtml(s) {
        return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function setTitle(hostname) {
        document.getElementById('relationsModalTitle').textContent = hostname;
    }

    function setMeta(text) {
        const el = document.getElementById('relationsMeta');
        if (el) el.textContent = text;
    }

    function setError(msg) {
        const c = document.getElementById('relationsGraph');
        if (c) c.innerHTML = `<div class="rg-error">${escHtml(msg)}</div>`;
    }

    async function fetchJson(url) {
        try {
            const r = await fetch(url);
            return r.json();
        } catch (e) {
            return { error: String(e) };
        }
    }

    // ── Modal lifecycle ───────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        const modal = document.getElementById('relationsModal');
        if (!modal) return;
        modal.addEventListener('click', e => { if (e.target === modal) closeRelationsModal(); });
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape' && modal.style.display === 'flex') {
                // Let the details modal handle Escape if it's open
                const detailsModal = document.getElementById('serverDetailsModal');
                if (detailsModal?.style.display === 'block') return;
                closeRelationsModal();
            }
        });
    });
})();
