import re
import json

def grade_code_execution(response_text: str, expected_data: dict) -> bool:
    """Extracts a Python code block from the model response, executes it, and verifies it against test cases."""
    # We look for markdown code blocks enclosed in ```python ... ```.
    # re.DOTALL makes the dot (.) match newline characters, allowing us to capture multi-line code blocks.
    code_match = re.search(r"```python\s*(.*?)\s*```", response_text, re.DOTALL)
    if not code_match:
        # Fallback: if they omitted "python" and just wrote ``` ... ```
        code_match = re.search(r"```\s*(.*?)\s*```", response_text, re.DOTALL)
        if not code_match:
            return False
            
    code = code_match.group(1).strip()
    
    # We create a dictionary to act as a local scope for executing the code.
    # This prevents the executed code from modifying our global variables.
    local_scope = {}
    try:
        # exec() dynamically compiles and runs Python code.
        exec(code, {}, local_scope)
    except Exception as e:
        # If the code fails to compile or runs into a syntax error during load, it is invalid.
        print(f" (Code execution failed to compile/run: {e})")
        return False
        
    # Retrieve the function using the entry_point name specified in tasks.py
    func = local_scope.get(expected_data["entry_point"])
    if not func or not callable(func):
        return False
        
    # We iterate over the test cases. If any test case fails, the model fails the task.
    for case in expected_data["test_cases"]:
        try:
            # We call the function using argument unpacking (*args) to pass positional arguments from the list.
            result = func(*case["args"])
            if result != case["output"]:
                return False
        except Exception as e:
            # If the function crashes when running a test case (e.g. NullPointerException/IndexError equivalent in Python).
            return False
            
    return True

def grade_substring(response_text: str, expected_substrings: list[str]) -> bool:
    """Returns True if any of the expected substrings are found in the response (case-insensitive)."""
    text_lower = response_text.lower()
    # We check if at least one of the expected keywords is present.
    # any() returns True if any item in the loop evaluates to True.
    return any(sub.lower() in text_lower for sub in expected_substrings)

def grade_math(response_text: str, expected_number: int) -> bool:
    """Extracts all numbers from the response and verifies if the final number matches the expected integer."""
    # \b\d+\b matches distinct integer numbers (using word boundaries \b to avoid matching part of a word/decimal).
    numbers = re.findall(r"\b\d+\b", response_text)
    if not numbers:
        return False
        
    # We compare the last number in the list of found numbers.
    # In math solutions, the final sentence typically contains the actual answer (e.g., 'Therefore, the answer is 60').
    # Using index -1 fetches the last element in Python lists.
    return int(numbers[-1]) == expected_number

def grade_writing_keywords(response_text: str, expected_keywords: list[str]) -> bool:
    """Verifies that all specified keywords are present in the response (case-insensitive)."""
    text_lower = response_text.lower()
    # all() returns True only if every single item in the loop evaluates to True.
    return all(keyword.lower() in text_lower for keyword in expected_keywords)

def grade_writing_format(response_text: str, expected_constraints: dict) -> bool:
    """Checks that the text adheres to maximum word count and exact bullet count constraints."""
    # Word count: splitting by whitespace gives a list of words.
    words = response_text.split()
    if len(words) > expected_constraints["max_words"]:
        return False
        
    # Bullet count: count how many lines start with the designated bullet character.
    lines = response_text.splitlines()
    bullet_count = 0
    for line in lines:
        clean_line = line.strip()
        if clean_line.startswith(expected_constraints["bullet_char"]):
            bullet_count += 1
            
    return bullet_count == expected_constraints["exact_bullets"]

def grade_tool_call(response_data: dict, expected_calls: dict) -> bool:
    """Inspects the API response object to confirm the model successfully invoked the required tools with expected arguments."""
    choices = response_data.get("choices", [])
    if not choices:
        return False
        
    message = choices[0].get("message", {})
    tool_calls = message.get("tool_calls", [])
    if not tool_calls:
        return False
        
    # For each expected tool call, we look for a matching call in the actual response.
    for req in expected_calls["required_calls"]:
        found = False
        for tc in tool_calls:
            func = tc.get("function", {})
            if func.get("name") == req["name"]:
                # The API returns arguments as a JSON string; we parse it back into a Python dict.
                args_raw = func.get("arguments", "{}")
                if isinstance(args_raw, str):
                    try:
                        args = json.loads(args_raw)
                    except Exception:
                        args = {}
                else:
                    args = args_raw
                    
                # We verify that all required arguments match (case-insensitive substring check).
                arg_match = True
                for k, expected_v in req["arguments"].items():
                    actual_v = args.get(k)
                    if not actual_v or str(expected_v).lower() not in str(actual_v).lower():
                        arg_match = False
                        break
                        
                if arg_match:
                    found = True
                    break
        if not found:
            return False
            
    return True
