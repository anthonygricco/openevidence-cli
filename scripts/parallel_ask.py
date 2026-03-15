#!/usr/bin/env python3
"""
Run multiple OpenEvidence queries in parallel.

Usage:
    python3 parallel_ask.py "question 1" "question 2" "question 3"
    python3 parallel_ask.py --file questions.txt
    
Output: JSON array of results, printed as each completes.
Each result is delimited by [RESULT N/total] markers for easy parsing.
"""

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
RUN_SCRIPT = SCRIPT_DIR / "run.py"
ASK_SCRIPT = "ask_question.py"


def run_single_query(args: tuple) -> dict:
    """Run a single OE query in a subprocess. Returns result dict."""
    idx, question, extra_flags = args
    start = time.time()
    
    cmd = [
        sys.executable, str(RUN_SCRIPT), ASK_SCRIPT,
        "--question", question,
        "--reliable",
        "--format", "json",
    ] + extra_flags
    
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min hard timeout per query
            cwd=str(SCRIPT_DIR.parent),
        )
        
        elapsed = time.time() - start
        
        # Try to parse JSON from stdout
        stdout = proc.stdout.strip()
        
        # The JSON output might be mixed with status lines — find the JSON block
        json_result = None
        for line in stdout.split('\n'):
            line = line.strip()
            if line.startswith('{'):
                try:
                    json_result = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        
        if json_result:
            json_result['_index'] = idx
            json_result['_elapsed'] = round(elapsed, 1)
            return json_result
        
        # Fallback: extract text between the delimiter markers
        if "OPENEVIDENCE RESPONSE" in stdout:
            # Extract between the markers
            lines = stdout.split('\n')
            capture = False
            answer_lines = []
            for line in lines:
                if "OPENEVIDENCE RESPONSE" in line:
                    capture = True
                    continue
                if capture and line.startswith('=' * 20):
                    continue
                if capture and line.startswith('-' * 20):
                    # End of response
                    break
                if capture:
                    answer_lines.append(line)
            
            answer = '\n'.join(answer_lines).strip()
            return {
                '_index': idx,
                '_elapsed': round(elapsed, 1),
                'question': question,
                'answer': answer,
                'chars': len(answer),
            }
        
        return {
            '_index': idx,
            '_elapsed': round(elapsed, 1),
            'question': question,
            'answer': None,
            'error': f"No parseable output. stderr: {proc.stderr[:500]}",
        }
        
    except subprocess.TimeoutExpired:
        return {
            '_index': idx,
            '_elapsed': 300,
            'question': question,
            'answer': None,
            'error': "Query timed out after 300s",
        }
    except Exception as e:
        return {
            '_index': idx,
            '_elapsed': time.time() - start,
            'question': question,
            'answer': None,
            'error': str(e),
        }


def main():
    parser = argparse.ArgumentParser(description="Run multiple OE queries in parallel")
    parser.add_argument("questions", nargs="*", help="Questions to ask")
    parser.add_argument("--file", "-f", help="File with one question per line")
    parser.add_argument("--max-parallel", "-p", type=int, default=3,
                        help="Max parallel queries (default: 3)")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--show-browser", action="store_true")
    
    args = parser.parse_args()
    
    questions = list(args.questions)
    if args.file:
        with open(args.file) as f:
            questions.extend(line.strip() for line in f if line.strip())
    
    if not questions:
        print("No questions provided.", file=sys.stderr)
        sys.exit(1)
    
    extra_flags = []
    if args.debug:
        extra_flags.append("--debug")
    if args.show_browser:
        extra_flags.append("--show-browser")
    
    n = len(questions)
    max_workers = min(args.max_parallel, n)
    print(f"Running {n} queries with up to {max_workers} in parallel...\n", file=sys.stderr)
    
    tasks = [(i, q, extra_flags) for i, q in enumerate(questions)]
    results = [None] * n
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(run_single_query, t): t[0] for t in tasks}
        
        completed = 0
        for future in as_completed(future_map):
            completed += 1
            result = future.result()
            idx = result['_index']
            results[idx] = result
            
            q = questions[idx]
            elapsed = result.get('_elapsed', '?')
            chars = result.get('chars', len(result.get('answer', '') or ''))
            status = f"{chars} chars" if result.get('answer') else f"FAILED: {result.get('error', 'unknown')}"
            
            # Print delimiter for each completed result
            print(f"\n[RESULT {idx + 1}/{n}] ({elapsed}s) {status}", file=sys.stderr)
            print(f"Q: {q[:80]}{'...' if len(q) > 80 else ''}", file=sys.stderr)
            
            # Print the actual answer to stdout for piping
            if result.get('answer'):
                print(f"\n{'=' * 60}")
                print(f"QUERY {idx + 1}: {q}")
                print(f"{'=' * 60}")
                print(result['answer'])
                print(f"({'=' * 60})")
                sys.stdout.flush()
    
    # Summary
    succeeded = sum(1 for r in results if r and r.get('answer'))
    total_time = max(r.get('_elapsed', 0) for r in results if r)
    print(f"\n{'=' * 60}", file=sys.stderr)
    print(f"DONE: {succeeded}/{n} queries succeeded in {total_time:.1f}s wall-clock", file=sys.stderr)


if __name__ == "__main__":
    main()
