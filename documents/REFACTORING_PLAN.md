# SentCom Refactoring Plan

## Overview
This document outlines the planned refactoring tasks to improve code maintainability and organization.

## Current State (March 18, 2026)

### Large Files Identified
| File | Lines | Status | Priority |
|------|-------|--------|----------|
| `/app/backend/routers/ib.py` | 5,230 | Needs splitting | P2 |
| `/app/backend/server.py` | 4,772 | Needs splitting | P2 |
| `/app/frontend/src/components/SentCom.jsx` | 3,717 | Needs refactoring | P3 |
| `/app/frontend/src/components/NIA.jsx` | 3,370 | Needs refactoring | P3 |

### Completed Cleanup
- [x] Removed 38 `console.log` statements from frontend code (March 18, 2026)
- [x] Fixed import errors (`get_timeseries_service` → `get_timeseries_ai`)
- [x] Fixed method name mismatches (`analyze_symbol` → `analyze_sentiment`, etc.)

## Proposed Refactoring

### 1. Backend Router Refactoring (`routers/ib.py`)

**Goal**: Split the 5,230-line file into focused, domain-specific routers.

**Proposed Structure**:
```
/app/backend/routers/
├── ib/
│   ├── __init__.py           # Combine all sub-routers
│   ├── connection.py         # Status, connect, disconnect, push-data (~300 lines)
│   ├── account.py            # Account summary, positions (~200 lines)
│   ├── orders.py             # Order placement, queue management (~500 lines)
│   ├── historical_data.py    # Historical data collection endpoints (~700 lines)
│   ├── scanner.py            # All scanner endpoints (~1500 lines)
│   ├── news.py               # News endpoints (~200 lines)
│   ├── analysis.py           # Analysis and SR analysis (~600 lines)
│   ├── alerts.py             # Price alerts and enhanced alerts (~400 lines)
│   └── collection_mode.py    # Collection mode endpoints (~300 lines)
```

**Benefits**:
- Smaller, focused files (200-700 lines each)
- Easier to test individual domains
- Better code organization
- Clearer ownership of functionality

### 2. Backend Server Refactoring (`server.py`)

**Goal**: Extract service initialization and configuration.

**Proposed Changes**:
- Extract service initialization to `/app/backend/core/services.py`
- Extract middleware configuration to `/app/backend/core/middleware.py`
- Extract background task definitions to `/app/backend/core/tasks.py`
- Keep `server.py` as the main FastAPI app definition (~500 lines)

### 3. Frontend Component Refactoring

**SentCom.jsx (3,717 lines)**:
- Extract `AIInsightsDashboard` to separate file
- Extract `ConversationPanel` to separate file
- Extract `SettingsPanel` to separate file
- Extract custom hooks to `/app/frontend/src/hooks/useSentCom.js`

**NIA.jsx (3,370 lines)**:
- Extract `DataCoveragePanel` to separate file
- Extract `TrainingPanel` to separate file
- Extract `CollectionModePanel` to separate file

## Implementation Priority

1. **P0 - Critical** (In progress)
   - Fix any blocking bugs
   - Complete deployment verification

2. **P1 - High** (Next sprint)
   - Extract scanner endpoints from `ib.py`
   - Extract historical data endpoints from `ib.py`

3. **P2 - Medium** (Future sprint)
   - Complete backend router refactoring
   - Server.py refactoring

4. **P3 - Low** (Backlog)
   - Frontend component refactoring
   - Additional code cleanup

## Notes
- All refactoring should maintain backward compatibility with existing API contracts
- Tests should be written/updated for each extracted module
- Hot reload should continue to work during development
