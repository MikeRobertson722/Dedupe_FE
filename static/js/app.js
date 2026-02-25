let gridApi;
let selectedRows = new Set();
let editModal;
let recommendationValues = [];
let pendingCount = 0;
let allRowData = [];
let activeRecFilter = '';

// Undo/Redo stacks
var undoStack = [];
var redoStack = [];
var UNDO_MAX = 50;

// Pattern to detect "do not use" variations
const DO_NOT_USE_RE = /do\s*n[o']?t\s*use|don['\u2019]t\s*use|d\.?n\.?u\.?(?!\w)/i;

// Preferred display order for recommendations
const REC_ORDER = [
    'NEW BA AND NEW ADDRESS',
    'EXISTING BA ADD NEW ADDRESS',
    'EXISTING BA AND EXISTING ADDRESS',
    'NEEDS REVIEW',
    'PROCESSED'
];

// Color map for recommendation badges
const REC_COLORS = {
    'NEW BA AND NEW ADDRESS': '#6c757d',
    'EXISTING BA ADD NEW ADDRESS': '#fd7e14',
    'EXISTING BA AND EXISTING ADDRESS': '#28a745',
    'NEEDS REVIEW': '#ffc107',
    'PROCESSED': '#0d6efd'
};

const PROCESS_OPTS = ['Add new BA and address', 'Add address to existing BA', 'Merge BA and address', 'Manual Review - DNP'];

function sortByRecOrder(items) {
    return items.sort(function(a, b) {
        const keyA = typeof a === 'string' ? a : a[0];
        const keyB = typeof b === 'string' ? b : b[0];
        let idxA = REC_ORDER.indexOf(keyA);
        let idxB = REC_ORDER.indexOf(keyB);
        if (idxA === -1) idxA = 999;
        if (idxB === -1) idxB = 999;
        return idxA - idxB;
    });
}

// ── Recommendation filter dropdown ──
function buildRecFilterDropdown(recs) {
    var $c = $('#recFilterContainer');
    var html = '<div class="dropdown rec-multi-dropdown">';
    html += '<button class="btn btn-sm btn-outline-secondary dropdown-toggle w-100 text-start" type="button" data-bs-toggle="dropdown" data-bs-auto-close="outside" id="recFilterBtn">';
    html += '<span class="rec-filter-label">All</span>';
    html += '</button>';
    html += '<div class="dropdown-menu rec-filter-menu">';
    html += '<div class="d-flex gap-2 px-2 py-1 border-bottom">';
    html += '<a href="#" class="small text-primary" onclick="toggleAllRecs(true);return false;">Select All</a>';
    html += '<a href="#" class="small text-danger" onclick="toggleAllRecs(false);return false;">Clear All</a>';
    html += '</div>';
    recs.forEach(function(r) {
        var color = REC_COLORS[r] || '#6c757d';
        html += '<label class="dropdown-item rec-filter-item d-flex align-items-center gap-2 py-1">';
        html += '<input type="checkbox" class="rec-check form-check-input mt-0" value="' + r + '">';
        html += '<span class="badge" style="background-color:' + color + '; font-size:0.7rem;">' + r + '</span>';
        html += '</label>';
    });
    html += '</div></div>';
    $c.html(html);
    $c.on('change', '.rec-check', function() {
        updateRecFilterLabel();
        onExternalFilterChanged();
    });
}

function getSelectedRecs() {
    var checked = [];
    $('.rec-check:checked').each(function() { checked.push($(this).val()); });
    return checked;
}

function updateRecFilterLabel() {
    var checked = getSelectedRecs();
    var label;
    if (checked.length === 0) label = 'All';
    else if (checked.length === 1) label = checked[0];
    else label = checked.length + ' selected';
    $('.rec-filter-label').text(label);
}

function toggleAllRecs(selectAll) {
    $('.rec-check').prop('checked', selectAll);
    updateRecFilterLabel();
    onExternalFilterChanged();
}

// ── Column visibility dropdown ──
const COL_DEFS = [
    ['UID', '#212529', 'uid', false],
    ['SSN', '#212529', 'ssn_match'],
    ['Name Score', '#212529', 'name_score'],
    ['Addr Score', '#212529', 'address_score'],
    ['N+A', '#212529', 'nameaddrscore', false],
    ['Status', '#212529', 'recommendation'],
    ['Process', '#212529', 'how_to_process'],
    ['Canvas Name', '#1e3a8a', 'canvas_name'],
    ['Canvas Addr', '#1e3a8a', 'canvas_address'],
    ['Canvas City/St/Zip', '#1e3a8a', 'canvas_csz'],
    ['Canvas ID', '#1e3a8a', 'canvas_id', false],
    ['DEC Name', '#9b4d6e', 'dec_name'],
    ['DEC Addr', '#9b4d6e', 'dec_address'],
    ['DEC City/St/Zip', '#9b4d6e', 'dec_csz'],
    ['DEC Code', '#9b4d6e', 'dec_hdrcode', false],
    ['Address Lookup', '#9b4d6e', 'dec_address_looked_up', false],
    ['JIB', '#212529', 'jib', false],
    ['Rev', '#212529', 'rev', false],
    ['Vendor', '#212529', 'vendor', false],
    ['Memo', '#212529', 'memo', false]
];

function buildColVisDropdown() {
    var html = '<div class="dropdown col-vis-dropdown">';
    html += '<button class="btn btn-sm btn-outline-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" data-bs-auto-close="outside">';
    html += '<i class="fas fa-columns"></i> Show/Hide Columns';
    html += '</button>';
    html += '<div class="dropdown-menu col-vis-menu">';
    html += '<div class="d-flex gap-2 px-2 py-1 border-bottom">';
    html += '<a href="#" class="small text-primary" onclick="toggleAllCols(true);return false;">Show All</a>';
    html += '<a href="#" class="small text-danger" onclick="toggleAllCols(false);return false;">Hide All</a>';
    html += '</div>';
    COL_DEFS.forEach(function(def) {
        var label = def[0], color = def[1], colName = def[2];
        var defaultVisible = def.length > 3 ? def[3] : true;
        var checkedAttr = defaultVisible ? ' checked' : '';
        var style = color ? 'background-color:' + color + ';color:#fff;border-radius:3px;padding:1px 6px;' : '';
        html += '<label class="dropdown-item col-vis-item d-flex align-items-center gap-2 py-1">';
        html += '<input type="checkbox" class="col-vis-check form-check-input mt-0" data-col-name="' + colName + '"' + checkedAttr + '>';
        html += '<span class="small" style="' + style + '">' + label + '</span>';
        html += '</label>';
    });
    html += '</div></div>';
    $('#colVisContainer').html(html);

    $('#colVisContainer').on('change', '.col-vis-check', function() {
        var colName = $(this).data('col-name');
        var visible = $(this).prop('checked');
        gridApi.setColumnsVisible([colName], visible);
    });
}

function toggleAllCols(show) {
    $('.col-vis-check').each(function() {
        $(this).prop('checked', show);
        var colName = $(this).data('col-name');
        gridApi.setColumnsVisible([colName], show);
    });
}

// ── External filter state ──
function isExternalFilterPresent() {
    if (activeRecFilter) return true;
    if ($('#ssnFilter').val()) return true;
    if ($('#minNameScore').val()) return true;
    if ($('#maxNameScore').val()) return true;
    if ($('#minAddrScore').val()) return true;
    if ($('#maxAddrScore').val()) return true;
    return false;
}

function doesExternalFilterPass(node) {
    var data = node.data;

    // Recommendation filter
    if (activeRecFilter && data.recommendation !== activeRecFilter) return false;

    // SSN filter
    var ssn = $('#ssnFilter').val();
    if (ssn === 'yes' && data.ssn_match !== 100) return false;
    if (ssn === 'no' && data.ssn_match !== 0) return false;
    if (ssn === 'partial' && (data.ssn_match <= 0 || data.ssn_match >= 100)) return false;

    // Score filters
    var minName = $('#minNameScore').val();
    if (minName && (data.name_score === '' || Number(data.name_score) < Number(minName))) return false;
    var maxName = $('#maxNameScore').val();
    if (maxName && (data.name_score === '' || Number(data.name_score) > Number(maxName))) return false;
    var minAddr = $('#minAddrScore').val();
    if (minAddr && (data.address_score === '' || Number(data.address_score) < Number(minAddr))) return false;
    var maxAddr = $('#maxAddrScore').val();
    if (maxAddr && (data.address_score === '' || Number(data.address_score) > Number(maxAddr))) return false;

    return true;
}

function onExternalFilterChanged() {
    if (!gridApi) return;
    gridApi.deselectAll();
    selectedRows.clear();
    updateSelectionInfo();
    gridApi.onFilterChanged();
    updateGridInfo();
}

function updateGridInfo() {
    if (!gridApi) return;
    var displayed = 0;
    gridApi.forEachNodeAfterFilterAndSort(function() { displayed++; });
    var total = allRowData.length;
    $('#gridInfo').text('Showing ' + displayed.toLocaleString() + ' of ' + total.toLocaleString() + ' records');
}

// ── Cell renderers ──
function ssnCellRenderer(params) {
    if (params.value === 100) return '<span class="badge bg-success" style="font-size:0.6rem;line-height:16px;padding:0 4px;">Yes</span>';
    return '<span class="badge bg-danger" style="font-size:0.6rem;line-height:16px;padding:0 4px;">No</span>';
}

function scoreCellRenderer(params) {
    var val = params.value;
    if (val === '' || val === null || val === undefined) return '<span class="badge bg-secondary" style="font-size:0.6rem;line-height:16px;padding:0 4px;">-</span>';
    var cls = 'score-low';
    if (val === 100) cls = 'score-perfect';
    else if (val >= 90) cls = 'score-high';
    else if (val >= 75) cls = 'score-medium';
    return '<span class="score-badge ' + cls + '">' + val + '</span>';
}

function recCellRenderer(params) {
    var val = params.value;
    if (!val) return '';
    var color = REC_COLORS[val] || '#6c757d';
    return '<span class="badge" style="background-color:' + color + '; font-size:0.6rem; white-space:nowrap; line-height:18px; padding:0 4px;" title="' + val + '">' + val + '</span>';
}

function processValueGetter(params) {
    var val = params.data.how_to_process || '';
    if (!val) {
        var rec = (params.data.recommendation || '').toUpperCase();
        if (rec === 'NEW BA AND NEW ADDRESS') val = 'Add new BA and address';
        else if (rec === 'EXISTING BA ADD NEW ADDRESS') val = 'Add address to existing BA';
        else if (rec === 'EXISTING BA AND EXISTING ADDRESS') val = 'Merge BA and address';
    }
    return val;
}

function checkboxCellRenderer(params) {
    var checked = params.value ? 'checked' : '';
    return '<input type="checkbox" class="field-check" data-row-id="' + params.data._row_id + '" data-field="' + params.colDef.field + '" ' + checked + '>';
}

function addressLookupCellRenderer(params) {
    var checked = (params.value === 1 || params.value === '1') ? 'checked' : '';
    return '<input type="checkbox" ' + checked + ' disabled>';
}

function memoCellRenderer(params) {
    var val = params.value || '';
    var escaped = val.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    return '<span class="memo-text" data-row-id="' + params.data._row_id + '" style="font-size:0.75rem;cursor:pointer;" title="Click to edit">' + escaped + '</span>';
}

function actionsCellRenderer(params) {
    var rid = params.data._row_id;
    return '<button class="btn btn-sm btn-outline-primary py-0 px-1" onclick="editRecord(' + rid + ')" title="Edit"><i class="fas fa-edit"></i></button> ' +
           '<button class="btn btn-sm btn-outline-success py-0 px-1" onclick="quickApprove(' + rid + ')" title="Approve"><i class="fas fa-check"></i></button>';
}

function canvasIdValueGetter(params) {
    var d = params.data;
    var seq = d.canvas_addrseq || '';
    return seq ? (d.canvas_id || '') + '-' + seq : (d.canvas_id || '');
}

function canvasCszValueGetter(params) {
    var d = params.data;
    return (d.canvas_city || '') + ', ' + (d.canvas_state || '') + ' ' + (d.canvas_zip || '');
}

function decCszValueGetter(params) {
    var d = params.data;
    return (d.dec_city || '') + ', ' + (d.dec_state || '') + ' ' + (d.dec_zip || '');
}

function decCodeValueGetter(params) {
    var d = params.data;
    var code = d.dec_hdrcode || '';
    var sub = d.dec_addrsubcode || '';
    return sub ? code + '-' + sub : code;
}

// ── AG Grid init ──
function initGrid() {
    var columnDefs = [
        { headerName: 'UID', field: 'id', colId: 'uid', width: 60, hide: true },
        { headerName: 'SSN', field: 'ssn_match', colId: 'ssn_match', cellRenderer: ssnCellRenderer, width: 62 },
        { headerName: 'Name', field: 'name_score', colId: 'name_score', cellRenderer: scoreCellRenderer, width: 80,
          tooltipValueGetter: function(p) {
              if (p.value !== '' && p.value !== null && p.value < 45) return 'This may be low because name may exist in address field';
              return null;
          }
        },
        { headerName: 'Addr', field: 'address_score', colId: 'address_score', cellRenderer: scoreCellRenderer, width: 76,
          tooltipValueGetter: function(p) {
              if (p.value !== '' && p.value !== null && p.value > 45 &&
                  p.data.recommendation && p.data.recommendation.toUpperCase().indexOf('NEW ADDRESS') !== -1) {
                  return 'May have status of new address since numbers in address may not match';
              }
              return null;
          }
        },
        { headerName: 'N+A', field: 'nameaddrscore', colId: 'nameaddrscore', width: 66, hide: true,
          cellRenderer: function(params) {
            var rec = (params.data && params.data.recommendation || '').toUpperCase();
            if (rec !== 'NEEDS REVIEW') return '<span class="badge bg-secondary" style="font-size:0.6rem;line-height:16px;padding:0 4px;" title="Not Scored - Only NEEDS REVIEW scored">NS</span>';
            return scoreCellRenderer(params);
          }
        },
        { headerName: 'Status', field: 'recommendation', colId: 'recommendation', cellRenderer: recCellRenderer, width: 220 },
        { headerName: 'Process', field: 'how_to_process', colId: 'how_to_process', width: 160,
          editable: true,
          cellEditor: 'agSelectCellEditor',
          cellEditorParams: { values: PROCESS_OPTS },
          cellStyle: { fontSize: '0.75rem', cursor: 'pointer' },
          valueGetter: processValueGetter,
          valueSetter: function(params) {
              params.data.how_to_process = params.newValue;
              return true;
          }
        },
        { headerName: 'Canvas Name', field: 'canvas_name', colId: 'canvas_name', minWidth: 140, flex: 1,
          headerClass: 'ag-header-canvas', wrapText: false,
          cellClassRules: { 'do-not-use-cell': function(p) { return p.value && DO_NOT_USE_RE.test(p.value); } }
        },
        { headerName: 'Canvas Addr', field: 'canvas_address', colId: 'canvas_address', minWidth: 140, flex: 1,
          headerClass: 'ag-header-canvas', wrapText: false,
          cellClassRules: { 'do-not-use-cell': function(p) { return p.value && DO_NOT_USE_RE.test(p.value); } }
        },
        { headerName: 'Canvas City/St/Zip', colId: 'canvas_csz', valueGetter: canvasCszValueGetter, width: 160,
          headerClass: 'ag-header-canvas' },
        { headerName: 'Canvas ID', field: 'canvas_id', colId: 'canvas_id', valueGetter: canvasIdValueGetter, width: 100,
          headerClass: 'ag-header-canvas', hide: true },
        { headerName: 'DEC Name', field: 'dec_name', colId: 'dec_name', minWidth: 140, flex: 1,
          headerClass: 'ag-header-dec', wrapText: false,
          cellClassRules: { 'do-not-use-cell': function(p) { return p.value && DO_NOT_USE_RE.test(p.value); } }
        },
        { headerName: 'DEC Addr', field: 'dec_address', colId: 'dec_address', minWidth: 140, flex: 1,
          headerClass: 'ag-header-dec', wrapText: false,
          cellClassRules: { 'do-not-use-cell': function(p) { return p.value && DO_NOT_USE_RE.test(p.value); } }
        },
        { headerName: 'DEC City/St/Zip', colId: 'dec_csz', valueGetter: decCszValueGetter, width: 160,
          headerClass: 'ag-header-dec' },
        { headerName: 'DEC Code', field: 'dec_hdrcode', colId: 'dec_hdrcode', valueGetter: decCodeValueGetter, width: 100,
          headerClass: 'ag-header-dec', hide: true },
        { headerName: 'Address Lookup', field: 'dec_address_looked_up', colId: 'dec_address_looked_up',
          cellRenderer: addressLookupCellRenderer, width: 55, headerClass: 'ag-header-dec', hide: true },
        { headerName: 'JIB', field: 'jib', colId: 'jib', cellRenderer: checkboxCellRenderer, width: 45, hide: true },
        { headerName: 'Rev', field: 'rev', colId: 'rev', cellRenderer: checkboxCellRenderer, width: 45, hide: true },
        { headerName: 'Vendor', field: 'vendor', colId: 'vendor', cellRenderer: checkboxCellRenderer, width: 55, hide: true },
        { headerName: 'Memo', field: 'memo', colId: 'memo', cellRenderer: memoCellRenderer, width: 160, hide: true },
        { headerName: 'Actions', colId: 'actions', cellRenderer: actionsCellRenderer, width: 80,
          sortable: false, filter: false, hide: true, pinned: 'right' }
    ];

    var gridOptions = {
        columnDefs: columnDefs,
        rowData: [],
        getRowId: function(params) { return String(params.data._row_id); },
        defaultColDef: {
            sortable: true,
            resizable: true,
            filter: false,
            suppressMenu: true
        },
        rowSelection: {
            mode: 'multiRow',
            checkboxes: true,
            headerCheckbox: true,
            selectAll: 'currentPage',
            enableClickSelection: false
        },
        selectionColumnDef: {
            pinned: 'left',
            width: 35,
            suppressMovable: true
        },
        rowHeight: 24,
        headerHeight: 26,
        animateRows: false,
        rowBuffer: 10,
        pagination: false,
        suppressCellFocus: false,
        tooltipShowDelay: 300,
        isExternalFilterPresent: isExternalFilterPresent,
        doesExternalFilterPass: doesExternalFilterPass,
        rowClassRules: {
            'trust-highlight': function(params) {
                var v = params.data.is_trust;
                return v === 1 || v === true || v === '1' || v === 'true' || v === 'True';
            }
        },
        singleClickEdit: true,
        onCellValueChanged: function(params) {
            if (params.colDef.field === 'how_to_process' && params.oldValue !== params.newValue && !window._bulkProcessUpdate) {
                // Check if multiple Process cells are shift-selected
                var selectedCells = $('.cell-selected[col-id="how_to_process"]');
                if (selectedCells.length > 1) {
                    var undoChanges = [];
                    var chosen = params.newValue;
                    window._bulkProcessUpdate = true;
                    // Include the edited cell in undo
                    undoChanges.push({ rowId: params.data._row_id, field: 'how_to_process', oldValue: params.oldValue || '', newValue: chosen });
                    saveProcessValue(params.data._row_id, chosen);
                    // Apply to other selected cells
                    selectedCells.each(function() {
                        var rowEl = $(this).closest('.ag-row');
                        var rowId = rowEl.attr('row-id');
                        var rowNode = gridApi.getRowNode(rowId);
                        if (!rowNode || rowNode.data._row_id === params.data._row_id) return;
                        var oldVal = rowNode.data.how_to_process || '';
                        if (oldVal !== chosen) {
                            undoChanges.push({ rowId: rowNode.data._row_id, field: 'how_to_process', oldValue: oldVal, newValue: chosen });
                            rowNode.setDataValue('how_to_process', chosen);
                            saveProcessValue(rowNode.data._row_id, chosen);
                        }
                    });
                    window._bulkProcessUpdate = false;
                    pushUndo({ type: 'single', changes: undoChanges });
                } else {
                    pushUndo({ type: 'single', changes: [{ rowId: params.data._row_id, field: 'how_to_process', oldValue: params.oldValue || '', newValue: params.newValue }] });
                    saveProcessValue(params.data._row_id, params.newValue);
                }
            }
        },
        onGridReady: function(params) {
            loadGridData();
        },
        onPaginationChanged: function() {
            updateGridInfo();
        },
        onSelectionChanged: function() {
            selectedRows.clear();
            gridApi.getSelectedNodes().forEach(function(node) {
                selectedRows.add(node.data._row_id);
            });
            updateSelectionInfo();
        },
        getRowClass: undefined
    };

    var gridDiv = document.getElementById('matchesGrid');
    gridApi = agGrid.createGrid(gridDiv, gridOptions);
}

function loadGridData() {
    fetch('/api/matches_all')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            allRowData = data;
            gridApi.setGridOption('rowData', data);
            updateGridInfo();
        })
        .catch(function(err) {
            console.error('Failed to load data:', err);
            showToast('Failed to load data', 'error');
        });
}

function refreshGridData() {
    fetch('/api/matches_all')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            allRowData = data;
            gridApi.setGridOption('rowData', data);
            updateGridInfo();
        });
}

// ── Document ready ──
$(document).ready(function() {
    editModal = new bootstrap.Modal(document.getElementById('editModal'));
    $.get('/api/recommendations', function(recs) {
        recommendationValues = sortByRecOrder(recs.slice());
        buildRecFilterDropdown(recommendationValues);
        recommendationValues.forEach(function(r) {
            $('#editRecommendation').append('<option value="' + r + '">' + r + '</option>');
        });
        $('#editRecommendation').append('<option value="PROCESSED">PROCESSED</option>');
        initGrid();
        loadStats();
    });

    // Filter dropdowns trigger external filter
    $('#ssnFilter, #minNameScore, #maxNameScore, #minAddrScore, #maxAddrScore').on('change', function() {
        onExternalFilterChanged();
    });


    // Quick filter (search)
    var quickFilterTimer;
    $('#quickFilterInput').on('input', function() {
        var val = $(this).val();
        clearTimeout(quickFilterTimer);
        quickFilterTimer = setTimeout(function() {
            gridApi.setGridOption('quickFilterText', val);
            updateGridInfo();
        }, 300);
    });

    // Import type dropdown
    $('#importType').on('change', function() {
        if ($(this).val()) { $('#importFile').val(''); $('#importFile').trigger('click'); }
    });

    // File import
    $('#importFile').on('change', function() {
        var file = this.files[0];
        var field = $('#importType').val();
        if (!file || !field) return;
        var reader = new FileReader();
        reader.onload = function(e) {
            var ids = e.target.result.split(/[\r\n,]+/).map(function(s) { return s.trim(); }).filter(function(s) { return s && s !== ''; });
            if (ids.length === 0) { showToast('No Canvas IDs found in file', 'warning'); $('#importType').val(''); return; }
            $.ajax({
                url: '/api/import_ids', method: 'POST', contentType: 'application/json',
                data: JSON.stringify({ field: field, canvas_ids: ids }),
                success: function(data) {
                    showToast(data.message, 'success');
                    pendingCount = data.pending_count || 0;
                    updateSaveBtn();
                    refreshGridData();
                },
                error: function(xhr) { showToast(xhr.responseJSON ? xhr.responseJSON.error : 'Import failed', 'error'); }
            });
            $('#importType').val('');
        };
        reader.readAsText(file);
    });

    // Cell selection + inline editing via event delegation on grid div
    var lastClickedCell = null;
    $('#matchesGrid').on('click', '.ag-cell', function(e) {
        if ($(e.target).is('input, button, i, a, select')) return;
        var td = $(this);
        var colId = td.attr('col-id');

        if (e.shiftKey && lastClickedCell) {
            var rows = $('#matchesGrid .ag-row');
            var startRow = rows.index(lastClickedCell.row);
            var endRow = rows.index(td.closest('.ag-row'));
            var lo = Math.min(startRow, endRow);
            var hi = Math.max(startRow, endRow);
            $('.cell-selected').removeClass('cell-selected');

            if (lastClickedCell.colId === colId) {
                rows.slice(lo, hi + 1).each(function() {
                    $(this).find('.ag-cell[col-id="' + colId + '"]').addClass('cell-selected');
                });
                window.getSelection().removeAllRanges();
            } else {
                td.closest('.ag-row').find('.ag-cell').addClass('cell-selected');
                var sel = window.getSelection();
                sel.removeAllRanges();
                var range = document.createRange();
                range.selectNodeContents(td.closest('.ag-row')[0]);
                sel.addRange(range);
            }
        } else {
            $('.cell-selected').removeClass('cell-selected');
            td.addClass('cell-selected');
            lastClickedCell = { colId: colId, row: td.closest('.ag-row')[0] };
        }
    });

    // Click outside grid clears cell selection
    $(document).on('click', function(e) {
        if (!$(e.target).closest('#matchesGrid .ag-body-viewport').length) {
            $('.cell-selected').removeClass('cell-selected');
        }
    });

    // Ctrl+C copy, Ctrl+Z undo, Ctrl+Y redo
    $(document).on('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'c' && $('.cell-selected').length > 0) {
            var sel = window.getSelection();
            if (sel && sel.toString().length > 0) return;
            e.preventDefault();
            var vals = $('.cell-selected').map(function() { return $(this).text().trim(); }).get();
            navigator.clipboard.writeText(vals.join('\n'));
            showToast('Copied ' + vals.length + ' value(s)', 'success');
        }
        if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
            if ($(e.target).is('input, textarea, select')) return;
            e.preventDefault();
            performUndo();
        }
        if ((e.ctrlKey || e.metaKey) && e.key === 'y') {
            if ($(e.target).is('input, textarea, select')) return;
            e.preventDefault();
            performRedo();
        }
    });

    // JIB/Rev/Vendor checkbox toggle
    $('#matchesGrid').on('change', '.field-check', function() {
        var field = $(this).data('field');
        var value = $(this).prop('checked') ? 1 : 0;
        var selectedCells = $('.cell-selected');

        if (selectedCells.length > 1) {
            var rowIds = [];
            var undoChanges = [];
            var seen = new Set();
            selectedCells.each(function() {
                var row = $(this).closest('.ag-row');
                var cb = row.find('.field-check[data-field="' + field + '"]');
                if (cb.length) {
                    var rid = parseInt(cb.data('row-id'));
                    if (!seen.has(rid)) {
                        seen.add(rid);
                        rowIds.push(rid);
                        var oldVal = cb.prop('checked') ? 1 : 0;
                        undoChanges.push({ rowId: rid, field: field, oldValue: oldVal, newValue: value });
                        cb.prop('checked', !!value);
                    }
                }
            });
            if (undoChanges.length > 0) pushUndo({ type: 'bulk', changes: undoChanges });
            var completed = 0;
            rowIds.forEach(function(rid) {
                $.ajax({
                    url: '/api/update', method: 'POST', contentType: 'application/json',
                    data: JSON.stringify({ row_id: rid, field: field, value: value }),
                    success: function(data) {
                        pendingCount = data.pending_count || 0; updateSaveBtn();
                        if (++completed === rowIds.length) showToast('Set ' + field.toUpperCase() + ' on ' + rowIds.length + ' rows', 'success');
                    },
                    error: function() { showToast('Toggle failed', 'error'); }
                });
            });
        } else {
            var rowId = parseInt($(this).data('row-id'));
            var oldVal = value ? 0 : 1;
            pushUndo({ type: 'single', changes: [{ rowId: rowId, field: field, oldValue: oldVal, newValue: value }] });
            $.ajax({
                url: '/api/update', method: 'POST', contentType: 'application/json',
                data: JSON.stringify({ row_id: rowId, field: field, value: value }),
                success: function(data) { pendingCount = data.pending_count || 0; updateSaveBtn(); },
                error: function() { showToast('Toggle failed', 'error'); }
            });
        }
    });

    // Process inline dropdown
    function saveProcessValue(rowId, value) {
        $.ajax({
            url: '/api/update', method: 'POST', contentType: 'application/json',
            data: JSON.stringify({ row_id: rowId, field: 'how_to_process', value: value }),
            success: function(data) { pendingCount = data.pending_count || 0; updateSaveBtn(); },
            error: function() { showToast('Update failed', 'error'); }
        });
    }


    // Memo inline edit
    $('#matchesGrid').on('click', '.memo-text', function() {
        var $span = $(this);
        if ($span.data('editing')) return;
        $span.data('editing', true);
        var rowId = $span.data('row-id');
        var curVal = $span.text();
        var $input = $('<input type="text" class="form-control form-control-sm" style="font-size:0.75rem;padding:1px 4px;">').val(curVal);
        $span.replaceWith($input);
        $input.focus();
        var saved = false;
        function saveMemo() {
            if (saved) return;
            saved = true;
            var newVal = $input.val();
            if (newVal !== curVal) {
                pushUndo({ type: 'single', changes: [{ rowId: rowId, field: 'memo', oldValue: curVal, newValue: newVal }] });
            }
            $.ajax({
                url: '/api/update', method: 'POST', contentType: 'application/json',
                data: JSON.stringify({ row_id: rowId, field: 'memo', value: newVal }),
                error: function() { showToast('Memo save failed', 'error'); }
            });
            var rowNode = gridApi.getRowNode(String(rowId));
            if (rowNode) rowNode.setDataValue('memo', newVal);
        }
        $input.on('blur', saveMemo);
        $input.on('keydown', function(e) {
            if (e.key === 'Enter') { e.preventDefault(); saveMemo(); }
            if (e.key === 'Escape') {
                saved = true;
                var rowNode = gridApi.getRowNode(String(rowId));
                if (rowNode) gridApi.refreshCells({ rowNodes: [rowNode], columns: ['memo'], force: true });
            }
        });
    });

    // Right-click on Process column header → set all visible rows
    $('#matchesGrid').on('contextmenu', '.ag-header-cell', function(e) {
        var colId = $(this).attr('col-id');
        if (colId !== 'how_to_process') return;
        e.preventDefault();
        $('.process-ctx-menu').remove();
        var html = '<div class="process-ctx-menu" style="position:fixed;z-index:9999;background:#fff;border:1px solid #ccc;border-radius:4px;box-shadow:0 2px 8px rgba(0,0,0,.2);padding:4px 0;">';
        PROCESS_OPTS.forEach(function(o) {
            html += '<div class="process-ctx-item" style="padding:6px 16px;cursor:pointer;font-size:0.85rem;white-space:nowrap;" data-value="' + o + '">Update to: ' + o + '</div>';
        });
        html += '</div>';
        var $menu = $(html);
        $menu.css({ top: e.clientY + 'px', left: e.clientX + 'px' });
        $('body').append($menu);
        $menu.find('.process-ctx-item').hover(
            function() { $(this).css('background', '#e9ecef'); },
            function() { $(this).css('background', '#fff'); }
        );
        $menu.find('.process-ctx-item').on('click', function() {
            var chosen = $(this).data('value');
            $menu.remove();
            var count = 0;
            var undoChanges = [];
            window._bulkProcessUpdate = true;
            gridApi.forEachNodeAfterFilterAndSort(function(node) {
                var oldVal = node.data.how_to_process || '';
                if (oldVal !== chosen) {
                    undoChanges.push({ rowId: node.data._row_id, field: 'how_to_process', oldValue: oldVal, newValue: chosen });
                    node.setDataValue('how_to_process', chosen);
                    saveProcessValue(node.data._row_id, chosen);
                    count++;
                }
            });
            window._bulkProcessUpdate = false;
            if (undoChanges.length > 0) pushUndo({ type: 'bulk', changes: undoChanges });
            showToast('Updated ' + count + ' rows to "' + chosen + '"');
        });
        $(document).one('click', function() { $menu.remove(); });
    });

    // Build column visibility dropdown
    buildColVisDropdown();
});

// ── Undo / Redo ──
function pushUndo(action) {
    undoStack.push(action);
    if (undoStack.length > UNDO_MAX) undoStack.shift();
    redoStack.length = 0;
    updateUndoRedoBtns();
}

function applyChanges(changes, direction, callback) {
    var completed = 0;
    var hasRecChange = false;
    window._bulkProcessUpdate = true;
    changes.forEach(function(ch) {
        var val = direction === 'undo' ? ch.oldValue : ch.newValue;
        if (ch.field === 'recommendation') hasRecChange = true;
        $.ajax({
            url: '/api/update', method: 'POST', contentType: 'application/json',
            data: JSON.stringify({ row_id: ch.rowId, field: ch.field, value: val }),
            success: function(data) {
                pendingCount = data.pending_count || 0;
                var rowNode = gridApi.getRowNode(String(ch.rowId));
                if (rowNode) rowNode.setDataValue(ch.field, val);
                if (++completed === changes.length) {
                    window._bulkProcessUpdate = false;
                    updateSaveBtn();
                    if (hasRecChange) loadStats();
                    if (callback) callback();
                }
            },
            error: function() {
                if (++completed === changes.length) {
                    window._bulkProcessUpdate = false;
                    updateSaveBtn();
                    if (hasRecChange) loadStats();
                    if (callback) callback();
                }
            }
        });
    });
}

function performUndo() {
    if (undoStack.length === 0) return;
    var action = undoStack.pop();
    applyChanges(action.changes, 'undo', function() {
        redoStack.push(action);
        updateUndoRedoBtns();
        showToast('Undone (' + action.changes.length + ' change' + (action.changes.length > 1 ? 's' : '') + ')', 'info');
    });
}

function performRedo() {
    if (redoStack.length === 0) return;
    var action = redoStack.pop();
    applyChanges(action.changes, 'redo', function() {
        undoStack.push(action);
        updateUndoRedoBtns();
        showToast('Redone (' + action.changes.length + ' change' + (action.changes.length > 1 ? 's' : '') + ')', 'info');
    });
}

function updateUndoRedoBtns() {
    $('#undoBtn').prop('disabled', undoStack.length === 0);
    $('#redoBtn').prop('disabled', redoStack.length === 0);
}

// ── Stats cards ──
function loadStats() {
    $.get('/api/stats', function(s) {
        $('#totalRecords').text(s.total_records.toLocaleString());
        $('#ssnPerfect').text(s.ssn_perfect_matches.toLocaleString());
        $('#ssnNone').text(s.ssn_no_match.toLocaleString());

        var html = '';
        // "ALL" card to show all records
        html += '<div class="col">' +
            '<div class="card rec-card" style="border-left: 4px solid #212529; cursor:pointer;" onclick="clearFilters()">' +
            '<div class="card-body py-1 px-2" style="line-height:1.4;">' +
            '<div class="fw-bold text-truncate" style="font-size:0.82rem;" title="All Records">ALL - ' + s.total_records.toLocaleString() + '</div>' +
            '</div></div></div>';
        var recCfg = s.rec_config || {};
        var recs = sortByRecOrder(Object.entries(s.recommendations));
        recs.forEach(function(entry) {
            var rec = entry[0], count = entry[1];
            var color = REC_COLORS[rec] || '#6c757d';
            var pct = ((count / s.total_records) * 100).toFixed(1);
            var tip = rec;
            var cfg = recCfg[rec];
            if (cfg) {
                tip += '&#10;Name Score: ' + cfg.min_name + ' - ' + cfg.max_name;
                tip += '&#10;Addr Score: ' + cfg.min_addr + ' - ' + cfg.max_addr;
            }
            html += '<div class="col">' +
                '<div class="card rec-card" style="border-left: 4px solid ' + color + '; cursor:pointer;" onclick="filterByRec(\'' + rec + '\')" title="' + tip + '">' +
                '<div class="card-body py-1 px-2" style="line-height:1.4;">' +
                '<div class="fw-bold text-truncate" style="font-size:0.82rem;">' + rec + ' - ' + count.toLocaleString() + ' <span class="text-muted fw-normal">(' + pct + '%)</span></div>' +
                '</div></div></div>';
        });
        $('#recBreakdown').html(html);
    });
}

function filterByRec(rec) {
    activeRecFilter = rec;
    $('#ssnFilter').val('');
    onExternalFilterChanged();
}

function filterByStat(type) {
    if (type === 'all') { clearFilters(); }
    else if (type === 'ssn_yes') { $('#ssnFilter').val('yes'); onExternalFilterChanged(); }
    else if (type === 'ssn_partial') { $('#ssnFilter').val('partial'); onExternalFilterChanged(); }
    else if (type === 'ssn_no') { $('#ssnFilter').val('no'); onExternalFilterChanged(); }
}

function applyFilters() {
    onExternalFilterChanged();
}

function openDevNotes() {
    $.get('/api/dev_notes').fail(function(xhr) {
        showToast(xhr.responseJSON ? xhr.responseJSON.error : 'Could not open Dev Notes', 'error');
    });
}

function clearFilters() {
    activeRecFilter = '';
    $('#ssnFilter').val('');
    $('#minNameScore').val('');
    $('#maxNameScore').val('');
    $('#minAddrScore').val('');
    $('#maxAddrScore').val('');
    $('#quickFilterInput').val('');
    if (gridApi) gridApi.setGridOption('quickFilterText', '');
    onExternalFilterChanged();
}

function refreshData() {
    if (pendingCount > 0 && !confirm('You have unsaved changes. Refresh will discard them. Continue?')) return;
    showToast('Reloading from Snowflake...', 'info');
    $.post('/api/reload', function(data) {
        pendingCount = 0;
        updateSaveBtn();
        loadStats();
        refreshGridData();
        showToast(data.message, 'success');
    }).fail(function() {
        loadStats();
        refreshGridData();
        showToast('Refreshed (from cache)', 'warning');
    });
}

function updateSelectionInfo() {
    var n = selectedRows.size;
    $('#selectionInfo').text(n === 0 ? 'No records selected' : n + ' record(s) selected');
    $('#bulkApproveBtn').prop('disabled', n === 0);
}

// ── Edit modal ──
function editRecord(rowId) {
    $.get('/api/record/' + rowId, function(d) {
        $('#editRowId').val(d._row_id);
        $('#editCanvasName').val(d.canvas_name || '');
        $('#editCanvasAddress').val(d.canvas_address || '');
        $('#editCanvasCity').val(d.canvas_city || '');
        $('#editCanvasState').val(d.canvas_state || '');
        $('#editCanvasZip').val(d.canvas_zip || '');
        $('#editCanvasId').text(d.canvas_addrseq ? (d.canvas_id + '-' + d.canvas_addrseq) : (d.canvas_id || ''));
        $('#editCanvasSSN').text(d.canvas_ssn || '');
        $('#editDecName').text(d.dec_name || '');
        $('#editDecAddress').text(d.dec_address || '');
        $('#editDecCity').text(d.dec_city || '');
        $('#editDecState').text(d.dec_state || '');
        $('#editDecZip').text(d.dec_zip || '');
        $('#editDecContact').text(d.dec_contact || '');
        $('#editDecHdrcode').text(d.dec_hdrcode || '');
        setScoreBadgeEl('#editSsnMatch', d.ssn_match);
        setScoreBadgeEl('#editNameScore', d.name_score);
        setScoreBadgeEl('#editAddressScore', d.address_score);
        $('#editRecommendation').val(d.recommendation || '');
        $('#editAddressReason').val(d.address_reason || '');
        $('#editMemo').val(d.memo || '');
        editModal.show();
    });
}

function setScoreBadgeEl(sel, val) {
    var el = $(sel);
    el.text(val != null ? val : '-');
    el.removeClass('score-perfect score-high score-medium score-low');
    if (val === 100) el.addClass('score-perfect');
    else if (val >= 90) el.addClass('score-high');
    else if (val >= 75) el.addClass('score-medium');
    else el.addClass('score-low');
}

function saveRecord() {
    var rowId = parseInt($('#editRowId').val());
    var fields = {
        'canvas_name': $('#editCanvasName').val(),
        'canvas_address': $('#editCanvasAddress').val(),
        'canvas_city': $('#editCanvasCity').val(),
        'canvas_state': $('#editCanvasState').val(),
        'canvas_zip': $('#editCanvasZip').val(),
        'recommendation': $('#editRecommendation').val(),
        'address_reason': $('#editAddressReason').val(),
        'memo': $('#editMemo').val()
    };

    var pending = Object.keys(fields).length;
    var errors = [];

    Object.entries(fields).forEach(function(entry) {
        var field = entry[0], value = entry[1];
        $.ajax({
            url: '/api/update', method: 'POST', contentType: 'application/json',
            data: JSON.stringify({ row_id: rowId, field: field, value: value }),
            success: function(data) {
                pendingCount = data.pending_count || 0;
                if (--pending === 0) onSaveDone(errors);
            },
            error: function() { errors.push(field); if (--pending === 0) onSaveDone(errors); }
        });
    });
}

function onSaveDone(errors) {
    if (errors.length === 0) {
        showToast('Changes saved to memory (click Save to persist)', 'success');
        editModal.hide();
        updateSaveBtn();
        refreshGridData();
        loadStats();
    } else {
        showToast('Errors saving: ' + errors.join(', '), 'error');
    }
}

function showConfirm(title, message, onConfirm) {
    $('#confirmModalTitle').text(title);
    $('#confirmModalBody').html(message);
    var modal = new bootstrap.Modal(document.getElementById('confirmModal'));
    $('#confirmModalOk').off('click').on('click', function() { modal.hide(); onConfirm(); });
    modal.show();
}

function quickApprove(rowId) {
    showConfirm('Approve Record', '<i class="fas fa-check-circle text-success fa-2x mb-2"></i><br>Approve this record?', function() {
        var rowNode = gridApi.getRowNode(String(rowId));
        var oldVal = rowNode ? (rowNode.data.recommendation || '') : '';
        pushUndo({ type: 'single', changes: [{ rowId: rowId, field: 'recommendation', oldValue: oldVal, newValue: 'APPROVED' }] });
        $.ajax({
            url: '/api/update', method: 'POST', contentType: 'application/json',
            data: JSON.stringify({ row_id: rowId, field: 'recommendation', value: 'APPROVED' }),
            success: function(data) {
                showToast('Approved (unsaved)', 'success');
                pendingCount = data.pending_count || 0;
                updateSaveBtn();
                if (rowNode) rowNode.setDataValue('recommendation', 'APPROVED');
                loadStats();
            },
            error: function() { showToast('Failed', 'error'); }
        });
    });
}

function bulkApprove() {
    var n = selectedRows.size;
    if (n === 0) return;
    showConfirm('Approve Selected', '<i class="fas fa-check-circle text-success fa-2x mb-2"></i><br>Approve <strong>' + n + '</strong> selected record' + (n > 1 ? 's' : '') + '?', function() {
        var undoChanges = [];
        selectedRows.forEach(function(rid) {
            var node = gridApi.getRowNode(String(rid));
            var oldVal = node ? (node.data.recommendation || '') : '';
            undoChanges.push({ rowId: rid, field: 'recommendation', oldValue: oldVal, newValue: 'APPROVED' });
        });
        if (undoChanges.length > 0) pushUndo({ type: 'bulk', changes: undoChanges });
        $.ajax({
            url: '/api/bulk_update', method: 'POST', contentType: 'application/json',
            data: JSON.stringify({ row_ids: Array.from(selectedRows), recommendation: 'APPROVED' }),
            success: function(data) {
                showToast('Approved ' + data.updated + ' records (unsaved)', 'success');
                pendingCount = data.pending_count || 0;
                updateSaveBtn();
                gridApi.deselectAll();
                selectedRows.clear();
                updateSelectionInfo();
                refreshGridData();
                loadStats();
            },
            error: function() { showToast('Bulk approve failed', 'error'); }
        });
    });
}

// ── Export (client-side CSV via AG Grid) ──
function exportSelected() {
    if (selectedRows.size === 0) {
        showToast('No records selected', 'warning');
        return;
    }
    var rowNodes = [];
    selectedRows.forEach(function(rid) {
        var node = gridApi.getRowNode(String(rid));
        if (node) rowNodes.push(node);
    });
    gridApi.exportDataAsCsv({
        onlySelected: false,
        shouldRowBeSkipped: function(params) {
            return !selectedRows.has(params.node.data._row_id);
        },
        fileName: 'selected_export_' + new Date().toISOString().slice(0, 10) + '.csv'
    });
}

function exportData() {
    gridApi.exportDataAsCsv({
        fileName: 'matches_export_' + new Date().toISOString().slice(0, 10) + '.csv'
    });
}

// ── Save pending changes ──
function saveChanges() {
    if (pendingCount === 0) { showToast('Nothing to save', 'info'); return; }
    var btn = $('#saveChangesBtn');
    btn.prop('disabled', true);
    $.ajax({
        url: '/api/save_changes', method: 'POST', contentType: 'application/json',
        data: JSON.stringify({}),
        success: function(data) {
            pendingCount = data.pending_count || 0;
            updateSaveBtn();
            refreshGridData();
            loadStats();
            showToast(data.message, 'success');
        },
        error: function(xhr) {
            showToast(xhr.responseJSON ? xhr.responseJSON.error : 'Save failed', 'error');
            updateSaveBtn();
        }
    });
}

function updateSaveBtn() {
    var btn = $('#saveChangesBtn');
    btn.prop('disabled', pendingCount === 0);
    btn.find('.save-count').text(pendingCount > 0 ? ' (' + pendingCount + ')' : '');
}

// ── Toast ──
function showToast(msg, type) {
    var colors = { success: '#28a745', error: '#dc3545', warning: '#ffc107', info: '#17a2b8' };
    var bg = colors[type] || colors.info;
    var toast = $('<div class="toast-msg" style="background:' + bg + '">' + msg + '</div>');
    $('body').append(toast);
    setTimeout(function() { toast.fadeOut(300, function() { $(this).remove(); }); }, 2500);
}

// ── Search & Replace ──
var srModal;
var srMatches = [];   // [{rowId, rowNode, col, value}, ...]
var srMatchIdx = -1;  // current match index

var SR_TEXT_COLS = [
    'canvas_name', 'canvas_address', 'canvas_city', 'canvas_state', 'canvas_zip',
    'recommendation', 'how_to_process', 'memo', 'address_reason'
];

var srHighlightInterval = null;

function srClearHighlight() {
    $('.sr-highlight').removeClass('sr-highlight');
    if (srHighlightInterval) { clearInterval(srHighlightInterval); srHighlightInterval = null; }
}

function srKeepHighlight() {
    // Re-apply highlight periodically (AG Grid virtualisation can remove classes on scroll)
    srClearHighlight();
    if (srMatchIdx < 0 || srMatchIdx >= srMatches.length) return;
    var m = srMatches[srMatchIdx];
    var search = $('#srSearch').val();
    var caseSensitive = $('#srCaseSensitive').is(':checked');
    function apply() {
        var rowEl = document.querySelector('.ag-row[row-id="' + m.nodeId + '"]');
        if (!rowEl) return;
        var cell = rowEl.querySelector('.ag-cell[col-id="' + m.col + '"]');
        if (!cell) return;
        cell.classList.add('sr-highlight');
        // Highlight the matched text within the cell
        if (search && cell.querySelector('.sr-match-text') === null) {
            var flags = caseSensitive ? 'g' : 'gi';
            var re = new RegExp('(' + search.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', flags);
            var inner = cell.innerHTML;
            if (!inner.includes('sr-match-text')) {
                cell.innerHTML = inner.replace(re, '<span class="sr-match-text">$1</span>');
            }
        }
    }
    apply();
    srHighlightInterval = setInterval(apply, 200);
}

function openSearchReplace() {
    if (!srModal) {
        srModal = new bootstrap.Modal(document.getElementById('searchReplaceModal'));
        var srFindTimer;
        $('#srSearch, #srColumn, #srCaseSensitive').on('input change', function() {
            clearTimeout(srFindTimer);
            srMatches = []; srMatchIdx = -1;
            srClearHighlight();
            srFindTimer = setTimeout(srAutoFind, 300);
        });
        // Clear highlight when modal closes
        document.getElementById('searchReplaceModal').addEventListener('hidden.bs.modal', function() {
            srClearHighlight();
        });
    }
    $('#srMatchInfo').text('');
    srMatches = []; srMatchIdx = -1;
    srClearHighlight();
    srModal.show();
    setTimeout(srAutoFind, 100);
}

function getVisibleRowIds() {
    var ids = [];
    if (gridApi) {
        gridApi.forEachNodeAfterFilterAndSort(function(node) {
            if (node.data && node.data._row_id !== undefined) ids.push(node.data._row_id);
        });
    }
    return ids;
}

function srBuildMatches() {
    srMatches = [];
    srMatchIdx = -1;
    var search = $('#srSearch').val();
    if (!search || !gridApi) return;
    var col = $('#srColumn').val();
    var caseSensitive = $('#srCaseSensitive').is(':checked');
    var cols = (col === 'all') ? SR_TEXT_COLS : [col];
    var searchVal = caseSensitive ? search : search.toLowerCase();

    gridApi.forEachNodeAfterFilterAndSort(function(node) {
        if (!node.data) return;
        cols.forEach(function(c) {
            var val = String(node.data[c] || '');
            var cmp = caseSensitive ? val : val.toLowerCase();
            if (cmp.indexOf(searchVal) !== -1) {
                srMatches.push({ rowId: node.data._row_id, nodeId: node.id, col: c });
            }
        });
    });
}

function srHighlightMatch() {
    srClearHighlight();
    if (srMatchIdx < 0 || srMatchIdx >= srMatches.length) return;
    var m = srMatches[srMatchIdx];
    var node = gridApi.getRowNode(m.nodeId);
    if (!node) return;
    // Ensure the column is visible
    var colDef = gridApi.getColumnDef(m.col);
    if (colDef && colDef.hide) {
        gridApi.setColumnVisible(m.col, true);
    }
    gridApi.ensureNodeVisible(node, 'middle');
    // Start persistent highlight (survives AG Grid scroll re-renders)
    setTimeout(function() { srKeepHighlight(); }, 100);
}

function srUpdateInfo() {
    if (srMatches.length === 0) {
        $('#srMatchInfo').text('No matches found in filtered rows.');
    } else {
        $('#srMatchInfo').text('Match ' + (srMatchIdx + 1) + ' of ' + srMatches.length);
    }
}

function srAutoFind() {
    var search = $('#srSearch').val();
    if (!search) { $('#srMatchInfo').text(''); srMatches = []; srMatchIdx = -1; return; }
    srBuildMatches();
    if (srMatches.length > 0) {
        srMatchIdx = 0;
        srHighlightMatch();
    }
    srUpdateInfo();
}

function srFindNext() {
    var search = $('#srSearch').val();
    if (!search) { $('#srMatchInfo').text('Enter search text.'); return; }
    if (srMatches.length === 0) { srBuildMatches(); }
    if (srMatches.length === 0) { srUpdateInfo(); return; }
    srMatchIdx = (srMatchIdx + 1) % srMatches.length;
    srHighlightMatch();
    srUpdateInfo();
}

function srReplaceCurrent() {
    var search = $('#srSearch').val();
    var replace = $('#srReplace').val();
    if (!search) { $('#srMatchInfo').text('Enter search text.'); return; }
    if (srMatches.length === 0 || srMatchIdx < 0) { srFindNext(); return; }

    var m = srMatches[srMatchIdx];
    $.ajax({
        url: '/api/search_replace', method: 'POST', contentType: 'application/json',
        data: JSON.stringify({
            search: search, replace: replace,
            column: m.col,
            case_sensitive: $('#srCaseSensitive').is(':checked'),
            mode: 'replace',
            row_ids: [m.rowId]
        }),
        success: function(data) {
            if (data.replaced > 0) {
                pendingCount = data.pending_count || 0;
                updateSaveBtn();
                // Refresh just this row from server
                refreshGridData();
                loadStats();
                // Rebuild matches and advance
                setTimeout(function() {
                    srBuildMatches();
                    if (srMatches.length === 0) {
                        srMatchIdx = -1;
                        srUpdateInfo();
                    } else {
                        if (srMatchIdx >= srMatches.length) srMatchIdx = 0;
                        srHighlightMatch();
                        srUpdateInfo();
                    }
                }, 300);
            } else {
                $('#srMatchInfo').text('No replacement made.');
            }
        },
        error: function(xhr) {
            showToast('Replace failed: ' + (xhr.responseJSON ? xhr.responseJSON.error : 'Unknown error'), 'error');
        }
    });
}

function doReplaceAll() {
    var search = $('#srSearch').val();
    var replace = $('#srReplace').val();
    if (!search) { $('#srMatchInfo').text('Enter search text.'); return; }
    $.ajax({
        url: '/api/search_replace', method: 'POST', contentType: 'application/json',
        data: JSON.stringify({
            search: search, replace: replace,
            column: $('#srColumn').val(),
            case_sensitive: $('#srCaseSensitive').is(':checked'),
            mode: 'replace',
            row_ids: getVisibleRowIds()
        }),
        success: function(data) {
            if (data.replaced === 0) {
                $('#srMatchInfo').text('No matches to replace.');
            } else {
                showToast('Replaced ' + data.replaced + ' occurrence' + (data.replaced !== 1 ? 's' : '') + ' in ' + data.rows + ' row' + (data.rows !== 1 ? 's' : '') + ' (unsaved)', 'success');
                pendingCount = data.pending_count || 0;
                updateSaveBtn();
                refreshGridData();
                loadStats();
                srMatches = []; srMatchIdx = -1;
                srClearHighlight();
                srModal.hide();
            }
        },
        error: function(xhr) {
            showToast('Replace failed: ' + (xhr.responseJSON ? xhr.responseJSON.error : 'Unknown error'), 'error');
        }
    });
}
