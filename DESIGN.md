# Things-Todoist Duplicate Finder - Design Document

## Overview
A Python utility to identify potential duplicate tasks between Things.app and Todoist by comparing task names using efficient string similarity matching.

**Scope**: Only open (incomplete) tasks are analyzed. Completed tasks are excluded from both sources.

**Things.app Filtering**: Trashed/deleted tasks are explicitly excluded from analysis.

**Read-Only Operation**: This tool performs no modifications to either Todoist or Things.app. All operations are strictly read-only, producing only a duplicate report.

## Architecture

### Components

#### 1. Data Sources
- **TodoistClient**: Interfaces with Todoist REST API (read-only)
- **ThingsReader**: Reads from Things.app SQLite database (read-only)

#### 2. Core Processing
- **TaskMatcher**: Performs efficient similarity matching
- **DuplicateReport**: Structures and formats the results

#### 3. Data Models
- **Task**: Unified task representation
  - `id`: str
  - `name`: str
  - `source`: str ("todoist" or "things")

- **DuplicateMatch**: Represents a potential duplicate
  - `todoist_task`: Task
  - `things_task`: Task
  - `confidence`: float (0.0 to 1.0)

## Data Flow

```
1. TodoistClient → Load all open tasks (excludes completed) → List[Task]
2. ThingsReader → Load all open tasks (excludes completed & trashed) → List[Task]
3. TaskMatcher → Compare all pairs → List[DuplicateMatch]
4. DuplicateReport → Format results → Output
```

## Implementation Details

### 1. Todoist API Integration

```python
class TodoistClient:
    def __init__(self, api_token: str)
    def get_open_tasks(self) -> List[Task]
```

- Use Todoist REST API v2 (read-only operations)
- Filter for active (non-completed) tasks only
- Completed tasks are explicitly excluded
- Single API call to fetch all tasks
- Transform to unified Task model
- **No write operations**: Never creates, updates, or deletes tasks

### 2. Things.app Database Access

```python
class ThingsReader:
    def __init__(self, db_path: str)
    def get_open_tasks(self) -> List[Task]
```

- Default location: `~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/ThingsData-*/Things Database.thingsdatabase/main.sqlite`
  - Use glob pattern to resolve wildcard
  - **Error if multiple directories match** (ambiguous database location)
  - Error if no directories match (Things not installed or no data)
- Query: `SELECT uuid, title FROM TMTask WHERE status = 0 AND trashed = 0`
  - `status = 0`: Open tasks only (excludes completed)
  - `trashed = 0`: **Excludes trashed/deleted tasks** (tasks in Things trash are ignored)
- Single query to load all open tasks
- Transform to unified Task model
- **Read-only access**: Opens database in read-only mode, never modifies data
- **Database locked handling**: Retry with 1-second delay, warn after 10 retry attempts

### 3. Efficient String Matching

```python
class TaskMatcher:
    def __init__(self, threshold: float = 0.85)
    def find_duplicates(
        self, 
        todoist_tasks: List[Task], 
        things_tasks: List[Task],
        progress_callback: Optional[Callable] = None
    ) -> List[DuplicateMatch]
```

**Algorithm**: Use `rapidfuzz` library for performance

**Strategy**:
1. **Normalization**: Convert all task names to lowercase and strip whitespace
2. **Indexing**: Use `rapidfuzz.process.extract()` with preprocessing
3. **Comparison**: For each Todoist task, find best matches in Things tasks
   - **One-directional matching**: Only search Todoist→Things (not bidirectional)
   - Sufficient to identify tasks existing in both systems
4. **Filtering**: Only return matches above confidence threshold
   - **Multiple matches**: Report highest confidence match only
   - **Exception**: Report all exact matches (100% confidence after normalization)
5. **Progress Tracking**: Report progress every ~5 seconds (time-based) with percentage and ETA

**Progress Reporting** (Optional, via `--progress` flag):
- **Disabled by default** to reduce output clutter
- Enable with `--progress` command-line flag
- Track: current task index, total tasks, start time, last report time
- Report interval: Every 5 seconds (time-based check)
- Display: percentage complete, estimated time remaining
- Format: `"Progress: 45% (450/1000 tasks) - ETA: 6s"`
- Calculate ETA based on: `(elapsed_time / tasks_processed) * tasks_remaining`
- Implementation: Check `time.time()` to determine if 5 seconds elapsed since last report

**Complexity**: O(n*m) with optimizations from rapidfuzz's C++ implementation
- n = number of Todoist tasks
- m = number of Things tasks
- Typical performance: ~10,000 comparisons per second

**Similarity Metric**: Levenshtein ratio (normalized edit distance)
- Returns 0.0 (no match) to 1.0 (exact match)
- Handles typos, extra words, and minor variations
- **Exact matches after normalization** (e.g., "Buy Milk" vs "buy milk") = 100% confidence
- **No special handling** for short task names (all names processed equally)

### 4. Duplicate Report

```python
class DuplicateReport:
    def __init__(self, matches: List[DuplicateMatch])
    def to_console(self) -> str
```

**Output Format**: Plain text, human-readable console output

**Sorting**: Results sorted by confidence (highest first)

**Console Output Format**:
```
POTENTIAL DUPLICATES FOUND: 5

Match 1 (Confidence: 95.2%)
  Todoist: "Buy groceries for dinner"
  Things:  "Buy groceries for dinner party"

Match 2 (Confidence: 87.3%)
  ...
```



## Main Program Flow

```python
def main():
    # 1. Parse command-line arguments
    args = parse_args()  # Returns threshold and progress flag
    
    # 2. Initialize clients
    todoist = TodoistClient(api_token=get_api_token())
    things = ThingsReader(db_path=get_things_db_path())
    
    # 3. Load all tasks into memory (one-time operation)
    print("Loading Todoist tasks...")
    todoist_tasks = todoist.get_open_tasks()
    
    print("Loading Things tasks...")
    things_tasks = things.get_open_tasks()
    
    # 4. Find duplicates with optional progress reporting
    print(f"Comparing {len(todoist_tasks)} × {len(things_tasks)} tasks...")
    matcher = TaskMatcher(threshold=args.threshold)
    
    # Progress callback only if --progress flag is set
    progress_callback = None
    if args.progress:
        def progress_callback(current: int, total: int, eta_seconds: float):
            percent = (current / total) * 100
            print(f"Progress: {percent:.1f}% ({current}/{total} tasks) - ETA: {eta_seconds:.0f}s")
    
    matches = matcher.find_duplicates(
        todoist_tasks, 
        things_tasks,
        progress_callback=progress_callback
    )
    
    # 4. Generate report
    report = DuplicateReport(matches)
    print(report.to_console())
```

## Configuration

### Command-Line Options

Program configuration via command-line arguments:

```bash
python main.py [-h] [-t FLOAT] [-p] [-v]
```

**Options:**
- `-h, --help`: Show help message and exit
- `-t FLOAT, --threshold FLOAT`: Similarity threshold (0.0-1.0, default: 0.85)
- `-p, --progress`: Show progress updates during matching (disabled by default)
- `-v, --version`: Show program version and exit

**Examples:**
```bash
# Default settings (85% threshold, no progress)
python main.py

# Stricter matching with progress
python main.py --threshold 0.95 --progress

# More lenient matching
python main.py -t 0.75
```

### Implementation

```python
def parse_args():
    parser = argparse.ArgumentParser(
        description='Find potential duplicate tasks between Things.app and Todoist'
    )
    parser.add_argument('-t', '--threshold', type=float, default=0.85)
    parser.add_argument('-p', '--progress', action='store_true')
    parser.add_argument('-v', '--version', action='version', version='1.0.0')
    return parser.parse_args()
```

### API Key Configuration

```python
def load_api_key() -> str:
    """Load Todoist API key from ~/.api_keys.json"""
    api_keys_path = os.path.expanduser("~/.api_keys.json")
    with open(api_keys_path, 'r') as f:
        keys = json.load(f)
    return keys["TODOIST_API_KEY"]
```

**API Key File Format** (`~/.api_keys.json`):
```json
{
  "TODOIST_API_KEY": "your-api-token-here"
}
```

### Database Path Resolution

```python
THINGS_DB_PATH = os.path.expanduser(
    "~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/"
    "ThingsData-*/Things Database.thingsdatabase/main.sqlite"
)
```

## Dependencies

```
rapidfuzz>=3.0.0      # Fast string matching
requests>=2.31.0      # Todoist API calls
```

**Standard Library:**
- `argparse` - Command-line argument parsing
- `json` - API key configuration
- `sqlite3` - Things.app database access
- `time` - Progress tracking and timing
- `glob` - Database path resolution

## Performance Considerations

1. **Memory Usage**: All tasks loaded in memory
   - Typical: 1000 tasks × 50 bytes ≈ 50KB
   - Acceptable for datasets up to 100,000 tasks

2. **Time Complexity**:
   - API calls: O(1) - single request
   - Database query: O(1) - single query
   - Matching: O(n×m) - optimized by rapidfuzz
   - Typical runtime for 1000×1000 tasks: ~2-5 seconds

3. **Optimizations**:
   - Pre-normalize all strings before comparison
   - Use rapidfuzz's scoring_function for faster results
   - Sort results by confidence (highest first)

## Error Handling

- **Todoist API**: Handle rate limits (450 requests/15 min), network errors
- **Things DB**: 
  - Check file existence with glob pattern
  - Error if multiple database directories found
  - Retry locked database with 1-second delay
  - Print warning if retry count exceeds 10
- **Matching**: Validate input data, handle edge cases (empty names)

## Future Enhancements

- Support for additional metadata (due dates, tags, projects) in matching
- Progress bar for large datasets (instead of text updates)
- Caching of results between runs
- Additional output formats (JSON, CSV, HTML, Markdown)

**Note**: Automatic deduplication and task modification features are intentionally excluded to maintain read-only operation guarantee.
