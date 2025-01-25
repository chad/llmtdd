import os
import time
import sys
import subprocess
import hashlib
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import anthropic
from colorama import init, Fore, Style
import re

init(autoreset=True)

def run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Executes a command and returns the result."""
    try:
        start_time = time.time()
        print(f"{Fore.BLUE}Executing command: {Style.BRIGHT}{' '.join(command)}")
        result = subprocess.run(command, capture_output=True, text=True, cwd=cwd, check=False)
        elapsed_time = time.time() - start_time
        print(f"{Fore.BLUE}Command finished in: {elapsed_time:.2f}s")
        return result
    except FileNotFoundError:
        print(f"{Fore.RED}Error: Command not found: {' '.join(command)}")
        sys.exit(1)
    except Exception as e:
        print(f"{Fore.RED}Error running command {command}: {e}")
        sys.exit(1)

def extract_code_from_response(response: str) -> str:
    """
    Extracts code from a Claude response, handling various markdown code block formats.
    If no code block is found, returns the original string.
    """
    # Regex to match any markdown code block (``` ... ```)
    code_block_regex = re.compile(r'```(?:[a-zA-Z]+)?\n(.*?)\n```', re.DOTALL)

    match = code_block_regex.search(response)
    if match:
        # Return just the content of the first code block
        return match.group(1)
    else:
        # No code block found, return the full response
        print(f"{Fore.YELLOW}Warning: No code block found in Claude response, returning full response")
        return response

def hash_file_content(content: str) -> str:
    """Generates an SHA-256 hash of the file content."""
    return hashlib.sha256(content.encode()).hexdigest()
class TestWatcher(FileSystemEventHandler):
    def __init__(self, project_root: Path):
        self.test_dir = project_root.joinpath('tests')
        self.src_dir = project_root.joinpath('src')
        self.claude = anthropic.Anthropic(api_key=os.environ["CLAUDE_KEY"])
        self.cache = {}  # Cache to store file content hashes and generated code

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.test.ts'):
            print(f"{Fore.CYAN}Detected change in {Style.BRIGHT}{event.src_path}")
            time.sleep(1)
            self.process_test_file(Path(event.src_path))

    def process_test_file(self, test_path: Path):
        print(f"{Fore.YELLOW}Processing {Style.BRIGHT}{test_path.name}")

        with open(test_path) as f:
            test_content = f.read()

        test_hash = hash_file_content(test_content)

        if test_hash in self.cache:
            print(f"{Fore.GREEN}Cache hit for {Style.BRIGHT}{test_path.name}")
            cached_code = self.cache[test_hash]
            self.write_code_and_run_tests(test_path, cached_code, test_hash)
            return

        src_path = self.src_dir.joinpath(test_path.name.replace('.test.ts', '.ts'))
        success = False
        attempts = 0
        max_attempts = 5
        result = None  # Initialize result variable here
        error_messages = ""

        while not success and attempts < max_attempts:

            prompt_prefix = f"""Implement the following TypeScript tests. Do not include any other text except the code itself."""

            if error_messages:
                prompt_prefix = f"""Implement the following TypeScript tests, and be sure to export the necessary functions/types to make the tests pass.  Do not include any other text except the code itself. The previous attempt failed with the following errors: {error_messages}

                Specifically, ensure that any module that needs to be imported by another module is exported from that module.  If any test fails due to a missing export, be sure to export the missing member from that module."""

            prompt = f"""{prompt_prefix}

{test_content}"""


            print(f"\n{Fore.MAGENTA}Attempt {attempts + 1}/{max_attempts}: Asking Claude to generate code...")
            if attempts > 0 and result:
               print(f"{Fore.YELLOW}Including previous error feedback:{Style.DIM}\n{result.stderr}")


            response = self.claude.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=1500,
                temperature=0,
                messages=[{"role": "user", "content": prompt}]
            )

            print(f"{Fore.MAGENTA}Claude generated {len(response.content[0].text)} characters of code")

            code = extract_code_from_response(response.content[0].text)
            result = self.write_code_and_run_tests(test_path, code, test_hash)
            if result.returncode == 0:
                self.cache[test_hash] = code  # Store in cache after successful write and test
                success = True
            else:
                print(f"{Fore.RED}Test failed after code generation. Clearing cache for {Style.BRIGHT}{test_path.name}")
                if test_hash in self.cache:
                    del self.cache[test_hash]  # Clear cache if tests fail

                error_messages = result.stderr


    def write_code_and_run_tests(self, test_path: Path, code: str, test_hash: str) -> subprocess.CompletedProcess:
        src_path = self.src_dir.joinpath(test_path.name.replace('.test.ts', '.ts'))

        if not src_path.exists():
            print(f"{Fore.CYAN}Creating new file {Style.BRIGHT}{src_path}")

        with open(src_path, 'w') as f:
            f.write(code)

        print(f"{Fore.CYAN}Running tests...")
        result = run_command(['npm', 'test', str(test_path)], test_path.parent.parent)

        if result.returncode == 0:
            print(f"{Fore.GREEN}Γ£ô Tests passing for {Style.BRIGHT}{test_path.name}")
        else:
            print(f"{Fore.RED}Γ£ù Tests failed {Style.BRIGHT} after generating code with caching")
            print(f"{Fore.RED}Command: {' '.join(['npm', 'test', str(test_path)])}")
            print(f"{Fore.RED}Error message: {result.stderr}")
        return result

def main():
    if len(sys.argv) != 2:
        print("Usage: tdd.py <project_directory>")
        sys.exit(1)

    try:
        project_root = Path(sys.argv[1]).resolve()
        test_dir = project_root.joinpath('tests')
        src_dir = project_root.joinpath('src')

        if not project_root.exists():
            print(f"{Fore.RED}Error: Project directory '{project_root}' does not exist")
            sys.exit(1)

        if not all(d.exists() for d in [test_dir, src_dir]):
            print(f"Error: Project must contain both 'tests' and 'src' directories")
            sys.exit(1)

        event_handler = TestWatcher(project_root)
        observer = Observer()
        observer.schedule(event_handler, str(test_dir), recursive=False)
        observer.start()

        print(f"{Fore.CYAN}Watching for TypeScript test files in {Style.BRIGHT}{test_dir}")
        print(f"{Fore.YELLOW}Press Ctrl+C to exit")

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
