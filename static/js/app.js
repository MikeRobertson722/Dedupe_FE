let table;
let selectedRows = new Set();
let editModal;
let recommendationValues = [];

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

    // Row selection
    $('#matchesTable tbody').on('change', '.row-select', function() {
        const id = $(this).data('row-id');
        const checked = $(this).prop('checked');
        checked ? selectedRows.add(id) : selectedRows.delete(id);
        $(this).closest('tr').toggleClass('row-selected', checked);
        updateSelectionInfo();
    });
});

function initTable() {
    table = $('#matchesTable').DataTable({
        processing: true,
        serverSide: true,
        ajax: {
            url: '/api/matches',
            data: function(d) {
                d.recommendation = $('#recommendationFilter').val();
                d.ssn_match = $('#ssnFilter').val();
                var minName = $('#minNameScore').val();
                if (minName) d.min_name_score = minName;
            }
        },
        columns: [
            {
                data: null, orderable: false, className: 'text-center',
                render: function(data) {
                    return `<input type="checkbox" class="row-select" data-row-id="${data._row_id}">`;
                }
            },
            { data: 'ssn_match', render: scoreBadge },
            { data: 'name_score', render: scoreBadge },
            { data: 'address_score', render: scoreBadge },
            { data: 'recommendation', render: recBadge },
            { data: 'canvas_name', className: 'truncate' },
            { data: 'canvas_address', className: 'truncate' },
            {
                data: null, orderable: false,
                render: function(d) {
                    return `${d.canvas_city || ''}, ${d.canvas_state || ''} ${d.canvas_zip || ''}`;
                }
            },
            { data: 'dec_name', className: 'truncate' },
            { data: 'dec_address', className: 'truncate' },
            {
                data: null, orderable: false,
                render: function(d) {
                    return `${d.dec_city || ''}, ${d.dec_state || ''} ${d.dec_zip || ''}`;
                }
            },
            { data: 'dec_hdrcode' },
            {
                data: null, orderable: false,
                render: function(data) {
                    return `<button class="btn btn-sm btn-outline-primary py-0 px-1" onclick="editRecord(${data._row_id})" title="Edit"><i class="fas fa-edit"></i></button> <button class="btn btn-sm btn-outline-success py-0 px-1" onclick="quickApprove(${data._row_id})" title="Approve"><i class="fas fa-check"></i></button>`;
                }
            }
        ],
        pageLength: 25,
        lengthMenu: [[10, 25, 50, 100, 500], [10, 25, 50, 100, 500]],
        order: [[1, 'desc']],
        language: {
            processing: '<div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div>'
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
        $('#ssnPartial').text(s.ssn_partial_matches.toLocaleString());
        $('#ssnNone').text(s.ssn_no_match.toLocaleString());
        $('#avgNameScore').text(s.avg_name_score + '%');
        $('#avgAddressScore').text(s.avg_address_score + '%');

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
    $('#recommendationFilter').val(rec);
    applyFilters();
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

function exportData() {
    const rec = $('#recommendationFilter').val();
    let url = '/api/export';
    if (rec) url += `?recommendation=${encodeURIComponent(rec)}`;
    window.location.href = url;
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
