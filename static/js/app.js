let table;
let selectedRows = new Set();
let editModal;
let recommendationValues = [];
let pendingCount = 0;

// Color map for recommendation badges
const REC_COLORS = {
    'EXISTING BA - EXISTING ADDRESS': '#28a745',
    'EXISTING BA - NEW ADDRESS': '#17a2b8',
    'EXISTING BA - LIKELY SAME ADDRESS': '#20c997',
    'NEW BA - NO DEC MATCH': '#6c757d',
    'NEW BA - NO SSN': '#fd7e14',
    'NEW BA - INVALID SSN': '#dc3545',
    'LIKELY NEW BA - SSN MATCH NAME MISMATCH': '#ffc107',
    'APPROVED': '#0d6efd'
};

$(document).ready(function() {
    editModal = new bootstrap.Modal(document.getElementById('editModal'));

    // Load recommendations for dropdowns, then init table
    $.get('/api/recommendations', function(recs) {
        recommendationValues = recs;

        // Populate filter dropdown
        recs.forEach(function(r) {
            $('#recommendationFilter').append(`<option value="${r}">${r}</option>`);
        });

        // Populate edit modal dropdown
        recs.forEach(function(r) {
            $('#editRecommendation').append(`<option value="${r}">${r}</option>`);
        });
        $('#editRecommendation').append('<option value="APPROVED">APPROVED</option>');

        initTable();
        loadStats();
    });

    // Select all
    $('#selectAll').on('change', function() {
        const checked = $(this).prop('checked');
        $('.row-select:visible').each(function() {
            $(this).prop('checked', checked);
            const id = $(this).data('row-id');
            checked ? selectedRows.add(id) : selectedRows.delete(id);
            $(this).closest('tr').toggleClass('row-selected', checked);
        });
        updateSelectionInfo();
    });


    // Auto-apply filters on dropdown change
    $('#recommendationFilter, #ssnFilter, #minNameScore, #minAddrScore').on('change', function() {
        applyFilters();
    });

    // Import type dropdown - open file picker on selection
    $('#importType').on('change', function() {
        if ($(this).val()) {
            $('#importFile').val('');
            $('#importFile').trigger('click');
        }
    });

    // File selected - read Canvas IDs and import
    $('#importFile').on('change', function() {
        const file = this.files[0];
        const field = $('#importType').val();
        if (!file || !field) return;

        const reader = new FileReader();
        reader.onload = function(e) {
            const text = e.target.result;
            // Parse lines, split by comma/newline, trim, filter blanks
            const ids = text.split(/[\r\n,]+/).map(s => s.trim()).filter(s => s && s !== '');
            if (ids.length === 0) {
                showToast('No Canvas IDs found in file', 'warning');
                $('#importType').val('');
                return;
            }

            $.ajax({
                url: '/api/import_ids',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ field: field, canvas_ids: ids }),
                success: function(data) {
                    showToast(data.message, 'success');
                    pendingCount = data.pending_count || 0;
                    updateSaveBtn();
                    table.ajax.reload();
                },
                error: function(xhr) {
                    const msg = xhr.responseJSON ? xhr.responseJSON.error : 'Import failed';
                    showToast(msg, 'error');
                }
            });
            $('#importType').val('');
        };
        reader.readAsText(file);
    });

    // Column-confined cell selection (click = single, Shift+click = range)
    let lastClickedCell = null;
    $('#matchesTable').on('click', 'tbody td', function(e) {
        if ($(e.target).is('input, button, i, a')) return;
        const td = $(this);
        const colIdx = td.index();

        if (e.shiftKey && lastClickedCell && lastClickedCell.colIdx === colIdx) {
            // Shift+click: select range in same column
            const rows = $('#matchesTable tbody tr:visible');
            const startRow = rows.index(lastClickedCell.tr);
            const endRow = rows.index(td.closest('tr'));
            const lo = Math.min(startRow, endRow);
            const hi = Math.max(startRow, endRow);
            $('.cell-selected').removeClass('cell-selected');
            rows.slice(lo, hi + 1).each(function() {
                $(this).find('td').eq(colIdx).addClass('cell-selected');
            });
        } else {
            // Single click: select one cell
            $('.cell-selected').removeClass('cell-selected');
            td.addClass('cell-selected');
            lastClickedCell = { colIdx: colIdx, tr: td.closest('tr')[0] };
        }
    });

    // Ctrl+C / Cmd+C: copy selected cell values
    $(document).on('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'c' && $('.cell-selected').length > 0) {
            e.preventDefault();
            const vals = $('.cell-selected').map(function() {
                return $(this).text().trim();
            }).get();
            navigator.clipboard.writeText(vals.join('\n'));
            showToast(`Copied ${vals.length} value(s)`, 'success');
        }
    });

    // Click outside table clears cell selection
    $(document).on('click', function(e) {
        if (!$(e.target).closest('#matchesTable tbody').length) {
            $('.cell-selected').removeClass('cell-selected');
        }
    });

    // Row selection
    $('#matchesTable tbody').on('change', '.row-select', function() {
        const id = $(this).data('row-id');
        const checked = $(this).prop('checked');
        checked ? selectedRows.add(id) : selectedRows.delete(id);
        $(this).closest('tr').toggleClass('row-selected', checked);
        updateSelectionInfo();
    });

    // JIB/Rev/Vendor checkbox toggle — applies to all cell-selected rows if any
    $('#matchesTable tbody').on('change', '.field-check', function() {
        const field = $(this).data('field');
        const value = $(this).prop('checked') ? 1 : 0;
        const selectedCells = $('.cell-selected');

        if (selectedCells.length > 1) {
            // Apply to all rows that have a selected cell
            const rowIds = [];
            const seen = new Set();
            selectedCells.each(function() {
                const tr = $(this).closest('tr');
                const cb = tr.find(`.field-check[data-field="${field}"]`);
                if (cb.length) {
                    const rid = cb.data('row-id');
                    if (!seen.has(rid)) {
                        seen.add(rid);
                        rowIds.push(rid);
                        cb.prop('checked', !!value);
                    }
                }
            });
            // Send all updates
            let completed = 0;
            rowIds.forEach(function(rid) {
                $.ajax({
                    url: '/api/update',
                    method: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify({ row_id: rid, field: field, value: value }),
                    success: function(data) {
                        pendingCount = data.pending_count || 0;
                        updateSaveBtn();
                        if (++completed === rowIds.length) {
                            showToast(`Set ${field.toUpperCase()} on ${rowIds.length} rows`, 'success');
                        }
                    },
                    error: function() { showToast('Toggle failed', 'error'); }
                });
            });
        } else {
            // Single row update
            const rowId = $(this).data('row-id');
            $.ajax({
                url: '/api/update',
                method: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({ row_id: rowId, field: field, value: value }),
                success: function(data) {
                    pendingCount = data.pending_count || 0;
                    updateSaveBtn();
                },
                error: function() { showToast('Toggle failed', 'error'); }
            });
        }
    });
});

function initTable() {
    table = $('#matchesTable').DataTable({
        processing: true,
        serverSide: true,
        autoWidth: false,
        ajax: {
            url: '/api/matches',
            data: function(d) {
                d.recommendation = $('#recommendationFilter').val();
                d.ssn_match = $('#ssnFilter').val();
                var minName = $('#minNameScore').val();
                if (minName) d.min_name_score = minName;
                var minAddr = $('#minAddrScore').val();
                if (minAddr) d.min_addr_score = minAddr;
            }
        },
        columns: [
            {   // 0: Checkbox
                data: null, orderable: false, className: 'text-center', width: '30px',
                render: function(data) {
                    return `<input type="checkbox" class="row-select" data-row-id="${data._row_id}">`;
                }
            },
            { data: 'ssn_match', render: ssnBadge, width: '42px' },           // 1: SSN
            { data: 'name_score', render: scoreBadge, width: '42px' },         // 2: Name
            { data: 'address_score', render: scoreBadge, width: '42px' },      // 3: Addr
            { data: 'recommendation', render: recBadge, className: 'rec-col', width: '210px' }, // 4: Rec
            { data: 'canvas_name', className: 'resizable' },                    // 5: Canvas Name
            { data: 'canvas_address', className: 'resizable' },               // 6: Canvas Addr
            {   // 7: Canvas City/St/Zip
                data: null, orderable: false, className: 'resizable',
                render: function(d) {
                    return `${d.canvas_city || ''}, ${d.canvas_state || ''} ${d.canvas_zip || ''}`;
                }
            },
            { data: 'canvas_id', width: '75px' },                             // 8: Canvas ID
            { data: 'dec_name', className: 'resizable' },                      // 9: DEC Name
            { data: 'dec_address', className: 'resizable' },                  // 10: DEC Addr
            {   // 11: DEC City/St/Zip
                data: null, orderable: false, className: 'resizable',
                render: function(d) {
                    return `${d.dec_city || ''}, ${d.dec_state || ''} ${d.dec_zip || ''}`;
                }
            },
            { data: 'dec_hdrcode', width: '65px' },                           // 12: DEC Code
            {   // 13: JIB
                data: 'jib', className: 'text-center', width: '35px',
                render: function(data, type, row) {
                    const checked = data ? 'checked' : '';
                    return `<input type="checkbox" class="field-check" data-row-id="${row._row_id}" data-field="jib" ${checked}>`;
                }
            },
            {   // 14: Rev
                data: 'rev', className: 'text-center', width: '35px',
                render: function(data, type, row) {
                    const checked = data ? 'checked' : '';
                    return `<input type="checkbox" class="field-check" data-row-id="${row._row_id}" data-field="rev" ${checked}>`;
                }
            },
            {   // 15: Vendor
                data: 'vendor', className: 'text-center', width: '50px',
                render: function(data, type, row) {
                    const checked = data ? 'checked' : '';
                    return `<input type="checkbox" class="field-check" data-row-id="${row._row_id}" data-field="vendor" ${checked}>`;
                }
            },
            {   // 16: Actions
                data: null, orderable: false, width: '70px',
                render: function(data) {
                    return `<button class="btn btn-sm btn-outline-primary py-0 px-1" onclick="editRecord(${data._row_id})" title="Edit"><i class="fas fa-edit"></i></button> <button class="btn btn-sm btn-outline-success py-0 px-1" onclick="quickApprove(${data._row_id})" title="Approve"><i class="fas fa-check"></i></button>`;
                }
            }
        ],
        pageLength: 100,
        lengthMenu: [[100, 500, 1000, 5000], [100, 500, '1,000', '5,000']],
        order: [[1, 'desc']],
        language: {
            processing: '<div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div>',
            lengthMenu: 'Show _MENU_'
        },
        drawCallback: function() {
            $('.row-select').each(function() {
                const id = $(this).data('row-id');
                if (selectedRows.has(id)) {
                    $(this).prop('checked', true);
                    $(this).closest('tr').addClass('row-selected');
                }
            });
        }
    });

    // Move DataTables length and search controls into the header
    $('#matchesTable_length').detach().appendTo('#dtLengthPlaceholder');
    $('#matchesTable_filter').detach().appendTo('#dtSearchPlaceholder');

    // Column resizing
    enableColumnResize('#matchesTable');
}

function enableColumnResize(tableSelector) {
    const $table = $(tableSelector);
    $table.css('table-layout', 'fixed');

    // Only add resize handles to columns whose td has class 'resizable'
    // DataTables applies className to td, so check which column indices are resizable
    const resizableIndices = new Set();
    $table.DataTable().columns().every(function(idx) {
        const col = this.settings()[0].aoColumns[idx];
        if (col.sClass && col.sClass.indexOf('resizable') !== -1) {
            resizableIndices.add(idx);
        }
    });

    const $ths = $table.find('thead th');
    $ths.each(function(idx) {
        if (!resizableIndices.has(idx)) return;
        const $th = $(this);
        $th.append('<div class="col-resize-handle"></div>');
    });

    // Drag logic
    let dragging = false, startX, startW, $dragTh;

    $table.on('mousedown', '.col-resize-handle', function(e) {
        e.preventDefault();
        e.stopPropagation();
        dragging = true;
        $dragTh = $(this).closest('th');
        startX = e.pageX;
        startW = $dragTh.outerWidth();
        $('body').addClass('col-resizing');
    });

    $(document).on('mousemove.colresize', function(e) {
        if (!dragging) return;
        const diff = e.pageX - startX;
        const newW = Math.max(50, startW + diff);
        $dragTh.css('width', newW + 'px');
    });

    $(document).on('mouseup.colresize', function() {
        if (dragging) {
            dragging = false;
            $dragTh = null;
            $('body').removeClass('col-resizing');
        }
    });
}

function ssnBadge(val) {
    if (val === 100) return '<span class="badge bg-success">Yes</span>';
    return '<span class="badge bg-danger">No</span>';
}

function scoreBadge(val) {
    if (val === '' || val === null || val === undefined) return '<span class="badge bg-secondary">-</span>';
    let cls = 'score-low';
    if (val === 100) cls = 'score-perfect';
    else if (val >= 90) cls = 'score-high';
    else if (val >= 75) cls = 'score-medium';
    return `<span class="score-badge ${cls}">${val}</span>`;
}

function recBadge(val) {
    if (!val) return '';
    const color = REC_COLORS[val] || '#6c757d';
    // Shorten for display
    let short = val;
    if (val.length > 25) {
        short = val.replace('EXISTING BA - ', '').replace('NEW BA - ', 'NEW: ').replace('LIKELY NEW BA - ', '~NEW: ');
    }
    return `<span class="badge" style="background-color:${color}; font-size:0.7rem; white-space:nowrap;" title="${val}">${short}</span>`;
}

function loadStats() {
    $.get('/api/stats', function(s) {
        $('#totalRecords').text(s.total_records.toLocaleString());
        $('#ssnPerfect').text(s.ssn_perfect_matches.toLocaleString());
        $('#ssnNone').text(s.ssn_no_match.toLocaleString());

        // Recommendation breakdown row
        let html = '';
        const recs = Object.entries(s.recommendations).sort((a, b) => b[1] - a[1]);
        recs.forEach(function([rec, count]) {
            const color = REC_COLORS[rec] || '#6c757d';
            const pct = ((count / s.total_records) * 100).toFixed(1);
            html += `<div class="col">
                <div class="card rec-card" style="border-left: 4px solid ${color}; cursor:pointer;" onclick="filterByRec('${rec}')">
                    <div class="card-body py-1 px-2">
                        <div class="small text-truncate" title="${rec}">${rec}</div>
                        <div class="fw-bold">${count.toLocaleString()} <span class="text-muted small">(${pct}%)</span></div>
                    </div>
                </div>
            </div>`;
        });
        $('#recBreakdown').html(html);
    });
}

function filterByRec(rec) {
    table.page.len(100).draw(false);
    $('#recommendationFilter').val(rec);
    $('#ssnFilter').val('');
    applyFilters();
}

function filterByStat(type) {
    table.page.len(100).draw(false);
    if (type === 'all') {
        clearFilters();
    } else if (type === 'ssn_yes') {
        $('#ssnFilter').val('yes');
        applyFilters();
    } else if (type === 'ssn_partial') {
        $('#ssnFilter').val('partial');
        applyFilters();
    } else if (type === 'ssn_no') {
        $('#ssnFilter').val('no');
        applyFilters();
    }
}

function applyFilters() {
    selectedRows.clear();
    $('#selectAll').prop('checked', false);
    updateSelectionInfo();
    table.ajax.reload();
}

function clearFilters() {
    $('#recommendationFilter').val('');
    $('#ssnFilter').val('');
    $('#minNameScore').val('');
    $('#minAddrScore').val('');
    applyFilters();
}

function refreshData() {
    loadStats();
    table.ajax.reload();
    showToast('Refreshed', 'success');
}

function updateSelectionInfo() {
    const n = selectedRows.size;
    $('#selectionInfo').text(n === 0 ? 'No records selected' : `${n} record(s) selected`);
    $('#bulkApproveBtn').prop('disabled', n === 0);
}

function editRecord(rowId) {
    $.get(`/api/record/${rowId}`, function(d) {
        $('#editRowId').val(d._row_id);

        // Canvas side
        $('#editCanvasName').text(d.canvas_name || '');
        $('#editCanvasAddress').text(d.canvas_address || '');
        $('#editCanvasCity').text(d.canvas_city || '');
        $('#editCanvasState').text(d.canvas_state || '');
        $('#editCanvasZip').text(d.canvas_zip || '');
        $('#editCanvasId').text(d.canvas_id || '');
        $('#editCanvasSSN').text(d.canvas_ssn || '');

        // DEC side
        $('#editDecName').val(d.dec_name || '');
        $('#editDecAddress').val(d.dec_address || '');
        $('#editDecCity').val(d.dec_city || '');
        $('#editDecState').val(d.dec_state || '');
        $('#editDecZip').val(d.dec_zip || '');
        $('#editDecContact').val(d.dec_contact || '');
        $('#editDecHdrcode').val(d.dec_hdrcode || '');

        // Scores
        setScoreBadgeEl('#editSsnMatch', d.ssn_match);
        setScoreBadgeEl('#editNameScore', d.name_score);
        setScoreBadgeEl('#editAddressScore', d.address_score);

        $('#editRecommendation').val(d.recommendation || '');
        $('#editAddressReason').val(d.address_reason || '');

        editModal.show();
    });
}

function setScoreBadgeEl(sel, val) {
    const el = $(sel);
    el.text(val != null ? val : '-');
    el.removeClass('score-perfect score-high score-medium score-low');
    if (val === 100) el.addClass('score-perfect');
    else if (val >= 90) el.addClass('score-high');
    else if (val >= 75) el.addClass('score-medium');
    else el.addClass('score-low');
}

function saveRecord() {
    const rowId = parseInt($('#editRowId').val());
    const fields = {
        'dec_name': $('#editDecName').val(),
        'dec_address': $('#editDecAddress').val(),
        'dec_city': $('#editDecCity').val(),
        'dec_state': $('#editDecState').val(),
        'dec_zip': $('#editDecZip').val(),
        'dec_contact': $('#editDecContact').val(),
        'dec_hdrcode': $('#editDecHdrcode').val(),
        'recommendation': $('#editRecommendation').val(),
        'address_reason': $('#editAddressReason').val()
    };

    let pending = Object.keys(fields).length;
    let errors = [];

    Object.entries(fields).forEach(([field, value]) => {
        $.ajax({
            url: '/api/update',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ row_id: rowId, field: field, value: value }),
            success: function() { if (--pending === 0) onSaveDone(errors); },
            error: function(xhr) {
                errors.push(field);
                if (--pending === 0) onSaveDone(errors);
            }
        });
    });
}

function onSaveDone(errors) {
    if (errors.length === 0) {
        showToast('Saved', 'success');
        editModal.hide();
        table.ajax.reload(null, false);
        loadStats();
    } else {
        showToast('Errors saving: ' + errors.join(', '), 'error');
    }
}

function quickApprove(rowId) {
    if (!confirm('Approve this match?')) return;
    $.ajax({
        url: '/api/update',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ row_id: rowId, field: 'recommendation', value: 'APPROVED' }),
        success: function() {
            showToast('Approved', 'success');
            table.ajax.reload(null, false);
            loadStats();
        },
        error: function(xhr) { showToast('Failed', 'error'); }
    });
}

function bulkApprove() {
    const n = selectedRows.size;
    if (n === 0) return;
    if (!confirm(`Approve ${n} selected record(s)?`)) return;

    $.ajax({
        url: '/api/bulk_update',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ row_ids: Array.from(selectedRows), recommendation: 'APPROVED' }),
        success: function(data) {
            showToast(`Approved ${data.updated} records`, 'success');
            selectedRows.clear();
            $('#selectAll').prop('checked', false);
            updateSelectionInfo();
            table.ajax.reload();
            loadStats();
        },
        error: function() { showToast('Bulk approve failed', 'error'); }
    });
}

function exportSelected() {
    if (selectedRows.size === 0) {
        showToast('No records selected', 'warning');
        return;
    }
    const ids = Array.from(selectedRows).join(',');
    window.location.href = `/api/export_selected?row_ids=${ids}`;
}

function exportData() {
    const rec = $('#recommendationFilter').val();
    let url = '/api/export';
    if (rec) url += `?recommendation=${encodeURIComponent(rec)}`;
    window.location.href = url;
}

function saveChanges() {
    if (pendingCount === 0) {
        showToast('Nothing to save', 'info');
        return;
    }

    $.ajax({
        url: '/api/save_changes',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({}),
        success: function(data) {
            showToast(data.message, 'success');
            pendingCount = 0;
            updateSaveBtn();
        },
        error: function(xhr) {
            const msg = xhr.responseJSON ? xhr.responseJSON.error : 'Save failed';
            showToast(msg, 'error');
        }
    });
}

function updateSaveBtn() {
    const btn = $('#saveChangesBtn');
    btn.prop('disabled', pendingCount === 0);
    btn.find('.save-count').text(pendingCount > 0 ? ` (${pendingCount})` : '');
}

function showToast(msg, type) {
    const colors = { success: '#28a745', error: '#dc3545', warning: '#ffc107', info: '#17a2b8' };
    const bg = colors[type] || colors.info;
    const toast = $(`<div class="toast-msg" style="background:${bg}">${msg}</div>`);
    $('body').append(toast);
    setTimeout(() => toast.fadeOut(300, function() { $(this).remove(); }), 2500);
}

// Toast styles
$('<style>').text(`
    .toast-msg {
        position: fixed; top: 70px; right: 20px; z-index: 10000;
        color: white; padding: 10px 20px; border-radius: 4px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3); font-size: 0.9rem;
        animation: slideIn 0.3s ease-out;
    }
    @keyframes slideIn {
        from { transform: translateX(300px); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
`).appendTo('head');
