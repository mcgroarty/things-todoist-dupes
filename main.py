#!/usr/bin/env python3
"""
Things-Todoist Duplicate Finder

A utility to identify potential duplicate tasks between Things.app and Todoist
by comparing task names using efficient string similarity matching.

All operations are read-only - no modifications to either platform.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from glob import glob
from typing import List, Optional, Callable

import requests
from rapidfuzz import fuzz, process


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class Task:
    """Unified task representation"""
    id: str
    name: str
    source: str  # "todoist" or "things"


@dataclass
class DuplicateMatch:
    """Represents a potential duplicate between two tasks"""
    todoist_task: Task
    things_task: Task
    confidence: float  # 0.0 to 1.0


# =============================================================================
# Todoist API Client
# =============================================================================

class TodoistClient:
    """Interfaces with Todoist REST API (read-only operations)"""
    
    API_URL = "https://api.todoist.com/rest/v2"
    
    def __init__(self, api_token: str):
        self.api_token = api_token
        self.headers = {
            "Authorization": f"Bearer {api_token}"
        }
    
    def get_open_tasks(self) -> List[Task]:
        """
        Fetch all open (non-completed) tasks from Todoist.
        Single API call to minimize overhead.
        """
        try:
            response = requests.get(
                f"{self.API_URL}/tasks",
                headers=self.headers,
                timeout=30
            )
            response.raise_for_status()
            
            tasks_data = response.json()
            
            # Transform to unified Task model
            # Filter for non-completed tasks (is_completed=False is default in API)
            tasks = [
                Task(
                    id=str(task["id"]),
                    name=task["content"],
                    source="todoist"
                )
                for task in tasks_data
            ]
            
            return tasks
            
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to fetch Todoist tasks: {e}")


# =============================================================================
# Things.app Database Reader
# =============================================================================

class ThingsReader:
    """Reads from Things.app SQLite database (read-only access)"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    def get_open_tasks(self) -> List[Task]:
        """
        Query all open (non-completed, non-trashed) tasks from Things database.
        Single query to minimize overhead.
        Retries if database is locked.
        """
        retry_count = 0
        max_retries = 30  # Will warn after 10
        
        while True:
            try:
                # Open in read-only mode
                conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
                cursor = conn.cursor()
                
                # Query: status=0 means open, trashed=0 means not deleted
                cursor.execute("""
                    SELECT uuid, title 
                    FROM TMTask 
                    WHERE status = 0 AND trashed = 0
                """)
                
                rows = cursor.fetchall()
                conn.close()
                
                # Transform to unified Task model
                tasks = [
                    Task(
                        id=row[0],
                        name=row[1],
                        source="things"
                    )
                    for row in rows
                ]
                
                return tasks
                
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    retry_count += 1
                    
                    if retry_count > 10 and retry_count % 10 == 1:
                        print(f"Warning: Things database still locked after {retry_count} retries...")
                    
                    if retry_count >= max_retries:
                        raise RuntimeError(
                            f"Things database locked after {max_retries} retry attempts. "
                            "Please close Things.app and try again."
                        )
                    
                    time.sleep(1)
                    continue
                else:
                    raise RuntimeError(f"Failed to read Things database: {e}")


# =============================================================================
# Task Matching Engine
# =============================================================================

class TaskMatcher:
    """Performs efficient similarity matching using rapidfuzz"""
    
    def __init__(self, threshold: float = 0.85):
        self.threshold = threshold
    
    def find_duplicates(
        self,
        todoist_tasks: List[Task],
        things_tasks: List[Task],
        progress_callback: Optional[Callable[[int, int, float], None]] = None
    ) -> List[DuplicateMatch]:
        """
        Find potential duplicates between Todoist and Things tasks.
        One-directional matching: For each Todoist task, find best match in Things.
        Returns highest confidence match only, except for exact matches (reports all).
        """
        matches = []
        start_time = time.time()
        last_report_time = start_time
        
        # Pre-normalize Things task names for efficiency
        things_names = [task.name for task in things_tasks]
        
        for i, todoist_task in enumerate(todoist_tasks):
            current_time = time.time()
            
            # Progress reporting (time-based, every ~5 seconds)
            if progress_callback and (current_time - last_report_time >= 5.0):
                elapsed = current_time - start_time
                tasks_processed = i + 1
                tasks_remaining = len(todoist_tasks) - tasks_processed
                
                if tasks_processed > 0:
                    eta = (elapsed / tasks_processed) * tasks_remaining
                    progress_callback(tasks_processed, len(todoist_tasks), eta)
                    last_report_time = current_time
            
            # Find best matches using rapidfuzz
            # fuzz.ratio returns 0-100, we normalize to 0.0-1.0
            results = process.extract(
                todoist_task.name,
                things_names,
                scorer=fuzz.ratio,
                limit=None  # Get all results
            )
            
            # Filter by threshold and process results
            exact_matches = []
            best_match = None
            best_confidence = 0.0
            
            for things_name, score, idx in results:
                confidence = score / 100.0  # Normalize to 0.0-1.0
                
                if confidence >= self.threshold:
                    things_task = things_tasks[idx]
                    match = DuplicateMatch(
                        todoist_task=todoist_task,
                        things_task=things_task,
                        confidence=confidence
                    )
                    
                    # Track exact matches separately
                    if confidence == 1.0:
                        exact_matches.append(match)
                    # Track best non-exact match
                    elif confidence > best_confidence:
                        best_match = match
                        best_confidence = confidence
            
            # Add results: all exact matches, or best match if no exact matches
            if exact_matches:
                matches.extend(exact_matches)
            elif best_match:
                matches.append(best_match)
        
        # Sort by confidence (highest first)
        matches.sort(key=lambda m: m.confidence, reverse=True)
        
        return matches


# =============================================================================
# Duplicate Report Generator
# =============================================================================

class DuplicateReport:
    """Generates plain text, human-readable console output"""
    
    def __init__(self, matches: List[DuplicateMatch]):
        self.matches = matches
    
    def to_console(self) -> str:
        """Generate formatted console output"""
        if not self.matches:
            return "No potential duplicates found."
        
        lines = [f"POTENTIAL DUPLICATES FOUND: {len(self.matches)}\n"]
        
        for i, match in enumerate(self.matches, 1):
            confidence_pct = match.confidence * 100
            lines.append(f"Match {i} (Confidence: {confidence_pct:.1f}%)")
            lines.append(f'  Todoist: "{match.todoist_task.name}"')
            lines.append(f'  Things:  "{match.things_task.name}"')
            lines.append("")
        
        return "\n".join(lines)


# =============================================================================
# Configuration
# =============================================================================

def load_api_key() -> str:
    """Load Todoist API key from ~/.api_keys.json"""
    api_keys_path = os.path.expanduser("~/.api_keys.json")
    
    if not os.path.exists(api_keys_path):
        raise FileNotFoundError(
            f"API key file not found: {api_keys_path}\n"
            f"Please create this file with format:\n"
            f'{{"TODOIST_API_KEY": "your-api-token-here"}}'
        )
    
    try:
        with open(api_keys_path, 'r') as f:
            keys = json.load(f)
        return keys["TODOIST_API_KEY"]
    except (json.JSONDecodeError, KeyError) as e:
        raise ValueError(
            f"Invalid API key file format. Expected JSON with 'TODOIST_API_KEY' key: {e}"
        )


def get_things_db_path() -> str:
    """
    Find Things database path using glob pattern.
    Error if multiple databases found (ambiguous) or none found.
    """
    pattern = os.path.expanduser(
        "~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/"
        "ThingsData-*/Things Database.thingsdatabase/main.sqlite"
    )
    
    matches = glob(pattern)
    
    if len(matches) == 0:
        raise FileNotFoundError(
            "Things database not found. Is Things.app installed?"
        )
    elif len(matches) > 1:
        raise RuntimeError(
            f"Multiple Things databases found (ambiguous):\n" +
            "\n".join(f"  - {m}" for m in matches)
        )
    
    return matches[0]


# =============================================================================
# Main Program
# =============================================================================

def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description='Find potential duplicate tasks between Things.app and Todoist',
        epilog='All operations are read-only. No modifications will be made to either platform.',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '-t', '--threshold',
        type=float,
        default=0.85,
        metavar='FLOAT',
        help='similarity threshold for matching (0.0-1.0, default: 0.85)'
    )
    
    parser.add_argument(
        '-p', '--progress',
        action='store_true',
        help='show progress updates during matching'
    )
    
    parser.add_argument(
        '-v', '--version',
        action='version',
        version='%(prog)s 1.0.0'
    )
    
    args = parser.parse_args()
    
    # Validate threshold
    if not 0.0 <= args.threshold <= 1.0:
        parser.error('threshold must be between 0.0 and 1.0')
    
    return args


def main():
    """Main program flow"""
    # Parse command-line arguments
    args = parse_args()
    
    print("Things-Todoist Duplicate Finder")
    print("=" * 50)
    print()
    
    try:
        # 1. Initialize clients
        print("Initializing...")
        api_token = load_api_key()
        todoist = TodoistClient(api_token=api_token)
        
        db_path = get_things_db_path()
        things = ThingsReader(db_path=db_path)
        
        # 2. Load all tasks into memory (one-time operation)
        print("Loading Todoist tasks...")
        todoist_tasks = todoist.get_open_tasks()
        print(f"  Found {len(todoist_tasks)} open tasks in Todoist")
        
        print("Loading Things tasks...")
        things_tasks = things.get_open_tasks()
        print(f"  Found {len(things_tasks)} open tasks in Things")
        print()
        
        # 3. Find duplicates with optional progress reporting
        print(f"Comparing {len(todoist_tasks)} × {len(things_tasks)} tasks...")
        print(f"Similarity threshold: {args.threshold * 100:.0f}%")
        print()
        
        matcher = TaskMatcher(threshold=args.threshold)
        
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
        
        print()
        
        # 4. Generate report
        report = DuplicateReport(matches)
        print(report.to_console())
        
    except (FileNotFoundError, RuntimeError, ValueError) as e:
        print(f"Error: {e}")
        return 1
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        return 130
    except Exception as e:
        print(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
