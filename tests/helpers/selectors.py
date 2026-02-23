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

# -- Table --
TABLE = "#matchesTable"
TABLE_BODY = "#matchesTable tbody"
TABLE_ROWS = "#matchesTable tbody tr"
TABLE_HEADER = "#matchesTable thead th"
TABLE_SECTION = "#tableSection"
SELECT_ALL_CHECKBOX = "#selectAll"
ROW_CHECKBOX = ".row-select"
FIELD_CHECKBOX = ".field-check"

# -- DataTable controls (relocated into header) --
DT_LENGTH_PLACEHOLDER = "#dtLengthPlaceholder"
DT_SEARCH_PLACEHOLDER = "#dtSearchPlaceholder"
DT_INFO = "#matchesTable_info"
DT_NEXT_BTN = "#matchesTable_next"
DT_PREV_BTN = "#matchesTable_previous"

# -- Column visibility --
COL_VIS_CONTAINER = "#colVisContainer"
COL_VIS_CHECK = ".col-vis-check"

# -- Selection & bulk actions --
SELECTION_INFO = "#selectionInfo"
BULK_APPROVE_BTN = "#bulkApproveBtn"
EXPORT_SELECTED_BTN = "button[title='Download selected']"
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
TRUST_HIGHLIGHT = "tr.trust-highlight"
DO_NOT_USE_CELL = "td.do-not-use-cell"
CELL_SELECTED = ".cell-selected"
ROW_SELECTED = "tr.row-selected"

# -- Resize handle --
RESIZE_HANDLE = ".col-resize-handle"

# -- Toast notifications --
TOAST = ".toast-msg"
