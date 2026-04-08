let gridApi;
let selectedRows = new Set();
let editModal;
let recommendationValues = [];
let activeRecFilter = '';
let recConfig = {};
let selectedRowDataMap = new Map(); // rowId -> row data, for bulk operations
let lastRecordsTotal = 0;
let lastRecordsFiltered = 0;
let _removedRowIds = new Set();  // rows hidden client-side (approved/moved) until next datasource reset
let currentFilters = {
    recommendation: '',
    ssn_match: '',
    min_name_score: '',
    max_name_score: '',
    min_addr_score: '',
    max_addr_score: '',
    search: '',
};

// Undo/Redo stacks
var undoStack = [];
var redoStack = [];
var UNDO_MAX = 50;

// Pattern to detect "do not use" variations
const DO_NOT_USE_RE = /do\s*n[o']?t\s*use|don['\u2019]t\s*use|d\.?n\.?u\.?(?!\w)/i;
const BAD_ADDR_RE = /bad\s*addr(?:ess)?/i;

// Grid settings persistence
var _colStateSaveTimer = null;
var _suppressFilterSave = false;

// Preferred display order for recommendations
const REC_ORDER = [
    'NEW BA AND NEW ADDRESS',
    'EXISTING BA ADD NEW ADDRESS',
    'EXISTING BA AND EXISTING ADDRESS',
    'NEEDS REVIEW',
    'PROCESSED',
    'STAGED'
];

// Color map for recommendation badges
const REC_COLORS = {
    'NEW BA AND NEW ADDRESS': '#6c757d',
    'EXISTING BA ADD NEW ADDRESS': '#fd7e14',
    'EXISTING BA AND EXISTING ADDRESS': '#28a745',
    'NEEDS REVIEW': '#ffc107',
    'PROCESSED': '#0d6efd',
    'STAGED': '#6610f2'
};

const PROCESS_OPTS = ['Add new BA and address', 'Add address to existing BA', 'Merge BA and address', 'Manual Review - DNP'];

function isStaged(params) {
    return params.data && (params.data.recommendation || '').toUpperCase() === 'STAGED';
}
function notStagedEditable(params) {
    return !isStaged(params);
}

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
        var checked = getSelectedRecs();
        currentFilters.recommendation = checked.join(',');
        activeRecFilter = checked.length === 1 ? checked[0] : '';
        applyServerFilters();
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
    var checked = getSelectedRecs();
    currentFilters.recommendation = checked.join(',');
    activeRecFilter = checked.length === 1 ? checked[0] : '';
    applyServerFilters();
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
    ['Src Name', '#1e3a8a', 'source_name'],
    ['Src Addr', '#1e3a8a', 'source_address'],
    ['Src City/St/Zip', '#1e3a8a', 'source_csz'],
    ['Src Addr Recomend', '#1e3a8a', 'source_address_recomend'],
    ['Src SSN', '#1e3a8a', 'source_ssn'],
    ['Src ID', '#1e3a8a', 'source_id', false],
    ['DEC SSN', '#9b4d6e', 'dec_ssn'],
    ['DEC Name', '#9b4d6e', 'dec_name'],
    ['DEC Addr', '#9b4d6e', 'dec_address'],
    ['DEC City/St/Zip', '#9b4d6e', 'dec_csz'],
    ['DEC Code', '#9b4d6e', 'dec_hdrcode', false],
    ['Address Lookup', '#9b4d6e', 'dec_address_looked_up', false],
    ['JIB', '#212529', 'jib', false],
    ['Rev', '#212529', 'rev', false],
    ['Vendor', '#212529', 'vendor', false],
    ['Memo', '#212529', 'memo', false],
    ['Run ID', '#212529', 'run_id', false],
    ['Name Normal', '#2e7d32', 'name_normal_detail', false],
    ['Addr Normal', '#2e7d32', 'address_normal_detail', false],
    ['Name Match', '#2e7d32', 'name_match_detail', false],
    ['Addr Match', '#2e7d32', 'addr_match_detail', false]
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

function syncColVisDropdown() {
    // Sync checkboxes to the grid's actual runtime visibility state.
    // Called after applyColumnState() restores saved state so the
    // Show/Hide panel matches what is actually on screen.
    if (!gridApi) return;
    $('.col-vis-check').each(function() {
        var col = gridApi.getColumn($(this).data('col-name'));
        if (col) $(this).prop('checked', col.visible);
    });
}

// ── External filter state (legacy stub — now handled server-side) ──
function onExternalFilterChanged() {
    // Kept as a stub so legacy callers don't crash.
    // Actual filtering is now done server-side via applyServerFilters().
    applyServerFilters();
    if (!_suppressFilterSave) saveFilterState();
}

function updateGridInfo() {
    var filtered = lastRecordsFiltered || 0;
    var total = lastRecordsTotal || 0;
    if (filtered === total) {
        $('#gridInfo').text(total.toLocaleString() + ' records');
    } else {
        $('#gridInfo').text(filtered.toLocaleString() + ' of ' + total.toLocaleString() + ' records');
    }
}

// ── Cell renderers ──
function ssnCellRenderer(params) {
    if (!params.data) return '';
    if (params.value === 100) return '<span class="badge bg-success" style="font-size:0.6rem;line-height:16px;padding:0 4px;">Yes</span>';
    return '<span class="badge bg-danger" style="font-size:0.6rem;line-height:16px;padding:0 4px;">No</span>';
}

function scoreCellRenderer(params) {
    if (!params.data) return '';
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

function processDefaultForRec(rec) {
    var r = (rec || '').toUpperCase();
    if (r === 'NEW BA AND NEW ADDRESS') return 'Add new BA and address';
    if (r === 'EXISTING BA ADD NEW ADDRESS') return 'Add address to existing BA';
    if (r === 'EXISTING BA AND EXISTING ADDRESS') return 'Merge BA and address';
    return '';
}

function prefillProcessField(rows) {
    // Pre-populate how_to_process from recommendation so AG Grid change
    // detection works correctly (no valueGetter masking the real value).
    rows.forEach(function(row) {
        if (!row.how_to_process) {
            row.how_to_process = processDefaultForRec(row.recommendation);
        }
    });
    return rows;
}

function processCellRenderer(params) {
    if (!params.data) return '';
    var val = params.value || '';
    var disabled = isStaged(params) ? ' disabled' : '';
    var html = '<select class="process-select" data-row-id="' + params.data._row_id + '" style="width:100%;border:none;background:transparent;font-size:0.75rem;cursor:pointer;padding:0 2px;"' + disabled + '>';
    html += '<option value=""' + (val === '' ? ' selected' : '') + '></option>';
    for (var i = 0; i < PROCESS_OPTS.length; i++) {
        var opt = PROCESS_OPTS[i];
        html += '<option value="' + opt + '"' + (val === opt ? ' selected' : '') + '>' + opt + '</option>';
    }
    html += '</select>';
    return html;
}

function checkboxCellRenderer(params) {
    if (!params.data) return '';
    var checked = params.value ? 'checked' : '';
    var disabled = isStaged(params) ? ' disabled' : '';
    return '<input type="checkbox" class="field-check" data-row-id="' + params.data._row_id + '" data-field="' + params.colDef.field + '" ' + checked + disabled + '>';
}

function addressLookupCellRenderer(params) {
    if (!params.data) return '';
    var checked = (params.value === 1 || params.value === '1') ? 'checked' : '';
    return '<input type="checkbox" ' + checked + ' disabled>';
}

function memoCellRenderer(params) {
    if (!params.data) return '';
    var val = params.value || '';
    var escaped = val.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    if (isStaged(params)) {
        return '<span style="font-size:0.75rem;">' + escaped + '</span>';
    }
    return '<span class="memo-text" data-row-id="' + params.data._row_id + '" style="font-size:0.75rem;cursor:pointer;" title="Click to edit">' + escaped + '</span>';
}


function sourceIdValueGetter(params) {
    var d = params.data;
    if (!d) return '';
    var seq = d.source_addrseq || '';
    return seq ? (d.source_id || '') + '-' + seq : (d.source_id || '');
}

function sourceCszValueGetter(params) {
    var d = params.data;
    if (!d) return '';
    return (d.source_city || '') + ', ' + (d.source_state || '') + ' ' + (d.source_zip || '');
}

function decCszValueGetter(params) {
    var d = params.data;
    if (!d) return '';
    return (d.dec_city || '') + ', ' + (d.dec_state || '') + ' ' + (d.dec_zip || '');
}

function decCodeValueGetter(params) {
    var d = params.data;
    if (!d) return '';
    var code = d.dec_hdrcode || '';
    var sub = d.dec_addrsubcode || '';
    return sub ? code + '-' + sub : code;
}

// ── Grid settings persistence helpers ──
function saveGridSetting(key, value) {
    $.ajax({
        url: '/api/grid_settings', method: 'POST', contentType: 'application/json',
        data: JSON.stringify({ key: key, value: value }),
        error: function(xhr) { console.warn('Grid setting save failed:', key, xhr.responseText); }
    });
}

function saveColumnState() {
    if (!gridApi) return;
    saveGridSetting('column_state', gridApi.getColumnState());
}

function saveFilterState() {
    saveGridSetting('filter_state', {
        activeRecFilter: activeRecFilter,
        ssnFilter:    $('#ssnFilter').val(),
        minNameScore: $('#minNameScore').val(),
        maxNameScore: $('#maxNameScore').val(),
        minAddrScore: $('#minAddrScore').val(),
        maxAddrScore: $('#maxAddrScore').val()
    });
}

function applyColumnState(state) {
    if (!gridApi || !state || !Array.isArray(state)) return;
    try { gridApi.applyColumnState({ state: state, applyOrder: true }); }
    catch (e) { console.warn('applyColumnState failed:', e); }
}

function applyFilterState(state) {
    if (!state) return;
    try {
        _suppressFilterSave = true;
        $('#ssnFilter').val(state.ssnFilter || '');
        $('#minNameScore').val(state.minNameScore || '');
        $('#maxNameScore').val(state.maxNameScore || '');
        $('#minAddrScore').val(state.minAddrScore || '');
        $('#maxAddrScore').val(state.maxAddrScore || '');
        activeRecFilter = state.activeRecFilter || '';
        // Sync currentFilters with restored state
        currentFilters.recommendation = activeRecFilter;
        currentFilters.ssn_match = state.ssnFilter || '';
        currentFilters.min_name_score = state.minNameScore || '';
        currentFilters.max_name_score = state.maxNameScore || '';
        currentFilters.min_addr_score = state.minAddrScore || '';
        currentFilters.max_addr_score = state.maxAddrScore || '';
        applyServerFilters();
    } catch (e) {
        console.warn('applyFilterState failed:', e);
    } finally {
        _suppressFilterSave = false;
    }
}

function loadAndApplyGridSettings(onFilterStateDone) {
    $.get('/api/grid_settings')
        .done(function(data) {
            applyColumnState(data.column_state);
            onFilterStateDone(data.filter_state);
        })
        .fail(function() {
            console.warn('Could not load grid settings');
            onFilterStateDone(null);
        });
}

// ── AG Grid init ──
function initGrid(savedColState, savedFilterState) {
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
        { headerName: 'Process', field: 'how_to_process', colId: 'how_to_process', width: 190,
          cellRenderer: processCellRenderer,
          cellStyle: { padding: '0 4px' }
        },
        { headerName: 'Src Name', field: 'source_name', colId: 'source_name', minWidth: 140, flex: 1,
          headerClass: 'ag-header-source', wrapText: false, editable: notStagedEditable,
          cellClassRules: { 'do-not-use-cell': function(p) { return p.value && DO_NOT_USE_RE.test(p.value); }, 'bad-addr-cell': function(p) { return p.value && BAD_ADDR_RE.test(p.value); } }
        },
        { headerName: 'Src Addr', field: 'source_address', colId: 'source_address', minWidth: 200, flex: 2,
          headerClass: 'ag-header-source',
          wrapText: true,
          cellStyle: { 'white-space': 'pre-wrap', 'line-height': '1.3' },
          cellRenderer: function(params) {
              var val = params.value || '';
              if (val.indexOf('\n') === -1 && val.length <= 45) return document.createTextNode(val);
              var container = document.createElement('span');
              var lines = val.split('\n');
              for (var i = 0; i < lines.length; i++) {
                  if (i > 0) container.appendChild(document.createElement('br'));
                  var line = lines[i];
                  if (line.length <= 45) {
                      container.appendChild(document.createTextNode(line));
                  } else {
                      container.appendChild(document.createTextNode(line.substring(0, 45)));
                      var over = document.createElement('span');
                      over.style.color = 'red';
                      over.textContent = line.substring(45);
                      container.appendChild(over);
                  }
              }
              return container;
          },
          cellClassRules: { 'do-not-use-cell': function(p) { return p.value && DO_NOT_USE_RE.test(p.value); }, 'bad-addr-cell': function(p) { return p.value && BAD_ADDR_RE.test(p.value); } }
        },
        { headerName: 'Src City', field: 'source_city', colId: 'source_city', width: 100,
          headerClass: 'ag-header-source', editable: notStagedEditable },
        { headerName: 'Src St', field: 'source_state', colId: 'source_state', width: 50,
          headerClass: 'ag-header-source', editable: notStagedEditable },
        { headerName: 'Src Zip', field: 'source_zip', colId: 'source_zip', width: 70,
          headerClass: 'ag-header-source', editable: notStagedEditable },
        { headerName: 'Src Addr Recomend', field: 'source_address_recomend', colId: 'source_address_recomend', minWidth: 200, flex: 2,
          headerClass: 'ag-header-source', editable: notStagedEditable,
          wrapText: true,
          cellStyle: { 'white-space': 'pre-wrap', 'line-height': '1.3' },
          cellEditor: 'agLargeTextCellEditor',
          cellEditorParams: { maxLength: 500, rows: 5, cols: 50 },
          cellEditorPopup: true,
          headerTooltip: 'Shift+Enter(Return) to add new line.  Enter to confirm, Esc to cancel.',
          cellRenderer: function(params) {
              var val = params.value || '';
              if (val.indexOf('\n') === -1 && val.length <= 45) return document.createTextNode(val);
              var container = document.createElement('span');
              var lines = val.split('\n');
              for (var i = 0; i < lines.length; i++) {
                  if (i > 0) container.appendChild(document.createElement('br'));
                  var line = lines[i];
                  if (line.length <= 45) {
                      container.appendChild(document.createTextNode(line));
                  } else {
                      container.appendChild(document.createTextNode(line.substring(0, 45)));
                      var over = document.createElement('span');
                      over.style.color = 'red';
                      over.textContent = line.substring(45);
                      container.appendChild(over);
                  }
              }
              return container;
          },
          cellClassRules: { 'do-not-use-cell': function(p) { return p.value && DO_NOT_USE_RE.test(p.value); }, 'bad-addr-cell': function(p) { return p.value && BAD_ADDR_RE.test(p.value); } }
        },
        { headerName: 'Src SSN', field: 'source_ssn', colId: 'source_ssn', width: 100,
          headerClass: 'ag-header-source' },
        { headerName: 'Src ID', field: 'source_id', colId: 'source_id', valueGetter: sourceIdValueGetter, width: 100,
          headerClass: 'ag-header-source', hide: true },
        { headerName: 'DEC SSN', field: 'dec_ssn', colId: 'dec_ssn', width: 100,
          headerClass: 'ag-header-dec' },
        { headerName: 'DEC Name', field: 'dec_name', colId: 'dec_name', minWidth: 140, flex: 1,
          headerClass: 'ag-header-dec', wrapText: false,
          cellClassRules: { 'do-not-use-cell': function(p) { return p.value && DO_NOT_USE_RE.test(p.value); }, 'bad-addr-cell': function(p) { return p.value && BAD_ADDR_RE.test(p.value); } }
        },
        { headerName: 'DEC Addr', field: 'dec_address', colId: 'dec_address', minWidth: 140, flex: 1,
          headerClass: 'ag-header-dec', wrapText: false,
          cellClassRules: { 'do-not-use-cell': function(p) { return p.value && DO_NOT_USE_RE.test(p.value); }, 'bad-addr-cell': function(p) { return p.value && BAD_ADDR_RE.test(p.value); } }
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
        { headerName: 'Run ID', field: 'run_id', colId: 'run_id', width: 120, hide: true },
        { headerName: 'Name Normal', field: 'name_normal_detail', colId: 'name_normal_detail', width: 200, hide: true },
        { headerName: 'Addr Normal', field: 'address_normal_detail', colId: 'address_normal_detail', width: 200, hide: true },
        { headerName: 'Name Match', field: 'name_match_detail', colId: 'name_match_detail', width: 200, hide: true },
        { headerName: 'Addr Match', field: 'addr_match_detail', colId: 'addr_match_detail', width: 200, hide: true }
    ];

    var gridOptions = {
        columnDefs: columnDefs,
        rowModelType: 'infinite',
        cacheBlockSize: 100,
        maxBlocksInCache: 1000,
        infiniteInitialRowCount: 1,
        getRowId: function(params) { return params.data ? String(params.data._row_id) : null; },
        stopEditingWhenCellsLoseFocus: true,
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
        rowClassRules: {
            'trust-highlight': function(params) {
                if (!params.data) return false;
                var v = params.data.is_trust;
                return v === 1 || v === true || v === '1' || v === 'true' || v === 'True';
            }
        },
        singleClickEdit: true,
        onCellValueChanged: function(params) {
            if (window._bulkProcessUpdate) return;
            var INLINE_TEXT_FIELDS = ['source_name', 'source_address_recomend', 'source_city', 'source_state', 'source_zip'];
            if (INLINE_TEXT_FIELDS.indexOf(params.colDef.field) !== -1) {
                if (params.oldValue !== params.newValue) {
                    var fld = params.colDef.field;
                    pushUndo({ type: 'single', changes: [{ rowId: params.data._row_id, field: fld, oldValue: params.oldValue || '', newValue: params.newValue || '' }] });
                    $.ajax({
                        url: '/api/update', method: 'POST', contentType: 'application/json',
                        data: JSON.stringify({
                            row_id: params.data._row_id,
                            id: params.data.id,
                            source_id: params.data.source_id,
                            source_ssn: params.data.source_ssn,
                            field: fld,
                            value: params.newValue || '',
                            old_value: params.oldValue || '',
                        }),
                        success: function(data) { showToast('Saved', 'success'); refreshBucketCounts(); },
                        error: function(xhr) { showToast('Save failed: ' + ((xhr.responseJSON || {}).error || 'Unknown'), 'danger'); }
                    });
                }
            }
        },
        onGridReady: function(params) {
            applyColumnState(savedColState);
            syncColVisDropdown();
            loadGridData(savedFilterState);
        },
        onColumnResized: function(params) {
            if (!params.finished) return;
            clearTimeout(_colStateSaveTimer);
            _colStateSaveTimer = setTimeout(saveColumnState, 800);
        },
        onColumnVisible: function() {
            syncColVisDropdown();
            clearTimeout(_colStateSaveTimer);
            _colStateSaveTimer = setTimeout(saveColumnState, 800);
        },
        onColumnMoved: function(params) {
            if (params.finished === false) return;
            clearTimeout(_colStateSaveTimer);
            _colStateSaveTimer = setTimeout(saveColumnState, 800);
        },
        onSortChanged: function() {
            clearTimeout(_colStateSaveTimer);
            _colStateSaveTimer = setTimeout(saveColumnState, 800);
        },
        onPaginationChanged: function() {
            updateGridInfo();
        },
        onSelectionChanged: function() {
            selectedRows.clear();
            selectedRowDataMap.clear();
            gridApi.getSelectedNodes().forEach(function(node) {
                if (node.data) {
                    selectedRows.add(node.data._row_id);
                    selectedRowDataMap.set(node.data._row_id, node.data);
                }
            });
            updateSelectionInfo();
        },
        getRowClass: undefined
    };

    var gridDiv = document.getElementById('matchesGrid');
    gridApi = agGrid.createGrid(gridDiv, gridOptions);
}

function loadGridData(savedFilterState) {
    if (savedFilterState) {
        applyFilterState(savedFilterState);
    }
    // Defer datasource set to avoid triggering a re-render while onGridReady
    // is still on the call stack (causes "cannot draw rows while drawing rows").
    setTimeout(function() {
        if (typeof gridApi !== 'undefined' && gridApi) {
            gridApi.setGridOption('datasource', buildDatasource());
        }
    }, 0);
}

function refreshGridData(onDone) {
    if (typeof gridApi !== 'undefined' && gridApi) {
        gridApi.purgeInfiniteCache();
    }
    if (typeof onDone === 'function') setTimeout(onDone, 300);
}

// ── Bucket count / cache status helpers ──
function refreshBucketCounts() {
    $.get('/api/bucket-counts', function(counts) {
        var total = 0;
        Object.values(counts).forEach(function(c) { total += c; });
        $('.bucket-count').each(function() {
            var bucket = $(this).data('bucket');
            var count = counts[bucket];
            if (count !== undefined) {
                $(this).text(count.toLocaleString());
                var pctSpan = $(this).siblings('.text-muted');
                if (pctSpan.length && total > 0) {
                    pctSpan.text('(' + ((count / total) * 100).toFixed(1) + '%)');
                }
            }
        });
        if (total > 0) $('#allRecordsCount').text(total.toLocaleString());
    }).fail(function() {
        $('.bucket-count').text('?');
    });
}

function refreshCacheStatus() {
    $.get('/api/cache-status', function(status) {
        var badge = $('#cacheModeBadge');
        if (status.mode === 'cached') {
            badge.text('Cached').attr('title', 'Data is served from an in-memory cache for faster filtering and scrolling').removeClass('bg-secondary').addClass('bg-info text-dark').show();
        } else {
            badge.text('Live query').attr('title', 'Each request queries the database directly — used for multi-bucket views or search').removeClass('bg-info text-dark').addClass('bg-secondary').show();
        }
    }).fail(function() {
        $('#cacheModeBadge').text('Unknown').attr('title', 'Unable to determine data source mode').removeClass('bg-info text-dark bg-secondary').addClass('bg-danger').show();
    });
}

// ── Infinite Row Model datasource ──
function buildDatasource() {
    _removedRowIds = new Set();  // clear client-side removals on datasource reset
    return {
        getRows: function(params) {
            var sortCol = null, sortDir = 'asc';
            if (params.sortModel && params.sortModel.length > 0) {
                sortCol = params.sortModel[0].colId;
                sortDir = params.sortModel[0].sort || 'asc';
            }

            var qp = new URLSearchParams({
                draw: 1,
                start: params.startRow,
                length: params.endRow - params.startRow,
                recommendation: currentFilters.recommendation || '',
                'ssn_match': currentFilters.ssn_match || '',
            });
            if (currentFilters.min_name_score !== '') qp.set('min_name_score', currentFilters.min_name_score);
            if (currentFilters.max_name_score !== '') qp.set('max_name_score', currentFilters.max_name_score);
            if (currentFilters.min_addr_score !== '') qp.set('min_addr_score', currentFilters.min_addr_score);
            if (currentFilters.max_addr_score !== '') qp.set('max_addr_score', currentFilters.max_addr_score);
            if (currentFilters.search) qp.set('search[value]', currentFilters.search);
            if (sortCol) {
                qp.set('order[0][column]', '0');
                qp.set('order[0][dir]', sortDir);
                qp.set('columns[0][data]', sortCol);
            }

            fetch('/api/matches?' + qp.toString())
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    var rows = prefillProcessField(data.data || []);
                    // Filter out rows that were removed client-side (e.g. approved)
                    if (_removedRowIds.size > 0) {
                        rows = rows.filter(function(r) { return !_removedRowIds.has(r._row_id); });
                    }
                    lastRecordsTotal = data.recordsTotal || 0;
                    lastRecordsFiltered = (data.recordsFiltered || 0) - _removedRowIds.size;
                    if (lastRecordsFiltered < 0) lastRecordsFiltered = 0;
                    var rowCount = lastRecordsFiltered <= params.endRow ? lastRecordsFiltered : -1;
                    params.successCallback(rows, rowCount);
                    updateGridInfo();
                    // Update cache mode badge from response
                    if (data.cache_mode) {
                        var badge = $('#cacheModeBadge');
                        if (data.cache_mode === 'cached') {
                            badge.text('Cached').attr('title', 'Data is served from an in-memory cache for faster filtering and scrolling').removeClass('bg-secondary').addClass('bg-info text-dark').show();
                        } else {
                            badge.text('Live query').attr('title', 'Each request queries the database directly — used for multi-bucket views or search').removeClass('bg-info text-dark').addClass('bg-secondary').show();
                        }
                    }
                })
                .catch(function() {
                    params.failCallback();
                });
        }
    };
}

function applyServerFilters() {
    if (typeof gridApi !== 'undefined' && gridApi) {
        gridApi.setGridOption('datasource', buildDatasource());
    }
}

// ── Document ready ──
$(document).ready(function() {
    // --- User identity ---
    function getCookie(name) {
        var match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
        return match ? decodeURIComponent(match[1]) : null;
    }
    function setCookie(name, value, days) {
        var expires = new Date(Date.now() + days * 864e5).toUTCString();
        document.cookie = name + '=' + encodeURIComponent(value) + '; expires=' + expires + '; path=/; SameSite=Lax';
    }

    function initUserIdentity() {
        var userId = getCookie('user_id');
        var userName = getCookie('user_name');

        if (!userId) {
            // Generate a UUID and set it (server also sets it on page load,
            // but set client-side as a fallback)
            userId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                var r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
            setCookie('user_id', userId, 365);
        }

        if (!userName) {
            $('#identityBanner').removeClass('d-none');
            $('#identityDisplayName').text('Guest');
        } else {
            $('#navUserName').text(userName);
            $('#identityDisplayName').text(userName);
        }
    }

    $('#dismissIdentityBanner').on('click', function() {
        $('#identityBanner').addClass('d-none');
    });

    $('#setNameLink').on('click', function(e) {
        e.preventDefault();
        $('#usernameInput').val(getCookie('user_name') || '');
        bootstrap.Modal.getOrCreateInstance(document.getElementById('usernameModal')).show();
    });

    $('#saveUsernameBtn').on('click', function() {
        var name = $('#usernameInput').val().trim().slice(0, 50);
        if (!name) return;
        setCookie('user_name', name, 365);
        $('#navUserName').text(name);
        $('#identityDisplayName').text(name);
        $('#identityBanner').addClass('d-none');
        bootstrap.Modal.getInstance(document.getElementById('usernameModal')).hide();
        showToast('Name saved: ' + name, 'success');
    });

    initUserIdentity();

    // Initial load
    refreshBucketCounts();
    refreshCacheStatus();

    // Refresh counts every 5 minutes
    setInterval(refreshBucketCounts, 5 * 60 * 1000);
    setInterval(refreshCacheStatus, 60 * 1000);

    // Refresh button — calls /api/reload then refreshes grid and counts
    $('#refreshBtn').on('click', function() {
        $(this).prop('disabled', true);
        $('#cacheLoadingBadge').show();
        $.ajax({
            url: '/api/reload', method: 'POST',
            success: function(data) {
                showToast(data.message || 'Cache refreshed', 'success');
                refreshBucketCounts();
                refreshCacheStatus();
                loadStats();
                refreshGridData(function() { $('#cacheLoadingBadge').hide(); });
            },
            error: function(xhr) {
                showToast('Refresh failed', 'danger');
                $('#cacheLoadingBadge').hide();
            },
            complete: function() { $('#refreshBtn').prop('disabled', false); }
        });
    });

    editModal = new bootstrap.Modal(document.getElementById('editModal'));
    var recsReq     = $.get('/api/recommendations');
    var settingsReq = $.get('/api/grid_settings').then(null, function() {
        return { column_state: null, filter_state: null };
    });
    $.when(recsReq, settingsReq).done(function(recsResult, settingsResult) {
        var recs     = recsResult[0];
        var settings = settingsResult[0] || {};
        recommendationValues = sortByRecOrder(recs.slice());
        buildRecFilterDropdown(recommendationValues);
        recommendationValues.forEach(function(r) {
            $('#editRecommendation').append('<option value="' + r + '">' + r + '</option>');
        });
        $('#editRecommendation').append('<option value="PROCESSED">PROCESSED</option>');
        $('#editRecommendation').append('<option value="STAGED">STAGED</option>');
        initGrid(settings.column_state, settings.filter_state);
        loadStats();
        loadStagingCount();
    });

    // Filter dropdowns trigger server-side filter refresh
    $('#ssnFilter').on('change', function() {
        currentFilters.ssn_match = $(this).val();
        applyServerFilters();
    });
    $('#minNameScore').on('change', function() {
        currentFilters.min_name_score = $(this).val();
        applyServerFilters();
    });
    $('#maxNameScore').on('change', function() {
        currentFilters.max_name_score = $(this).val();
        applyServerFilters();
    });
    $('#minAddrScore').on('change', function() {
        currentFilters.min_addr_score = $(this).val();
        applyServerFilters();
    });
    $('#maxAddrScore').on('change', function() {
        currentFilters.max_addr_score = $(this).val();
        applyServerFilters();
    });

    // Quick filter (search) — server-side
    var quickFilterTimer;
    $('#quickFilterInput').on('input', function() {
        var val = $(this).val();
        clearTimeout(quickFilterTimer);
        quickFilterTimer = setTimeout(function() {
            currentFilters.search = val;
            applyServerFilters();
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
            if (ids.length === 0) { showToast('No Source IDs found in file', 'warning'); $('#importType').val(''); return; }
            $.ajax({
                url: '/api/import_ids', method: 'POST', contentType: 'application/json',
                data: JSON.stringify({ field: field, source_ids: ids }),
                success: function(data) {
                    showToast(data.message, 'success');
                    // immediate save — no pending state
                    refreshGridData();
                },
                error: function(xhr) { showToast(xhr.responseJSON ? xhr.responseJSON.error : 'Import failed', 'error'); }
            });
            $('#importType').val('');
        };
        reader.readAsText(file);
    });

    // Cell selection + inline editing via event delegation on grid div
    // Store row-index (AG Grid's virtual row index) so selection survives scrolling
    var lastClickedCell = null;
    $('#matchesGrid').on('click', '.ag-cell', function(e) {
        var isSelect = $(e.target).is('select, option');
        // Allow select (Process dropdown) through for cell selection, skip other interactive elements
        if ($(e.target).is('input, button, i, a')) return;
        if (isSelect && !e.shiftKey) {
            // Plain click of a Process select: track as lastClickedCell but don't clear existing selection
            var selTd = $(this);
            var selRowIdx = parseInt(selTd.closest('.ag-row').attr('row-index'));
            lastClickedCell = { colId: selTd.attr('col-id'), rowIndex: selRowIdx };
            return;
        }
        var td = $(this);
        var colId = td.attr('col-id');
        var clickedRowIndex = parseInt(td.closest('.ag-row').attr('row-index'));

        if (e.shiftKey && lastClickedCell) {
            var lo = Math.min(lastClickedCell.rowIndex, clickedRowIndex);
            var hi = Math.max(lastClickedCell.rowIndex, clickedRowIndex);
            $('.cell-selected').removeClass('cell-selected');

            if (lastClickedCell.colId === colId) {
                // Store the selection range for Process multi-update (works with off-screen rows)
                processSelectionRange = { colId: colId, lo: lo, hi: hi };
                // Select all rendered cells in the range by row-index
                $('#matchesGrid .ag-row').each(function() {
                    var idx = parseInt($(this).attr('row-index'));
                    if (idx >= lo && idx <= hi) {
                        $(this).find('.ag-cell[col-id="' + colId + '"]').addClass('cell-selected');
                    }
                });
                window.getSelection().removeAllRanges();
            } else {
                processSelectionRange = null;
                td.closest('.ag-row').find('.ag-cell').addClass('cell-selected');
                var sel = window.getSelection();
                sel.removeAllRanges();
                var range = document.createRange();
                range.selectNodeContents(td.closest('.ag-row')[0]);
                sel.addRange(range);
            }
        } else {
            processSelectionRange = null;
            $('.cell-selected').removeClass('cell-selected');
            td.addClass('cell-selected');
            lastClickedCell = { colId: colId, rowIndex: clickedRowIndex };
        }
    });

    // Click outside grid clears cell selection and process range
    $(document).on('click', function(e) {
        if (!$(e.target).closest('#matchesGrid .ag-body-viewport').length) {
            $('.cell-selected').removeClass('cell-selected');
            processSelectionRange = null;
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
                var chkNode = gridApi.getRowNode(String(rid));
                var chkData = chkNode ? chkNode.data : {};
                var oldChkVal = undoChanges.filter(function(c) { return c.rowId === rid; }).map(function(c) { return c.oldValue; })[0];
                $.ajax({
                    url: '/api/update', method: 'POST', contentType: 'application/json',
                    data: JSON.stringify({
                        row_id: rid,
                        id: chkData.id,
                        source_id: chkData.source_id,
                        source_ssn: chkData.source_ssn,
                        field: field,
                        value: value,
                        old_value: oldChkVal !== undefined ? oldChkVal : '',
                    }),
                    success: function() {
                        if (++completed === rowIds.length) { showToast('Set ' + field.toUpperCase() + ' on ' + rowIds.length + ' rows', 'success'); refreshBucketCounts(); }
                    },
                    error: function() { showToast('Toggle failed', 'error'); }
                });
            });
        } else {
            var rowId = parseInt($(this).data('row-id'));
            var oldVal = value ? 0 : 1;
            pushUndo({ type: 'single', changes: [{ rowId: rowId, field: field, oldValue: oldVal, newValue: value }] });
            var singleNode = gridApi.getRowNode(String(rowId));
            var singleData = singleNode ? singleNode.data : {};
            $.ajax({
                url: '/api/update', method: 'POST', contentType: 'application/json',
                data: JSON.stringify({
                    row_id: rowId,
                    id: singleData.id,
                    source_id: singleData.source_id,
                    source_ssn: singleData.source_ssn,
                    field: field,
                    value: value,
                    old_value: oldVal,
                }),
                success: function(data) { showToast('Saved', 'success'); refreshBucketCounts(); },
                error: function(xhr) { showToast('Save failed: ' + ((xhr.responseJSON || {}).error || 'Unknown'), 'danger'); }
            });
        }
    });

    // Process inline dropdown — single record update
    function saveProcessValue(rowId, value, oldValue) {
        var procNode = gridApi.getRowNode(String(rowId));
        var procData = procNode ? procNode.data : {};
        $.ajax({
            url: '/api/update', method: 'POST', contentType: 'application/json',
            data: JSON.stringify({
                row_id: rowId,
                id: procData.id,
                source_id: procData.source_id,
                source_ssn: procData.source_ssn,
                field: 'how_to_process',
                value: value,
                old_value: oldValue || '',
            }),
            success: function(data) { showToast('Saved', 'success'); },
            error: function(xhr) { showToast('Save failed: ' + ((xhr.responseJSON || {}).error || 'Unknown'), 'danger'); }
        });
    }

    // Process bulk update — single request for many rows
    function bulkSaveProcessValues(rowIds, value) {
        $.ajax({
            url: '/api/bulk_field_update', method: 'POST', contentType: 'application/json',
            data: JSON.stringify({ row_ids: rowIds, field: 'how_to_process', value: value }),
            success: function(data) { showToast('Saved', 'success'); },
            error: function(xhr) { showToast('Save failed: ' + ((xhr.responseJSON || {}).error || 'Unknown'), 'danger'); }
        });
    }

    // Track the selected Process range (row indices) so changes apply to off-screen rows too
    var processSelectionRange = null;  // { colId, lo, hi } when a shift-select range is active

    // Process native <select> change handler (replaces agSelectCellEditor)
    $('#matchesGrid').on('change', '.process-select', function() {
        var $sel = $(this);
        var rowId = parseInt($sel.data('row-id'));
        var newValue = $sel.val();
        // Find the row node to get the old value (getRowNode works for loaded blocks)
        var rowNode = gridApi.getRowNode(String(rowId));

        var oldValue = rowNode ? (rowNode.data.how_to_process || '') : '';
        if (oldValue === newValue) return;

        // Check if a multi-cell range is active (use stored range, not just DOM)
        var hasRange = processSelectionRange && processSelectionRange.colId === 'how_to_process' &&
                       (processSelectionRange.hi - processSelectionRange.lo) > 0;
        if (hasRange) {
            var undoChanges = [];
            var bulkRowIds = [];
            var lo = processSelectionRange.lo;
            var hi = processSelectionRange.hi;
            // Iterate through ALL rows in the range via AG Grid API (not DOM)
            for (var i = lo; i <= hi; i++) {
                var node = gridApi.getDisplayedRowAtIndex(i);
                if (!node || !node.data) continue;
                var oldVal = node.data.how_to_process || '';
                if (oldVal !== newValue) {
                    undoChanges.push({ rowId: node.data._row_id, field: 'how_to_process', oldValue: oldVal, newValue: newValue });
                    node.setDataValue('how_to_process', newValue);
                    bulkRowIds.push(node.data._row_id);
                }
            }
            if (undoChanges.length > 0) pushUndo({ type: 'single', changes: undoChanges });
            if (bulkRowIds.length > 0) bulkSaveProcessValues(bulkRowIds, newValue);
        } else {
            pushUndo({ type: 'single', changes: [{ rowId: rowId, field: 'how_to_process', oldValue: oldValue, newValue: newValue }] });
            if (rowNode) rowNode.setDataValue('how_to_process', newValue);
            saveProcessValue(rowId, newValue, oldValue);
        }
    });

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
            var memoNode = gridApi.getRowNode(String(rowId));
            var memoData = memoNode ? memoNode.data : {};
            $.ajax({
                url: '/api/update', method: 'POST', contentType: 'application/json',
                data: JSON.stringify({
                    row_id: rowId,
                    id: memoData.id,
                    source_id: memoData.source_id,
                    source_ssn: memoData.source_ssn,
                    field: 'memo',
                    value: newVal,
                    old_value: curVal,
                }),
                success: function(data) { showToast('Saved', 'success'); refreshBucketCounts(); },
                error: function(xhr) { showToast('Memo save failed: ' + ((xhr.responseJSON || {}).error || 'Unknown'), 'danger'); }
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
        var oldVal = direction === 'undo' ? ch.newValue : ch.oldValue;
        if (ch.field === 'recommendation') hasRecChange = true;
        var undoNode = gridApi.getRowNode(String(ch.rowId));
        var undoData = undoNode ? undoNode.data : {};
        $.ajax({
            url: '/api/update', method: 'POST', contentType: 'application/json',
            data: JSON.stringify({
                row_id: ch.rowId,
                id: undoData.id,
                source_id: undoData.source_id,
                source_ssn: undoData.source_ssn,
                field: ch.field,
                value: val,
                old_value: oldVal,
            }),
            success: function(data) {
                // immediate save — no pending state
                var rowNode = gridApi.getRowNode(String(ch.rowId));
                if (rowNode) rowNode.setDataValue(ch.field, val);
                if (++completed === changes.length) {
                    setTimeout(function() { window._bulkProcessUpdate = false; }, 0);
                    if (hasRecChange) loadStats();
                    if (callback) callback();
                }
            },
            error: function() {
                if (++completed === changes.length) {
                    setTimeout(function() { window._bulkProcessUpdate = false; }, 0);
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
            '<div class="fw-bold text-truncate" style="font-size:0.82rem;" title="All Records">ALL - <span id="allRecordsCount">' + s.total_records.toLocaleString() + '</span></div>' +
            '</div></div></div>';
        recConfig = s.rec_config || {};
        var recCfg = recConfig;
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
                '<div class="fw-bold text-truncate" style="font-size:0.82rem;">' + rec + ' - <span class="bucket-count" data-bucket="' + rec + '">' + count.toLocaleString() + '</span> <span class="text-muted fw-normal">(' + pct + '%)</span></div>' +
                '</div></div></div>';
        });
        $('#recBreakdown').html(html);
        refreshBucketCounts();
    });
}

function filterByRec(rec) {
    activeRecFilter = rec;
    currentFilters.recommendation = rec;
    $('#ssnFilter').val('');
    currentFilters.ssn_match = '';
    var cfg = recConfig[rec];
    if (cfg) {
        $('#minNameScore').val(cfg.min_name || '');
        $('#maxNameScore').val(cfg.max_name || '');
        $('#minAddrScore').val(cfg.min_addr || '');
        $('#maxAddrScore').val(cfg.max_addr || '');
        currentFilters.min_name_score = cfg.min_name || '';
        currentFilters.max_name_score = cfg.max_name || '';
        currentFilters.min_addr_score = cfg.min_addr || '';
        currentFilters.max_addr_score = cfg.max_addr || '';
    } else {
        $('#minNameScore').val('');
        $('#maxNameScore').val('');
        $('#minAddrScore').val('');
        $('#maxAddrScore').val('');
        currentFilters.min_name_score = '';
        currentFilters.max_name_score = '';
        currentFilters.min_addr_score = '';
        currentFilters.max_addr_score = '';
    }
    gridApi && gridApi.deselectAll();
    selectedRows.clear();
    selectedRowDataMap.clear();
    applyServerFilters();
    updateSelectionInfo();
    try { localStorage.setItem('agGridFilterState', JSON.stringify({ recommendation: rec })); } catch(e) {}
}

function filterByStat(type) {
    if (type === 'all') { clearFilters(); }
    else if (type === 'ssn_yes') { $('#ssnFilter').val('yes'); currentFilters.ssn_match = 'yes'; applyServerFilters(); }
    else if (type === 'ssn_partial') { $('#ssnFilter').val('partial'); currentFilters.ssn_match = 'partial'; applyServerFilters(); }
    else if (type === 'ssn_no') { $('#ssnFilter').val('no'); currentFilters.ssn_match = 'no'; applyServerFilters(); }
}

function applyFilters() {
    applyServerFilters();
}

function openDevNotes() {
    $.get('/api/dev_notes').fail(function(xhr) {
        showToast(xhr.responseJSON ? xhr.responseJSON.error : 'Could not open Dev Notes', 'error');
    });
}

function clearFilters() {
    activeRecFilter = '';
    currentFilters.recommendation = '';
    currentFilters.ssn_match = '';
    currentFilters.min_name_score = '';
    currentFilters.max_name_score = '';
    currentFilters.min_addr_score = '';
    currentFilters.max_addr_score = '';
    currentFilters.search = '';
    $('#ssnFilter').val('');
    $('#minNameScore').val('');
    $('#maxNameScore').val('');
    $('#minAddrScore').val('');
    $('#maxAddrScore').val('');
    $('#quickFilterInput').val('');
    applyServerFilters();
    updateSelectionInfo();
}

function refreshData() {
    showToast('Reloading from Snowflake...', 'info');
    $.post('/api/reload', function(data) {
        // immediate save — no pending state
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
    var stagedMode = activeRecFilter.toUpperCase() === 'STAGED';
    $('#selectionInfo').text(n === 0 ? 'No records selected' : n + ' record(s) selected');
    $('#bulkApproveBtn').prop('disabled', n === 0 || stagedMode);
}

// ── Address line counter (45-char/line soft limit) ──
function updateAddrLineCounters() {
    var val = $('#editSourceAddress').val() || '';
    var lines = val.split('\n');
    var html = '';
    for (var i = 0; i < lines.length; i++) {
        var len = lines[i].length;
        var over = len > 45;
        var cls = over ? 'text-danger fw-bold' : 'text-success';
        html += '<span class="' + cls + '">Line ' + (i + 1) + ': ' + len + '/45</span>';
        if (i < lines.length - 1) html += ' &nbsp;|&nbsp; ';
    }
    $('#addrLineCounters').html(html);
}

// ── Edit modal ──
function editRecord(rowId) {
    $.get('/api/record/' + rowId, function(d) {
        $('#editRowId').val(d._row_id);
        $('#editRecordId').val(d.id);
        $('#editSourceIdHidden').val(d.source_id);
        $('#editSourceSsnHidden').val(d.source_ssn);
        $('#editSourceName').val(d.source_name || '');
        $('#editSourceAddress').val(d.source_address || '');
        updateAddrLineCounters();
        $('#editSourceAddress').off('input.addrcount').on('input.addrcount', updateAddrLineCounters);
        $('#editSourceCity').val(d.source_city || '');
        $('#editSourceState').val(d.source_state || '');
        $('#editSourceZip').val(d.source_zip || '');
        $('#editSourceId').text(d.source_addrseq ? (d.source_id + '-' + d.source_addrseq) : (d.source_id || ''));
        $('#editSourceSSN').text(d.source_ssn || '');
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
        // Disable editing for STAGED records
        var staged = (d.recommendation || '').toUpperCase() === 'STAGED';
        $('#editModal .modal-body input, #editModal .modal-body textarea, #editModal .modal-body select').prop('disabled', staged);
        $('#editModal .btn-primary').prop('disabled', staged);
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
        'source_name': $('#editSourceName').val(),
        'source_address_recomend': $('#editSourceAddress').val(),
        'source_city': $('#editSourceCity').val(),
        'source_state': $('#editSourceState').val(),
        'source_zip': $('#editSourceZip').val(),
        'recommendation': $('#editRecommendation').val(),
        'address_reason': $('#editAddressReason').val(),
        'memo': $('#editMemo').val()
    };

    var pending = Object.keys(fields).length;
    var errors = [];
    var modalRecordId = $('#editRecordId').val() || rowId;
    var modalSourceId = $('#editSourceIdHidden').val() || '';
    var modalSourceSsn = $('#editSourceSsnHidden').val() || '';

    // Retrieve the current row data to get old values for each field
    var editNode = gridApi.getRowNode(String(rowId));
    var editData = editNode ? editNode.data : {};

    Object.entries(fields).forEach(function(entry) {
        var field = entry[0], value = entry[1];
        var oldValue = editData[field] !== undefined ? String(editData[field] || '') : '';
        $.ajax({
            url: '/api/update', method: 'POST', contentType: 'application/json',
            data: JSON.stringify({
                row_id: rowId,
                id: modalRecordId,
                source_id: modalSourceId,
                source_ssn: modalSourceSsn,
                field: field,
                value: value,
                old_value: oldValue,
            }),
            success: function(data) {
                // immediate save — no pending state
                if (--pending === 0) onSaveDone(errors);
            },
            error: function() { errors.push(field); if (--pending === 0) onSaveDone(errors); }
        });
    });
}

function onSaveDone(errors) {
    if (errors.length === 0) {
        showToast('Changes saved', 'success');
        editModal.hide();
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
        var approveData = rowNode ? Object.assign({}, rowNode.data) : {};
        pushUndo({ type: 'single', changes: [{ rowId: rowId, field: 'recommendation', oldValue: oldVal, newValue: 'APPROVED' }] });
        // Hide row immediately — no grid refresh needed
        _removedRowIds.add(rowId);
        gridApi.purgeInfiniteCache();
        updateGridInfo();
        showToast('Approved', 'success');
        $.ajax({
            url: '/api/update', method: 'POST', contentType: 'application/json',
            data: JSON.stringify({
                row_id: rowId,
                id: approveData.id,
                source_id: approveData.source_id,
                source_ssn: approveData.source_ssn,
                field: 'recommendation',
                value: 'APPROVED',
                old_value: oldVal,
            }),
            success: function(data) {
                refreshBucketCounts();
                loadStats();
            },
            error: function(xhr) {
                // Restore row on failure
                _removedRowIds.delete(rowId);
                gridApi.purgeInfiniteCache();
                showToast('Save failed: ' + ((xhr.responseJSON || {}).error || 'Unknown'), 'danger');
            }
        });
    });
}

function bulkApprove() {
    var n = selectedRows.size;
    if (n === 0) return;
    showConfirm('Approve Selected', '<i class="fas fa-check-circle text-success fa-2x mb-2"></i><br>Approve <strong>' + n + '</strong> selected record' + (n > 1 ? 's' : '') + '?', function() {
        var undoChanges = [];
        var processValues = {};
        selectedRows.forEach(function(rid) {
            var node = gridApi.getRowNode(String(rid));
            var rowData = (node && node.data) ? node.data : (selectedRowDataMap.get(rid) || {});
            var oldVal = rowData.recommendation || '';
            undoChanges.push({ rowId: rid, field: 'recommendation', oldValue: oldVal, newValue: 'APPROVED' });
            // Capture the current process value (may be pre-filled client-side) so it
            // gets persisted alongside the recommendation change.
            if (rowData.how_to_process) {
                processValues[rid] = rowData.how_to_process;
            }
        });
        if (undoChanges.length > 0) pushUndo({ type: 'bulk', changes: undoChanges });
        var bulkRecords = [];
        selectedRowDataMap.forEach(function(data, id) {
            if (selectedRows.has(id)) {
                bulkRecords.push({
                    id: data.id,
                    source_id: data.source_id || '',
                    source_ssn: data.source_ssn || '',
                    old_recommendation: data.recommendation || '',
                });
            }
        });
        // Hide rows immediately — no grid refresh needed
        var approvedIds = [];
        selectedRows.forEach(function(rid) { approvedIds.push(rid); _removedRowIds.add(rid); });
        gridApi.deselectAll();
        selectedRows.clear();
        selectedRowDataMap.clear();
        updateSelectionInfo();
        gridApi.purgeInfiniteCache();
        updateGridInfo();
        showToast('Approved ' + approvedIds.length + ' record' + (approvedIds.length !== 1 ? 's' : ''), 'success');
        $.ajax({
            url: '/api/bulk_update', method: 'POST', contentType: 'application/json',
            data: JSON.stringify({ records: bulkRecords, recommendation: 'APPROVED', process_values: processValues }),
            success: function(data) {
                refreshBucketCounts();
                loadStats();
                loadStagingCount();
            },
            error: function(xhr) {
                // Restore rows on failure
                approvedIds.forEach(function(rid) { _removedRowIds.delete(rid); });
                gridApi.purgeInfiniteCache();
                showToast('Bulk approve failed: ' + ((xhr.responseJSON || {}).error || 'Unknown'), 'danger');
            }
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

// ── Staging ──
var stagingCount = 0;

function loadStagingCount() {
    $.get('/api/staging_count', function(data) {
        stagingCount = data.count || 0;
        updateStagingBtn();
    });
}

function updateStagingBtn() {
    var btn = $('#stageApprovedBtn');
    btn.prop('disabled', stagingCount === 0);
    btn.find('.stage-count').text(stagingCount > 0 ? ' (' + stagingCount + ')' : '');
}

function stageApproved() {
    if (stagingCount === 0) {
        showToast('No eligible records to stage', 'info');
        return;
    }
    showConfirm(
        'Stage Approved Records',
        'Move <strong>' + stagingCount + '</strong> approved record(s) to the staging table?<br>Their status will change to <strong>STAGED</strong> and they will be hidden from the default view.',
        function() {
            var btn = $('#stageApprovedBtn');
            btn.prop('disabled', true);
            $.ajax({
                url: '/api/stage_approved', method: 'POST', contentType: 'application/json',
                data: JSON.stringify({}),
                success: function(data) {
                    showToast(data.message, 'success');
                    refreshGridData();
                    loadStats();
                    loadStagingCount();
                },
                error: function(xhr) {
                    showToast(xhr.responseJSON ? xhr.responseJSON.error : 'Staging failed', 'error');
                    updateStagingBtn();
                }
            });
        }
    );
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
    'source_name', 'source_address_recomend', 'source_city', 'source_state', 'source_zip',
    'how_to_process', 'memo', 'address_reason', 'recommendation'
];

var srHighlightInterval = null;

function srClearHighlight() {
    if (srHighlightInterval) { clearInterval(srHighlightInterval); srHighlightInterval = null; }
    document.querySelectorAll('.ag-cell.sr-highlight, .ag-cell.sr-highlight-current').forEach(function(cell) {
        cell.classList.remove('sr-highlight', 'sr-highlight-current');
        cell.querySelectorAll('.sr-match-text').forEach(function(span) {
            span.replaceWith(document.createTextNode(span.textContent));
        });
    });
}

function srApplyHighlights() {
    // Re-apply every 200ms so AG Grid virtualisation doesn't lose the highlights.
    var search = $('#srSearch').val();
    if (!search || !srMatches.length) return;
    var caseSensitive = $('#srCaseSensitive').is(':checked');
    var flags = caseSensitive ? 'g' : 'gi';
    var re = new RegExp('(' + search.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', flags);

    // Build nodeId → [col] lookup for O(1) checks
    var matchMap = {};
    srMatches.forEach(function(m) {
        if (!matchMap[m.nodeId]) matchMap[m.nodeId] = [];
        if (matchMap[m.nodeId].indexOf(m.col) === -1) matchMap[m.nodeId].push(m.col);
    });
    var cur = srMatchIdx >= 0 && srMatchIdx < srMatches.length ? srMatches[srMatchIdx] : null;

    document.querySelectorAll('.ag-row').forEach(function(rowEl) {
        var nodeId = rowEl.getAttribute('row-id');
        if (!matchMap[nodeId]) return;
        matchMap[nodeId].forEach(function(col) {
            var cell = rowEl.querySelector('.ag-cell[col-id="' + col + '"]');
            if (!cell) return;
            // Wrap matched text if not already done (guard against double-wrap on re-render)
            if (!cell.querySelector('.sr-match-text')) {
                cell.innerHTML = cell.innerHTML.replace(re, '<span class="sr-match-text">$1</span>');
            }
            cell.classList.add('sr-highlight');
            var isCurrent = cur && cur.nodeId === nodeId && cur.col === col;
            cell.classList.toggle('sr-highlight-current', isCurrent);
        });
    });
}

function srFindPrev() {
    var search = $('#srSearch').val();
    if (!search) { $('#srMatchInfo').text('Enter search text.'); return; }
    if (srMatches.length === 0) { srBuildMatches(); }
    if (srMatches.length === 0) { srUpdateInfo(); return; }
    srMatchIdx = (srMatchIdx - 1 + srMatches.length) % srMatches.length;
    srHighlightMatch();
    srUpdateInfo();
}

function openSearchReplace() {
    if (!srModal) {
        // backdrop:false keeps the grid interactive while the panel is open
        srModal = new bootstrap.Modal(document.getElementById('searchReplaceModal'), { backdrop: false });
        var srFindTimer;
        // #srSearch: input only — the 'change' event fires on blur and can race
        // with Find Next clicks, resetting srMatchIdx unexpectedly.
        $('#srSearch').on('input', function() {
            clearTimeout(srFindTimer);
            srMatches = []; srMatchIdx = -1;
            srClearHighlight();
            srFindTimer = setTimeout(srAutoFind, 300);
        });
        $('#srColumn, #srCaseSensitive').on('input change', function() {
            clearTimeout(srFindTimer);
            srMatches = []; srMatchIdx = -1;
            srClearHighlight();
            srFindTimer = setTimeout(srAutoFind, 300);
        });

        // Make modal draggable by its header
        var srModalEl = document.getElementById('searchReplaceModal');
        var srDialog = srModalEl.querySelector('.modal-dialog');
        var srHeader = srModalEl.querySelector('.modal-header');
        var srDragX = 0, srDragY = 0, srDragging = false, srOriginX, srOriginY;
        srHeader.style.cursor = 'move';
        srHeader.addEventListener('mousedown', function(e) {
            if (e.target.closest('button')) return;
            srDragging = true;
            srOriginX = e.clientX - srDragX;
            srOriginY = e.clientY - srDragY;
            e.preventDefault();
        });
        document.addEventListener('mousemove', function(e) {
            if (!srDragging) return;
            srDragX = e.clientX - srOriginX;
            srDragY = e.clientY - srOriginY;
            srDialog.style.transform = 'translate(' + srDragX + 'px, ' + srDragY + 'px)';
        });
        document.addEventListener('mouseup', function() { srDragging = false; });

        // Bootstrap adds overflow:hidden + padding-right to body when a modal opens.
        // Remove those immediately so the grid behind remains fully usable.
        srModalEl.addEventListener('shown.bs.modal', function() {
            document.body.classList.remove('modal-open');
            document.body.style.overflow = '';
            document.body.style.paddingRight = '';
        });

        // Clear highlight and reset position when modal closes
        srModalEl.addEventListener('hidden.bs.modal', function() {
            srClearHighlight();
            srDragX = 0; srDragY = 0;
            srDialog.style.transform = '';
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
        // In infinite row model, iterate loaded rows via displayed row count
        var rowCount = gridApi.getDisplayedRowCount();
        for (var i = 0; i < rowCount; i++) {
            var node = gridApi.getDisplayedRowAtIndex(i);
            if (node && node.data && node.data._row_id !== undefined) ids.push(node.data._row_id);
        }
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

    // In infinite row model, search only loaded (currently visible) rows
    var rowCount = gridApi.getDisplayedRowCount();
    for (var idx = 0; idx < rowCount; idx++) {
        var node = gridApi.getDisplayedRowAtIndex(idx);
        if (!node || !node.data) continue;
        cols.forEach(function(c) {
            var val = String(node.data[c] || '');
            var cmp = caseSensitive ? val : val.toLowerCase();
            if (cmp.indexOf(searchVal) !== -1) {
                srMatches.push({ rowId: node.data._row_id, nodeId: node.id, col: c });
            }
        });
    }
}

function srHighlightMatch() {
    if (srMatchIdx < 0 || srMatchIdx >= srMatches.length) return;
    var m = srMatches[srMatchIdx];
    var node = gridApi.getRowNode(m.nodeId);
    if (!node) return;
    // Ensure the column is visible and scroll current match into view.
    // Check the live column object (.visible) rather than the static colDef.hide,
    // because the user may have hidden a column at runtime via the column state.
    var col = gridApi.getColumn(m.col);
    if (col && !col.visible) {
        gridApi.setColumnVisible(m.col, true);
    }
    gridApi.ensureColumnVisible(m.col, 'start');
    gridApi.ensureNodeVisible(node, 'middle');
    // Re-apply highlights (sr-highlight-current will move to the new match)
    setTimeout(srApplyHighlights, 100);
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
    if (!search) {
        $('#srMatchInfo').text(''); srMatches = []; srMatchIdx = -1;
        srClearHighlight();
        return;
    }
    srClearHighlight();
    srBuildMatches();
    if (srMatches.length > 0) {
        srMatchIdx = 0;
        srHighlightMatch();
        // Persistent interval keeps highlights alive through AG Grid virtualisation
        if (srHighlightInterval) clearInterval(srHighlightInterval);
        srHighlightInterval = setInterval(srApplyHighlights, 200);
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

// Returns true if replacing `search` with `replace` in `cellVal` would produce a net change.
// Used to pre-screen matches client-side before sending to the backend, avoiding pointless
// round-trips for already-uppercase / already-matching values.
function srWouldChange(cellVal, search, replace, caseSensitive) {
    if (!cellVal) return false;
    var s = caseSensitive ? cellVal : cellVal.toLowerCase();
    var q = caseSensitive ? search  : search.toLowerCase();
    if (s.indexOf(q) === -1) return false;
    // Simulate the replacement and compare
    var flags = caseSensitive ? 'g' : 'gi';
    var escaped = search.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    var newVal = cellVal.replace(new RegExp(escaped, flags), replace);
    return newVal !== cellVal;
}

function srReplaceCurrent() {
    var search = $('#srSearch').val();
    var replace = $('#srReplace').val();
    if (!search) { $('#srMatchInfo').text('Enter search text.'); return; }

    // Ensure matches are built (may be stale if the debounce timer hasn't fired yet)
    if (srMatches.length === 0) { srBuildMatches(); }
    if (srMatches.length === 0) { srUpdateInfo(); return; }
    if (srMatchIdx < 0) { srMatchIdx = 0; }

    var caseSensitive = $('#srCaseSensitive').is(':checked');

    // Advance past any matches where the replacement would produce no net change
    // (e.g. search="Add", replace="ADD" on a cell that already reads "ADD").
    // We do this client-side to avoid a round-trip for every no-op match.
    var startIdx = srMatchIdx;
    var m = null;
    while (true) {
        var candidate = srMatches[srMatchIdx];
        if (!candidate) break;
        var node = gridApi.getRowNode(candidate.nodeId);
        var cellVal = (node && node.data) ? String(node.data[candidate.col] || '') : '';
        if (srWouldChange(cellVal, search, replace, caseSensitive)) {
            m = candidate;
            break;
        }
        // This match is a no-op — advance to the next one
        srMatchIdx = (srMatchIdx + 1) % srMatches.length;
        if (srMatchIdx === startIdx) {
            // Wrapped all the way around — every remaining match is a no-op
            $('#srMatchInfo').text('No replaceable matches found (replacement text already present in all ' + srMatches.length + ' match' + (srMatches.length !== 1 ? 'es' : '') + ').');
            srHighlightMatch();
            return;
        }
    }

    if (!m) { srUpdateInfo(); return; }

    // Highlight the match we are about to replace so the user can see it
    srHighlightMatch();
    srUpdateInfo();

    $.ajax({
        url: '/api/search_replace', method: 'POST', contentType: 'application/json',
        data: JSON.stringify({
            search: search, replace: replace,
            column: m.col,
            case_sensitive: caseSensitive,
            mode: 'replace',
            row_ids: [m.rowId]
        }),
        success: function(data) {
            if (data.replaced > 0) {
                // immediate save — no pending state
                loadStats();

                // Stop the highlight interval so it doesn't fight with the cell update
                if (srHighlightInterval) { clearInterval(srHighlightInterval); srHighlightInterval = null; }

                // ── Immediate visual update ──
                // Update the matched cell RIGHT NOW so the user can see the text
                // change before the grid scrolls to the next match.
                var replacedNode = gridApi.getRowNode(m.nodeId);
                if (replacedNode) {
                    var newData = Object.assign({}, replacedNode.data);
                    var flags = caseSensitive ? 'g' : 'gi';
                    var esc = search.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                    newData[m.col] = String(replacedNode.data[m.col] || '').replace(new RegExp(esc, flags), replace);
                    replacedNode.setData(newData);
                }

                var replacedIdx = srMatchIdx;

                // Brief pause (600ms) so user can see the updated cell text, then advance
                setTimeout(function() {
                    srClearHighlight();
                    refreshGridData(function() {
                        srMatches = []; srMatchIdx = -1;
                        srBuildMatches();
                        if (srMatches.length === 0) {
                            srUpdateInfo();
                        } else {
                            srMatchIdx = Math.min(replacedIdx, srMatches.length - 1);
                            srHighlightMatch();
                            srUpdateInfo();
                        }
                    });
                }, 600);
            } else {
                // Backend made no change — advance to next match
                if (srMatches.length > 0) {
                    srMatchIdx = (srMatchIdx + 1) % srMatches.length;
                    srHighlightMatch();
                    srUpdateInfo();
                } else {
                    $('#srMatchInfo').text('No matches found.');
                }
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
                showToast('Replaced ' + data.replaced + ' occurrence' + (data.replaced !== 1 ? 's' : '') + ' in ' + data.rows + ' row' + (data.rows !== 1 ? 's' : ''), 'success');
                // immediate save — no pending state
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

// ── BA Config Editor ────────────────────────────────────────────────────────

var _configDefaults = {};
var _configModal = null;

function openConfigModal() {
    if (!_configModal) {
        _configModal = new bootstrap.Modal(document.getElementById('configModal'));
    }
    $('#configModalBody').html('<div class="text-center text-muted py-4"><i class="fas fa-spinner fa-spin me-2"></i>Loading...</div>');
    _configModal.show();

    $.when(
        $.getJSON('/api/ba_config/all'),
        $.getJSON('/api/ba_config/defaults')
    ).done(function(rowsResp, defaultsResp) {
        var rows = rowsResp[0];
        _configDefaults = defaultsResp[0];
        _renderConfigModal(rows);
    }).fail(function(xhr, textStatus, errorThrown) {
        var msg = (xhr && xhr.responseJSON && xhr.responseJSON.error)
            ? xhr.responseJSON.error
            : (xhr && xhr.status ? 'HTTP ' + xhr.status + ': ' + (xhr.responseText || errorThrown) : errorThrown || textStatus || 'Unknown error');
        console.error('Config load failed:', xhr && xhr.status, textStatus, errorThrown, xhr && xhr.responseText);
        $('#configModalBody').html('<div class="alert alert-danger" style="font-size:0.82rem;white-space:pre-wrap;word-break:break-all">Failed to load config: ' + _escHtml(String(msg).substring(0, 500)) + '</div>');
    });
}

function _renderConfigModal(rows) {
    var groups = {};
    rows.forEach(function(r) {
        if (!groups[r.category]) groups[r.category] = [];
        groups[r.category].push(r);
    });

    var html = '<table class="table table-sm table-bordered mb-0" style="font-size:0.85rem;">';
    html += '<thead class="table-light"><tr><th>Category</th><th>Config Key</th><th style="width:180px">Value</th></tr></thead><tbody>';

    Object.keys(groups).sort().forEach(function(cat) {
        groups[cat].forEach(function(r) {
            var hasDefault = _configDefaults.hasOwnProperty(r.config_key);
            var indicator = hasDefault ? ' <span class="text-muted" title="Has default value" style="font-size:0.75em;">&#8635;</span>' : '';
            var valLower = (r.config_value || '').toLowerCase();
            var isBoolean = (valLower === 'true' || valLower === 'false');
            var inputHtml;
            if (isBoolean) {
                inputHtml = '<select class="form-select form-select-sm config-val-input"' +
                    ' data-category="' + _escHtml(r.category) + '"' +
                    ' data-key="' + _escHtml(r.config_key) + '"' +
                    ' data-original="' + _escHtml(r.config_value) + '">' +
                    '<option value="true"' + (valLower === 'true' ? ' selected' : '') + '>true</option>' +
                    '<option value="false"' + (valLower === 'false' ? ' selected' : '') + '>false</option>' +
                    '</select>';
            } else {
                inputHtml = '<input type="text" class="form-control form-control-sm config-val-input"' +
                    ' data-category="' + _escHtml(r.category) + '"' +
                    ' data-key="' + _escHtml(r.config_key) + '"' +
                    ' data-original="' + _escHtml(r.config_value) + '"' +
                    ' value="' + _escHtml(r.config_value) + '">';
            }
            html += '<tr>' +
                '<td class="text-muted" style="white-space:nowrap">' + _escHtml(r.category) + '</td>' +
                '<td style="font-family:monospace">' + _escHtml(r.config_key) + indicator + '</td>' +
                '<td>' + inputHtml + '</td>' +
                '</tr>';
        });
    });

    html += '</tbody></table>';
    $('#configModalBody').html(html);
}

function revertConfigToDefaults() {
    $('#configModalBody .config-val-input').each(function() {
        var key = $(this).data('key');
        if (_configDefaults.hasOwnProperty(key)) {
            $(this).val(_configDefaults[key]);
        }
    });
    showToast('Defaults loaded \u2014 click Save Changes to persist', 'info');
}

function saveConfigChanges() {
    var changed = [];
    $('#configModalBody .config-val-input').each(function() {
        var val = $(this).val();
        if (val !== String($(this).data('original'))) {
            changed.push({
                category:     $(this).data('category'),
                config_key:   $(this).data('key'),
                config_value: val
            });
        }
    });

    if (changed.length === 0) {
        showToast('No changes to save', 'info');
        return;
    }

    var promises = changed.map(function(row) {
        return $.ajax({
            url: '/api/ba_config/update',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(row)
        });
    });

    $.when.apply($, promises).done(function() {
        showToast('Config saved (' + changed.length + ' value' + (changed.length !== 1 ? 's' : '') + ')', 'success');
        if (_configModal) _configModal.hide();
    }).fail(function(xhr) {
        showToast('Save failed: ' + (xhr.responseJSON ? xhr.responseJSON.error : 'Unknown error'), 'error');
    });
}

function _escHtml(str) {
    if (str == null) return '';
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
