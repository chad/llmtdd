import os
import time
import sys
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import anthropic
import subprocess

class TestWatcher(FileSystemEventHandler):
    def __init__(self, project_root: Path):
        self.test_dir = project_root / 'tests'
        self.src_dir = project_root / 'src'
        self.claude = anthropic.Anthropic(api_key=os.environ["CLAUDE_KEY"])
        
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.test.ts'):
            print(event)
            time.sleep(1)  # Wait for file writes to complete
            self.process_test_file(Path(event.src_path))
            
    def process_test_file(self, test_path: Path):
        with open(test_path) as f:
            test_content = f.read()
            
        src_path = self.src_dir / test_path.name.replace('.test.ts', '.ts')
        
        success = False
        attempts = 0
        max_attempts = 5
        
        while not success and attempts < max_attempts:
            prompt = f"""Given these TypeScript tests, generate production code that will make them pass:
{test_content}
Respond only with the TypeScript code that should go in the source file, nothing else."""
            response = self.claude.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=1500,
                temperature=0,
                messages=[{"role": "user", "content": prompt}]
            )
            
            code = response.content[0].text
            # Remove markdown code blocks if present
            if code.startswith('```') and code.endswith('```'):
                code = code.split('\n', 1)[1].rsplit('\n', 1)[0]
            elif code.startswith('```typescript'):
                code = code.split('\n', 1)[1].rsplit('```', 1)[0]
                
            with open(src_path, 'w') as f:
                f.write(code)
                
            result = subprocess.run(['npm', 'test', test_path], capture_output=True, text=True, cwd=test_path.parent.parent)
            
            if result.returncode == 0:
                print(f"✓ Tests passing for {test_path.name}")
                success = True
            else:
                print(f"✗ Tests failed (attempt {attempts + 1}/{max_attempts})")
                print(result.stderr)
                attempts += 1

def main():
    if len(sys.argv) != 2:
        print("Usage: tdd.py <project_directory>")
        sys.exit(1)

    try:
        project_root = Path(sys.argv[1]).resolve()
        test_dir = project_root / 'tests'
        src_dir = project_root / 'src'
        
        if not project_root.exists():
            print(f"Error: Project directory '{project_root}' does not exist")
            sys.exit(1)
        
        if not all(d.exists() for d in [test_dir, src_dir]):
            print(f"Error: Project must contain both 'tests' and 'src' directories")
            sys.exit(1)
        
        event_handler = TestWatcher(project_root)
        observer = Observer()
        observer.schedule(event_handler, str(test_dir), recursive=False)
        observer.start()
        
        print(f"Watching for TypeScript test files in {test_dir}")
        print("Press Ctrl+C to exit")
        
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        observer.stop()
        observer.join()
    except Exception as e:
        print(f"Error: {e}")
        raise

if __name__ == "__main__":
    main()
