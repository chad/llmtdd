import os
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import anthropic
import subprocess
import json

class TestWatcher(FileSystemEventHandler):
    def __init__(self, test_dir: Path, src_dir: Path):
        self.test_dir = test_dir
        self.src_dir = src_dir
        self.claude = anthropic.Anthropic(api_key=os.environ["CLAUDE_KEY"])
        
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.test.ts'):
            print(event)
            time.sleep(1)  # Wait for file writes to complete
            self.process_test_file(Path(event.src_path))
            
    def process_test_file(self, test_path: Path):
        # Read the test file
        with open(test_path) as f:
            test_content = f.read()
            
        # Generate corresponding source file path
        src_path = self.src_dir / test_path.name.replace('.test.ts', '.ts')
        
        success = False
        attempts = 0
        max_attempts = 5
        
        while not success and attempts < max_attempts:
            # Generate production code
            prompt = f"""Given these TypeScript tests, generate production code that will make them pass:

{test_content}

Respond only with the TypeScript code that should go in the source file, nothing else."""

            response = self.claude.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=1500,
                temperature=0,
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Save generated code
            with open(src_path, 'w') as f:
                f.write(response.content[0].text)
                
            # Run tests
            result = subprocess.run(['npm', 'test', test_path], capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"✅ Tests passing for {test_path.name}")
                success = True
            else:
                print(f"❌ Tests failed (attempt {attempts + 1}/{max_attempts})")
                print(result.stderr)
                attempts += 1

def main():
    try:
        # Configure paths
        test_dir = Path('./tests')
        print(test_dir.resolve())
        src_dir = Path('./src')
        
        # Ensure directories exist
        test_dir.mkdir(exist_ok=True)
        src_dir.mkdir(exist_ok=True)
        
        # Set up file watching
        event_handler = TestWatcher(test_dir, src_dir)
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
