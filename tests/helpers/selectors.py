"""Centralized CSS selectors for all UI elements."""

# -- Navigation bar --
NAVBAR = "nav.navbar"
DATASOURCE_SELECTOR = "#datasourceSelector"
TARGET_DATASOURCE_SELECTOR = "#targetDatasourceSelector"
REFRESH_BTN = "button:has-text('Refresh')"
DEV_NOTES_BTN = "button:has-text('Dev Notes')"
HELP_BTN = "button[data-bs-target='#helpModal']"

# -- Recommendation breakdown cards --
REC_BREAKDOWN = "#recBreakdown"
REC_CARD = "#recBreakdown .col"

# -- Filter controls --
REC_FILTER_BTN = "#recFilterBtn"
REC_CHECKBOX = ".rec-check"
SSN_FILTER = "#ssnFilter"
MIN_NAME_SCORE = "#minNameScore"
MAX_NAME_SCORE = "#maxNameScore"
MIN_ADDR_SCORE = "#minAddrScore"
MAX_ADDR_SCORE = "#maxAddrScore"
CLEAR_FILTERS_BTN = "button:has-text('Clear')"

# -- AG Grid --
GRID = "#matchesGrid"
GRID_ROW = "#matchesGrid .ag-row"
GRID_CELL = "#matchesGrid .ag-cell"
GRID_HEADER = "#matchesGrid .ag-header-cell"
TABLE_SECTION = "#tableSection"
SELECT_ALL_CHECKBOX = ".ag-header-select-all"
ROW_CHECKBOX = ".ag-selection-checkbox"
FIELD_CHECKBOX = ".field-check"

# -- Grid controls --
PAGE_SIZE_SELECT = "#pageSizeSelect"
QUICK_FILTER_INPUT = "#quickFilterInput"
GRID_INFO = "#gridInfo"

# -- Column visibility --
COL_VIS_CONTAINER = "#colVisContainer"
COL_VIS_CHECK = ".col-vis-check"

# -- Selection & bulk actions --
SELECTION_INFO = "#selectionInfo"
BULK_APPROVE_BTN = "#bulkApproveBtn"
EXPORT_SELECTED_BTN = "button[title='Download selected as CSV']"
SAVE_CHANGES_BTN = "#saveChangesBtn"
SAVE_COUNT_BADGE = "#saveChangesBtn .save-count"

# -- Import --
IMPORT_TYPE_SELECT = "#importType"
IMPORT_FILE_INPUT = "#importFile"

# -- Edit modal --
EDIT_MODAL = "#editModal"
EDIT_ROW_ID = "#editRowId"
EDIT_CANVAS_NAME = "#editCanvasName"
EDIT_CANVAS_ADDRESS = "#editCanvasAddress"
EDIT_DEC_NAME = "#editDecName"
EDIT_DEC_ADDRESS = "#editDecAddress"
EDIT_DEC_CITY = "#editDecCity"
EDIT_DEC_STATE = "#editDecState"
EDIT_DEC_ZIP = "#editDecZip"
EDIT_DEC_CONTACT = "#editDecContact"
EDIT_DEC_HDRCODE = "#editDecHdrcode"
EDIT_RECOMMENDATION = "#editRecommendation"
EDIT_ADDRESS_REASON = "#editAddressReason"
EDIT_SSN_MATCH = "#editSsnMatch"
EDIT_NAME_SCORE = "#editNameScore"
EDIT_ADDRESS_SCORE = "#editAddressScore"
EDIT_SAVE_BTN = "#editModal .btn-primary"

# -- Confirm modal --
CONFIRM_MODAL = "#confirmModal"
CONFIRM_OK_BTN = "#confirmModalOk"

# -- Help modal --
HELP_MODAL = "#helpModal"
HELP_ACCORDION = "#helpAccordion"

# -- Visual indicators --
TRUST_HIGHLIGHT = ".ag-row.trust-highlight"
DO_NOT_USE_CELL = ".ag-cell.do-not-use-cell"
CELL_SELECTED = ".cell-selected"
ROW_SELECTED = ".ag-row.row-selected"

# -- Search & Replace modal --
SR_MODAL = "#searchReplaceModal"
SR_SEARCH_INPUT = "#srSearch"
SR_REPLACE_INPUT = "#srReplace"
SR_COLUMN_SELECT = "#srColumn"
SR_CASE_SENSITIVE = "#srCaseSensitive"
SR_MATCH_INFO = "#srMatchInfo"
SR_FIND_NEXT_BTN = "#searchReplaceModal button:has-text('Find Next')"
SR_REPLACE_BTN = "#searchReplaceModal button:has-text('Replace'):not(:has-text('All'))"
SR_REPLACE_ALL_BTN = "#searchReplaceModal button:has-text('Replace All')"
SR_OPEN_BTN = "button:has-text('Search')"
SR_HIGHLIGHT = ".sr-highlight"
SR_MATCH_TEXT = ".sr-match-text"

# -- Undo / Redo --
UNDO_BTN = "#undoBtn"
REDO_BTN = "#redoBtn"

# -- Inline editing --
MEMO_TEXT = ".memo-text"
PROCESS_CELL = ".ag-cell[col-id='how_to_process']"
PROCESS_CTX_MENU = ".process-ctx-menu"
PROCESS_CTX_ITEM = ".process-ctx-item"

# -- Confirm modal (extended) --
CONFIRM_TITLE = "#confirmModalTitle"
CONFIRM_BODY = "#confirmModalBody"
CONFIRM_CANCEL_BTN = "#confirmModal .btn-secondary"

# -- Toast notifications --
TOAST = ".toast-msg"
