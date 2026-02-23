let table;
let selectedRows = new Set();
let editModal;
let recommendationValues = [];
let pendingCount = 0;

// Pattern to detect "do not use" variations: DO NOT USE, DON'T USE, DONT USE, D.N.U., DNU, DNU, etc.
const DO_NOT_USE_RE = /do\s*n[o']?t\s*use|don[''\u2019]t\s*use|d\.?n\.?u\.?(?!\w)/i;

// Preferred display order for recommendations (dropdown, stats cards)
const REC_ORDER = [
    'NEW BA - NO DEC MATCH',
    'LIKELY BA MATCH - SSN MATCH NAME MISMATCH',
    'EXISTING BA - EXISTING ADDRESS',
    'EXISTING BA - LIKELY SAME ADDRESS',
    'EXISTING BA - NEW ADDRESS',
    'NEW BA - NO SSN',
    'NEW BA - INVALID SSN',
    'APPROVED'
];

// Color map for recommendation badges
const REC_COLORS = {
    'EXISTING BA - EXISTING ADDRESS': '#28a745',
    'EXISTING BA - NEW ADDRESS': '#17a2b8',
    'EXISTING BA - LIKELY SAME ADDRESS': '#20c997',
    'NEW BA - NO DEC MATCH': '#6c757d',
    'NEW BA - NO SSN': '#fd7e14',
    'NEW BA - INVALID SSN': '#dc3545',
    'LIKELY BA MATCH - SSN MATCH NAME MISMATCH': '#ffc107',
    'APPROVED': '#0d6efd'
};

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
        applyFilters();
    });
}

function getSelectedRecs() {
    var checked = [];
    $('.rec-check:checked').each(function() {
        checked.push($(this).val());
    });
    return checked;
}

function updateRecFilterLabel() {
    var checked = getSelectedRecs();
    var label;
    if (checked.length === 0) {
        label = 'All';
    } else if (checked.length === 1) {
        label = checked[0];
    } else {
        label = checked.length + ' selected';
    }
    $('.rec-filter-label').text(label);
}

function toggleAllRecs(selectAll) {
    $('.rec-check').prop('checked', selectAll);
    updateRecFilterLabel();
    applyFilters();
}

// Column visibility dropdown  [label, header color, column name, default visible]
const COL_DEFS = [
    ['UID', '#212529', 'uid', false],
    ['SSN', '#212529', 'ssn'],
    ['Name Score', '#212529', 'name_score'],
    ['Addr Score', '#212529', 'addr_score'],
    ['Status', '#212529', 'recommendation'],
    ['Process', '#212529', 'how_to_process'],
    ['Canvas Name', '#1e3a8a', 'canvas_name'],
    ['Canvas Addr', '#1e3a8a', 'canvas_addr'],
    ['Canvas City/St/Zip', '#1e3a8a', 'canvas_csz'],
    ['Canvas ID', '#1e3a8a', 'canvas_id', false],
    ['DEC Name', '#9b4d6e', 'dec_name'],
    ['DEC Addr', '#9b4d6e', 'dec_addr'],
    ['DEC City/St/Zip', '#9b4d6e', 'dec_csz'],
    ['DEC Code', '#9b4d6e', 'dec_code', false],
    ['Address Lookup', '#9b4d6e', 'addr_lookup', false],
    ['JIB', '#212529', 'jib', false],
    ['Rev', '#212529', 'rev', false],
    ['Vendor', '#212529', 'vendor', false],
    ['Memo', '#212529', 'memo']
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
        table.column(colName + ':name').visible(visible);
    });
}

function toggleAllCols(show) {
    $('.col-vis-check').each(function() {
        $(this).prop('checked', show);
        var colName = $(this).data('col-name');
        table.column(colName + ':name').visible(show);
    });
}

$(document).ready(function() {
    editModal = new bootstrap.Modal(document.getElementById('editModal'));

    // Load available data sources
    loadDataSources();

    // Handle data source switching
    $('#datasourceSelector').on('change', function() {
        const sourceId = $(this).val();
        if (!sourceId) return;
        const dsType = $(this).find(':selected').data('type');

        if (dsType === 'excel') {
            // Open native file picker, then switch with chosen path
            $.get('/api/browse_excel', function(resp) {
                if (resp.cancelled) {
                    loadDataSources(); // reset dropdown
                    return;
                }
                if (resp.error) {
                    showToast(resp.error, 'error');
                    loadDataSources();
                    return;
                }
                switchDataSource(sourceId, resp.file_path);
            }).fail(function() {
                showToast('Could not open file browser', 'error');
                loadDataSources();
            });
        } else {
            switchDataSource(sourceId);
        }
    });

    // Load recommendations for dropdowns, then init table
    $.get('/api/recommendations', function(recs) {
        recommendationValues = sortByRecOrder(recs.slice());

        // Build multi-select checkbox dropdown for filter
        buildRecFilterDropdown(recommendationValues);

        // Populate edit modal dropdown (sorted)
        recommendationValues.forEach(function(r) {
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
    $('#ssnFilter, #minNameScore, #maxNameScore, #minAddrScore, #maxAddrScore').on('change', function() {
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

    // Cell selection (click = single cell, Shift+click = column range with text selection)
    let lastClickedCell = null;
    $('#matchesTable').on('click', 'tbody td', function(e) {
        if ($(e.target).is('input, button, i, a')) return;
        const td = $(this);
        const colIdx = td.index();

        if (e.shiftKey && lastClickedCell) {
            // Shift+click: select range in same column (or row if different column)
            const rows = $('#matchesTable tbody tr:visible');
            const startRow = rows.index(lastClickedCell.tr);
            const endRow = rows.index(td.closest('tr'));
            const lo = Math.min(startRow, endRow);
            const hi = Math.max(startRow, endRow);
            $('.cell-selected').removeClass('cell-selected');

            if (lastClickedCell.colIdx === colIdx) {
                // Same column: select range of cells in that column
                rows.slice(lo, hi + 1).each(function() {
                    $(this).find('td').eq(colIdx).addClass('cell-selected');
                });
                // Clear native selection — Ctrl+C handler copies .cell-selected
                window.getSelection().removeAllRanges();
            } else {
                // Different column: select all cells in clicked row
                td.closest('tr').find('td').addClass('cell-selected');
                // Native select the row text
                const sel = window.getSelection();
                sel.removeAllRanges();
                const range = document.createRange();
                range.selectNodeContents(td.closest('tr')[0]);
                sel.addRange(range);
            }
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
            var sel = window.getSelection();
            if (sel && sel.toString().length > 0) {
                return; // let browser copy the highlighted text
            }
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

    // Process: click text to open inline dropdown, save on change
    var PROCESS_OPTS = ['Add new BA and address', 'Merge BA - add addr', 'Merge BA and address', 'Manual Review -DNP'];

    function saveProcessValue(rowId, value) {
        $.ajax({
            url: '/api/update',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ row_id: rowId, field: 'how_to_process', value: value }),
            success: function(data) {
                pendingCount = data.pending_count || 0;
                updateSaveBtn();
            },
            error: function() { showToast('Update failed', 'error'); }
        });
    }

    $('#matchesTable tbody').on('click', '.process-text', function() {
        var $span = $(this);
        if ($span.data('editing')) return;
        $span.data('editing', true);
        var rowId = $span.data('row-id');
        var curVal = $span.data('value');
        var html = '<select class="form-select form-select-sm process-select" data-row-id="' + rowId + '" style="font-size:0.75rem;padding:1px 4px;">';
        PROCESS_OPTS.forEach(function(o) {
            html += '<option value="' + o + '"' + (o === curVal ? ' selected' : '') + '>' + o + '</option>';
        });
        html += '</select>';
        var $sel = $(html);
        $span.replaceWith($sel);
        $sel.focus();
        $sel.on('change', function() {
            var newVal = $(this).val();
            saveProcessValue(rowId, newVal);
            var $newSpan = $('<span class="process-text" data-row-id="' + rowId + '" data-value="' + newVal + '" style="font-size:0.75rem;cursor:pointer;" title="Click to change">' + newVal + '</span>');
            $(this).replaceWith($newSpan);
        });
        $sel.on('blur', function() {
            var val = $(this).val();
            var $newSpan = $('<span class="process-text" data-row-id="' + rowId + '" data-value="' + val + '" style="font-size:0.75rem;cursor:pointer;" title="Click to change">' + val + '</span>');
            $(this).replaceWith($newSpan);
        });
    });

    // Memo: click text to open inline input, save on blur/Enter
    $('#matchesTable tbody').on('click', '.memo-text', function() {
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
            $.ajax({
                url: '/api/update', method: 'POST', contentType: 'application/json',
                data: JSON.stringify({ row_id: rowId, field: 'memo', value: newVal }),
                error: function() { showToast('Memo save failed', 'error'); }
            });
            var escaped = newVal.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
            var $newSpan = $('<span class="memo-text" data-row-id="' + rowId + '" style="font-size:0.75rem;cursor:pointer;" title="Click to edit">' + escaped + '</span>');
            $input.replaceWith($newSpan);
        }
        $input.on('blur', saveMemo);
        $input.on('keydown', function(e) {
            if (e.key === 'Enter') { e.preventDefault(); saveMemo(); }
            if (e.key === 'Escape') {
                saved = true;
                var escaped = curVal.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
                var $newSpan = $('<span class="memo-text" data-row-id="' + rowId + '" style="font-size:0.75rem;cursor:pointer;" title="Click to edit">' + escaped + '</span>');
                $input.replaceWith($newSpan);
            }
        });
    });

    // Right-click on Process column header → set all visible rows to chosen option
    $('#matchesTable').on('contextmenu', 'th', function(e) {
        var colName = table ? table.column(this).dataSrc() : '';
        if (colName !== 'how_to_process') return;
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
            var spans = $('#matchesTable tbody .process-text');
            var count = 0;
            spans.each(function() {
                if ($(this).data('value') !== chosen) {
                    $(this).data('value', chosen).text(chosen);
                    saveProcessValue($(this).data('row-id'), chosen);
                    count++;
                }
            });
            showToast('Updated ' + count + ' rows to "' + chosen + '"');
        });
        $(document).one('click', function() { $menu.remove(); });
    });
});

function initTable() {
    table = $('#matchesTable').DataTable({
        processing: true,
        serverSide: true,
        autoWidth: false,
        deferRender: true,
        searchDelay: 400,
        colReorder: {
            fixedColumnsLeft: 1,
            fixedColumnsRight: 1
        },
        ajax: {
            url: '/api/matches',
            data: function(d) {
                d.recommendation = getSelectedRecs().join(',');
                d.ssn_match = $('#ssnFilter').val();
                var minName = $('#minNameScore').val();
                if (minName) d.min_name_score = minName;
                var maxName = $('#maxNameScore').val();
                if (maxName) d.max_name_score = maxName;
                var minAddr = $('#minAddrScore').val();
                if (minAddr) d.min_addr_score = minAddr;
                var maxAddr = $('#maxAddrScore').val();
                if (maxAddr) d.max_addr_score = maxAddr;
            }
        },
        columns: [
            {   // 0: Checkbox
                name: 'select', data: null, orderable: false, className: 'text-center', width: '30px',
                render: function(data) {
                    return `<input type="checkbox" class="row-select" data-row-id="${data._row_id}">`;
                }
            },
            { name: 'uid', data: 'id', visible: false, width: '60px' },                    // 1: UID (hidden by default)
            { name: 'ssn', data: 'ssn_match', render: ssnBadge, className: 'resizable', width: '42px' },           // 2: SSN
            { name: 'name_score', data: 'name_score', render: scoreBadge, className: 'resizable', width: '42px',
              createdCell: function(td, cellData) {
                  if (cellData !== '' && cellData !== null && cellData < 45) {
                      $(td).attr('title', 'This may be low because name may exist in address field');
                  }
              }
            },  // 2: Name
            { name: 'addr_score', data: 'address_score', render: scoreBadge, className: 'resizable', width: '42px',
              createdCell: function(td, cellData, rowData) {
                  if (cellData !== '' && cellData !== null && cellData > 45 &&
                      rowData.recommendation && rowData.recommendation.toUpperCase().indexOf('NEW ADDRESS') !== -1) {
                      $(td).attr('title', 'May have status of new address since numbers in address may not match');
                  }
              }
            }, // 3: Addr
            { name: 'recommendation', data: 'recommendation', render: recBadge, className: 'rec-col resizable', width: '140px' }, // 4: Rec
            {   // 5: Process
                name: 'how_to_process', data: 'how_to_process', className: 'resizable', width: '100px',
                render: function(data, type, row) {
                    var val = data || '';
                    if (!val) {
                        var rec = (row.recommendation || '').toUpperCase();
                        if (rec.indexOf('NEW BA') !== -1 || rec.indexOf('LIKELY BA MATCH') !== -1) val = 'Add new BA and address';
                        else if (rec.indexOf('EXISTING BA - NEW ADDRESS') !== -1) val = 'Merge BA - add addr';
                        else if (rec.indexOf('EXISTING BA') !== -1) val = 'Merge BA and address';
                    }
                    return '<span class="process-text" data-row-id="' + row._row_id + '" data-value="' + val + '" style="font-size:0.75rem;cursor:pointer;" title="Click to change">' + val + '</span>';
                }
            },
            { name: 'canvas_name', data: 'canvas_name', className: 'resizable', width: '120px', createdCell: function(td, cellData) {
                if (cellData && DO_NOT_USE_RE.test(cellData)) {
                    $(td).addClass('do-not-use-cell');
                }
            }},  // 5: Canvas Name
            { name: 'canvas_addr', data: 'canvas_address', className: 'resizable', width: '120px', createdCell: function(td, cellData) {
                if (cellData && DO_NOT_USE_RE.test(cellData)) {
                    $(td).addClass('do-not-use-cell');
                }
            }},  // 6: Canvas Addr
            {   // 7: Canvas City/St/Zip
                name: 'canvas_csz', data: 'canvas_city', className: 'resizable', width: '120px',
                render: function(data, type, d) {
                    return `${d.canvas_city || ''}, ${d.canvas_state || ''} ${d.canvas_zip || ''}`;
                }
            },
            { name: 'canvas_id', data: 'canvas_id', className: 'resizable', visible: false, width: '95px',            // 8: Canvas ID
              render: function(data, type, d) {
                  var seq = d.canvas_addrseq || '';
                  return seq ? data + '-' + seq : (data || '');
              }
            },
            { name: 'dec_name', data: 'dec_name', className: 'resizable', width: '120px', createdCell: function(td, cellData) {
                if (cellData && DO_NOT_USE_RE.test(cellData)) {
                    $(td).addClass('do-not-use-cell');
                }
            }},  // 9: DEC Name
            { name: 'dec_addr', data: 'dec_address', className: 'resizable', width: '120px', createdCell: function(td, cellData) {
                if (cellData && DO_NOT_USE_RE.test(cellData)) {
                    $(td).addClass('do-not-use-cell');
                }
            }},  // 10: DEC Addr
            {   // 11: DEC City/St/Zip
                name: 'dec_csz', data: 'dec_city', className: 'resizable', width: '120px',
                render: function(data, type, d) {
                    return `${d.dec_city || ''}, ${d.dec_state || ''} ${d.dec_zip || ''}`;
                }
            },
            {   // 12: DEC Code
                name: 'dec_code', data: 'dec_hdrcode', className: 'resizable', visible: false, width: '90px',
                render: function(data, type, d) {
                    var code = data || '';
                    var sub = d.dec_addrsubcode || '';
                    return sub ? code + '-' + sub : code;
                }
            },
            {   // 14: Address Lookup
                name: 'addr_lookup', data: 'dec_address_looked_up', className: 'text-center', width: '50px', visible: false,
                render: function(data) {
                    const checked = (data === 1 || data === '1') ? 'checked' : '';
                    return `<input type="checkbox" ${checked} disabled>`;
                }
            },
            {   // 15: JIB
                name: 'jib', data: 'jib', className: 'text-center', visible: false, width: '35px',
                render: function(data, type, row) {
                    const checked = data ? 'checked' : '';
                    return `<input type="checkbox" class="field-check" data-row-id="${row._row_id}" data-field="jib" ${checked}>`;
                }
            },
            {   // 14: Rev
                name: 'rev', data: 'rev', className: 'text-center', visible: false, width: '35px',
                render: function(data, type, row) {
                    const checked = data ? 'checked' : '';
                    return `<input type="checkbox" class="field-check" data-row-id="${row._row_id}" data-field="rev" ${checked}>`;
                }
            },
            {   // 15: Vendor
                name: 'vendor', data: 'vendor', className: 'text-center', visible: false, width: '50px',
                render: function(data, type, row) {
                    const checked = data ? 'checked' : '';
                    return `<input type="checkbox" class="field-check" data-row-id="${row._row_id}" data-field="vendor" ${checked}>`;
                }
            },
            {   // Memo
                name: 'memo', data: 'memo', className: 'resizable', width: '150px',
                render: function(data, type, row) {
                    var val = data || '';
                    var escaped = val.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
                    return '<span class="memo-text" data-row-id="' + row._row_id + '" style="font-size:0.75rem;cursor:pointer;" title="Click to edit">' + escaped + '</span>';
                }
            },
            {   // Actions
                name: 'actions', data: null, orderable: false, visible: false, width: '70px',
                render: function(data) {
                    return `<button class="btn btn-sm btn-outline-primary py-0 px-1" onclick="editRecord(${data._row_id})" title="Edit"><i class="fas fa-edit"></i></button> <button class="btn btn-sm btn-outline-success py-0 px-1" onclick="quickApprove(${data._row_id})" title="Approve"><i class="fas fa-check"></i></button>`;
                }
            }
        ],
        pageLength: 100,
        lengthMenu: [[100, 500, 1000, 5000, -1], [100, 500, '1,000', '5,000', 'All Records']],
        order: [[2, 'desc']],
        language: {
            processing: '<div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div>',
            lengthMenu: 'Show _MENU_'
        },
        createdRow: function(row, data) {
            // Trust highlight (runs per-row during render — no DOM re-scan)
            const cn = (data.canvas_name || '').toLowerCase();
            const ca = (data.canvas_address || '').toLowerCase();
            const combined = cn + ' ' + ca;
            if (combined.includes('trust') || combined.includes('trst') || combined.includes(' tr ')) {
                $(row).addClass('trust-highlight');
            }
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

    // Column visibility dropdown
    buildColVisDropdown();

    // Column resizing
    enableColumnResize('#matchesTable');
}

function enableColumnResize(tableSelector) {
    const $table = $(tableSelector);
    $table.css('table-layout', 'fixed');

    // Add resize handles to columns whose definition includes class 'resizable'
    // Use DataTables API to get header nodes directly (avoids index mismatch with hidden columns)
    $table.DataTable().columns().every(function() {
        const col = this.settings()[0].aoColumns[this.index()];
        if (col.sClass && col.sClass.indexOf('resizable') !== -1) {
            $(this.header()).append('<div class="col-resize-handle"></div>');
        }
    });

    // Drag logic
    let dragging = false, startX, startW, $dragTh;
    let resizeEndTime = 0;   // timestamp to suppress sort-click after resize

    // Bind directly on each handle so it fires BEFORE ColReorder's th handler
    $table.find('.col-resize-handle').on('mousedown', function(e) {
        e.preventDefault();
        e.stopPropagation();          // stop bubble to th (ColReorder)
        e.stopImmediatePropagation(); // stop any other handlers on this element
        dragging = true;
        $table.DataTable().colReorder.disable();
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
            $table.DataTable().colReorder.enable();
            resizeEndTime = Date.now();
        }
    });

    // Capture-phase listener fires BEFORE DataTables' sort handler
    $table[0].addEventListener('click', function(e) {
        if (Date.now() - resizeEndTime < 300) {
            e.stopImmediatePropagation();
            e.preventDefault();
        }
    }, true);
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
    return `<span class="badge" style="background-color:${color}; font-size:0.65rem; white-space:normal; line-height:1.2;" title="${val}">${val}</span>`;
}

function loadStats() {
    $.get('/api/stats', function(s) {
        $('#totalRecords').text(s.total_records.toLocaleString());
        $('#ssnPerfect').text(s.ssn_perfect_matches.toLocaleString());
        $('#ssnNone').text(s.ssn_no_match.toLocaleString());

        // Recommendation breakdown row (sorted by preferred order)
        let html = '';
        const recs = sortByRecOrder(Object.entries(s.recommendations));
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
    $('.rec-check').prop('checked', false);
    $(`.rec-check[value="${rec}"]`).prop('checked', true);
    updateRecFilterLabel();
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

function openDevNotes() {
    $.get('/api/dev_notes').fail(function(xhr) {
        var msg = xhr.responseJSON ? xhr.responseJSON.error : 'Could not open Dev Notes';
        showToast(msg, 'error');
    });
}

function clearFilters() {
    $('.rec-check').prop('checked', false);
    updateRecFilterLabel();
    $('#ssnFilter').val('');
    $('#minNameScore').val('');
    $('#maxNameScore').val('');
    $('#minAddrScore').val('');
    $('#maxAddrScore').val('');
    applyFilters();
}

function refreshData() {
    showToast('Reloading from database...', 'info');
    $.post('/api/reload', function(data) {
        loadStats();
        table.ajax.reload();
        showToast(data.message, 'success');
    }).fail(function() {
        // Fallback: just reload table from cache
        loadStats();
        table.ajax.reload();
        showToast('Refreshed (from cache)', 'warning');
    });
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
        $('#editCanvasId').text(d.canvas_addrseq ? (d.canvas_id + '-' + d.canvas_addrseq) : (d.canvas_id || ''));
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
        $('#editMemo').val(d.memo || '');

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
        'address_reason': $('#editAddressReason').val(),
        'memo': $('#editMemo').val()
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

function showConfirm(title, message, onConfirm) {
    $('#confirmModalTitle').text(title);
    $('#confirmModalBody').html(message);
    var modal = new bootstrap.Modal(document.getElementById('confirmModal'));
    $('#confirmModalOk').off('click').on('click', function() {
        modal.hide();
        onConfirm();
    });
    modal.show();
}

function quickApprove(rowId) {
    showConfirm('Approve Record', '<i class="fas fa-check-circle text-success fa-2x mb-2"></i><br>Approve this record?', function() {
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
    });
}

function bulkApprove() {
    const n = selectedRows.size;
    if (n === 0) return;
    showConfirm('Approve Selected', '<i class="fas fa-check-circle text-success fa-2x mb-2"></i><br>Approve <strong>' + n + '</strong> selected record' + (n > 1 ? 's' : '') + '?', function() {
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
    const recs = getSelectedRecs();
    let url = '/api/export';
    if (recs.length > 0) url += `?recommendation=${encodeURIComponent(recs.join(','))}`;
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

// Additional connection targets (no backend yet — placeholders for future use)
const EXTRA_DATASOURCES = [
    { id: 'mssql_cloud', name: 'MS SQL Server (Cloud)', type: 'mssql' },
    { id: 'mssql_local', name: 'MS SQL Server (Local)', type: 'mssql' },
    { id: 'oracle_cloud', name: 'Oracle (Cloud)', type: 'oracle' },
    { id: 'oracle_local', name: 'Oracle (Local)', type: 'oracle' }
];

function loadDataSources() {
    $.get('/api/datasources', function(data) {
        const allSources = data.datasources.concat(EXTRA_DATASOURCES);
        const selectors = ['#datasourceSelector', '#targetDatasourceSelector'];
        selectors.forEach(function(sel) {
            const $sel = $(sel);
            $sel.empty();

            allSources.forEach(function(ds) {
                const option = $('<option></option>')
                    .val(ds.id)
                    .text(ds.name)
                    .data('type', ds.type);

                if (ds.id === data.active) {
                    option.prop('selected', true);
                }

                $sel.append(option);
            });
        });
    }).fail(function() {
        $('#datasourceSelector').html('<option value="">Error loading sources</option>');
        $('#targetDatasourceSelector').html('<option value="">Error loading sources</option>');
    });
}

function switchDataSource(sourceId, filePath) {
    if (!confirm('Switch data source? This will reload all data.')) {
        loadDataSources(); // Reset dropdown to current source
        return;
    }

    showToast('Switching data source...', 'info');

    var payload = { source_id: sourceId };
    if (filePath) payload.file_path = filePath;

    $.ajax({
        url: '/api/switch_datasource',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(payload),
        success: function(data) {
            showToast(data.message + ` (${data.records.toLocaleString()} records)`, 'success');

            // Reload page to refresh all data
            setTimeout(function() {
                location.reload();
            }, 1000);
        },
        error: function(xhr) {
            const msg = xhr.responseJSON ? xhr.responseJSON.error : 'Failed to switch data source';
            showToast(msg, 'error');
            loadDataSources(); // Reset dropdown to current source
        }
    });
}

function showToast(msg, type) {
    const colors = { success: '#28a745', error: '#dc3545', warning: '#ffc107', info: '#17a2b8' };
    const bg = colors[type] || colors.info;
    const toast = $(`<div class="toast-msg" style="background:${bg}">${msg}</div>`);
    $('body').append(toast);
    setTimeout(() => toast.fadeOut(300, function() { $(this).remove(); }), 2500);
}

// Toast styles and trust highlight
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
    #matchesTable tbody tr.trust-highlight,
    #matchesTable tbody tr.trust-highlight td {
        background-color: #ffe0b2 !important;
    }
    #matchesTable tbody tr.trust-highlight:hover,
    #matchesTable tbody tr.trust-highlight:hover td {
        background-color: #ffcc80 !important;
    }
    #matchesTable tbody td.do-not-use-cell {
        background-color: #f8d7da !important;
    }
    .rec-multi-dropdown .dropdown-toggle {
        font-size: 0.8rem;
        max-width: 100%;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .rec-filter-menu {
        max-height: 320px;
        overflow-y: auto;
        min-width: 380px;
        font-size: 0.8rem;
    }
    .rec-filter-item {
        padding: 0.15rem 0.6rem;
        cursor: pointer;
    }
    .rec-filter-item:active {
        background-color: inherit;
        color: inherit;
    }
    .col-vis-menu {
        max-height: 400px;
        overflow-y: auto;
        min-width: 200px;
        font-size: 0.8rem;
    }
    .col-vis-item {
        padding: 0.15rem 0.6rem;
        cursor: pointer;
    }
    .col-vis-item:active {
        background-color: inherit;
        color: inherit;
    }
    .dataTables_processing {
        position: fixed !important;
        top: 50% !important;
        left: 50% !important;
        transform: translate(-50%, -50%) !important;
        z-index: 1000;
        background: rgba(255,255,255,0.95) !important;
        padding: 20px 40px !important;
        border-radius: 8px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.25);
        width: auto !important;
        margin: 0 !important;
    }
`).appendTo('head');
