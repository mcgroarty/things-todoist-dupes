# Things-Todoist Duplicate Finder

A Python utility to identify potential duplicate tasks between Things.app and Todoist by comparing task names using efficient string similarity matching.

## Features

- **Read-only operations**: Never modifies tasks in either system
- **Efficient matching**: Uses rapidfuzz for fast string similarity comparison
- **Progress reporting**: Shows real-time progress with ETA
- **Smart matching**: Reports highest confidence matches, all exact matches
- **Configurable threshold**: Adjust similarity sensitivity

## Requirements

- Python 3.7+
- macOS (for Things.app access)
- Active Todoist account
- Things.app installed

## Installation

1. Clone this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create API key file at `~/.api_keys.json`:
   ```json
   {
     "TODOIST_API_KEY": "your-api-token-here"
   }
   ```

   Get your Todoist API token from: https://todoist.com/prefs/integrations

## Usage

Run the program:

```bash
python main.py
```

### Command-Line Options

```bash
python main.py [-h] [-t FLOAT] [-p] [-v]
```

**Options:**
- `-h, --help` - Show help message and exit
- `-t FLOAT, --threshold FLOAT` - Similarity threshold for matching (0.0-1.0, default: 0.85)
- `-p, --progress` - Show progress updates during matching (disabled by default)
- `-v, --version` - Show program version and exit

**Examples:**

```bash
# Use default settings (85% threshold, no progress)
python main.py

# Use stricter matching (95% threshold)
python main.py --threshold 0.95

# Show progress updates
python main.py --progress

# Combine options: 90% threshold with progress
python main.py -t 0.90 -p
```

### What the program does:

The program will:
1. Load all open tasks from Todoist
2. Load all open tasks from Things.app
3. Compare tasks and identify potential duplicates
4. Display a report of matches with confidence scores

### Example Output

```
Things-Todoist Duplicate Finder
==================================================

Initializing...
Loading Todoist tasks...
  Found 450 open tasks in Todoist
Loading Things tasks...
  Found 380 open tasks in Things

Comparing 450 × 380 tasks...
Similarity threshold: 85%

POTENTIAL DUPLICATES FOUND: 12

Match 1 (Confidence: 100.0%)
  Todoist: "Buy groceries"
  Things:  "Buy groceries"

Match 2 (Confidence: 95.2%)
  Todoist: "Buy groceries for dinner"
  Things:  "Buy groceries for dinner party"

...
```

## Configuration

Adjust matching sensitivity using the `--threshold` option:

```bash
# More strict (fewer matches, higher confidence required)
python main.py --threshold 0.95

# More lenient (more matches, lower confidence accepted)  
python main.py --threshold 0.75
```

**Threshold guidelines:**
- `0.95-1.0`: Very strict, mostly exact matches
- `0.85-0.95`: Balanced (default: 0.85)
- `0.70-0.85`: More lenient, may include false positives

Enable progress reporting for large datasets:

```bash
python main.py --progress
```

## How It Works

1. **Data Loading**: Fetches all open tasks from both platforms in a single operation
2. **Normalization**: Task names are normalized (lowercase, trimmed) for comparison
3. **Matching**: Uses Levenshtein ratio to compute similarity scores
4. **Filtering**: Only reports matches above the confidence threshold
5. **Reporting**: Displays results sorted by confidence (highest first)

## Limitations

- Only compares task names (no metadata like due dates, tags, etc.)
- One-directional matching (Todoist → Things)
- Completed tasks are excluded from analysis

## Documentation

See [DESIGN.md](DESIGN.md) for detailed design documentation.

## License

See [LICENSE](LICENSE) file.
